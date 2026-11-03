"""v1.4b advisory restock planning. No auto-purchase or spurious zero-sales forecasts.

ROP = ceil(units_sold / observed_window * lead_time_days) + safety_stock_units
Suggested quantity = max(0, ceil(units_sold / observed_window * (lead_time_days+review_days))
                         + safety_stock_units - current_stock).
No quantity is proposed until a product has explicitly configured supplier settings,
full registration age for the window, and non-zero recorded sales.
"""
from io import BytesIO, StringIO
import csv

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment

from app.database import connection
from app.services.audit import write_audit
from app.services.inventory_intelligence import analyze_inventory, WINDOWS
from app.services.reports import safe_text

MAX_LEAD = 365
MAX_REVIEW = 90
MAX_SAFETY = 1_000_000
STATUSES = ('all', 'due', 'unconfigured', 'insufficient', 'healthy')
EXPORT_COLUMNS = [
    ('sku', 'SKU'), ('name', 'Produk'), ('category', 'Kategori'),
    ('current_stock', 'Stok Sekarang'), ('min_stock', 'Stok Minimum'),
    ('units_sold', 'Unit Terjual'), ('velocity_raw', 'Unit per Hari'),
    ('lead_time_days', 'Lead Time (Hari)'), ('safety_stock_units', 'Safety Stock (Unit)'),
    ('review_days', 'Periode Tinjau (Hari)'), ('reorder_point', 'Reorder Point (Unit)'),
    ('suggested_qty', 'Saran Pembelian (Unit)'), ('status_label', 'Status'),
    ('reason', 'Penjelasan'),
]


def _parse_integer(raw, label, lo, hi):
    value = str(raw).strip()
    if not value.isascii() or not value.isdecimal():
        raise ValueError(f'{label} harus bilangan bulat antara {lo} dan {hi}.')
    number = int(value)
    if not lo <= number <= hi:
        raise ValueError(f'{label} harus antara {lo} dan {hi}.')
    return number


def save_reorder_settings(product_id, lead_time_days, safety_stock_units, review_days, *, actor_id):
    lead = _parse_integer(lead_time_days, 'Lead time', 1, MAX_LEAD)
    safety = _parse_integer(safety_stock_units, 'Safety stock', 0, MAX_SAFETY)
    review = _parse_integer(review_days, 'Periode tinjau', 1, MAX_REVIEW)
    with connection() as db:
        db.execute('BEGIN IMMEDIATE')
        product = db.execute('SELECT id,sku,is_active FROM products WHERE id=?', (product_id,)).fetchone()
        if not product or not product['is_active']:
            raise ValueError('Produk aktif tidak ditemukan.')
        old = db.execute('SELECT lead_time_days,safety_stock_units,review_days '
                         'FROM reorder_settings WHERE product_id=?', (product_id,)).fetchone()
        before = dict(old) if old else None
        after = {'lead_time_days': lead, 'safety_stock_units': safety, 'review_days': review}
        if before != after:
            db.execute('''INSERT INTO reorder_settings(product_id,lead_time_days,safety_stock_units,review_days)
                VALUES (?,?,?,?) ON CONFLICT(product_id) DO UPDATE SET
                lead_time_days=excluded.lead_time_days,
                safety_stock_units=excluded.safety_stock_units,
                review_days=excluded.review_days,
                updated_at=datetime('now')''', (product_id, lead, safety, review))
            write_audit(db, actor_id, 'reorder.settings_updated', 'product', product_id,
                        before=before, after=after, summary=f'Parameter reorder produk {product["sku"]} diperbarui')
        db.commit()
    return before != after


def restock_recommendations(days=30, *, today=None, q='', category='', status='all'):
    if type(days) is not int or days not in WINDOWS:
        raise ValueError('Periode harus 7, 30, atau 90 hari.')
    if status not in STATUSES:
        raise ValueError('Status filter tidak dikenal.')
    data = analyze_inventory(days, today=today, q=q, category=category)
    with connection() as db:
        settings = {row['product_id']: dict(row) for row in db.execute(
            'SELECT product_id,lead_time_days,safety_stock_units,review_days FROM reorder_settings')}
    for product in data['rows']:
        config = settings.get(product['id'])
        product['configured'] = config is not None
        product['lead_time_days'] = config['lead_time_days'] if config else None
        product['safety_stock_units'] = config['safety_stock_units'] if config else None
        product['review_days'] = config['review_days'] if config else None
        product['reorder_point'] = None
        product['suggested_qty'] = None
        if not config:
            product['plan_status'] = 'unconfigured'
            product['status_label'] = 'Atur parameter'
            product['reason'] = 'Masukkan lead time pemasok, safety stock, dan periode tinjau terlebih dahulu.'
        elif product['is_new']:
            product['plan_status'] = 'insufficient'
            product['status_label'] = 'Data masih terbatas'
            product['reason'] = (f'Produk terdaftar {product["age_days"]} hari, belum mencapai '
                                 f'periode {days} hari. Periksa batas stok minimum secara manual.')
        elif product['units_sold'] == 0:
            product['plan_status'] = 'insufficient'
            product['status_label'] = 'Belum ada penjualan'
            product['reason'] = 'Tidak ada penjualan dalam periode terpilih; periksa stok minimum secara manual.'
        else:
            # Integer-ceiling formulation avoids floating rounding artifacts.
            demand_lead = (product['units_sold'] * config['lead_time_days'] + days - 1) // days
            demand_target = (product['units_sold'] * (config['lead_time_days'] + config['review_days'])
                             + days - 1) // days
            point = demand_lead + config['safety_stock_units']
            suggested = max(0, demand_target + config['safety_stock_units'] - product['current_stock'])
            product['reorder_point'] = point
            if product['current_stock'] <= point:
                product['plan_status'] = 'due'
                product['status_label'] = 'Perlu pesan ulang'
                product['suggested_qty'] = max(1, suggested)
                product['reason'] = ('Stok ≤ reorder point. Kuantitas indikatif untuk memenuhi '
                                     'permintaan selama lead time + periode tinjau, termasuk safety stock.')
            else:
                product['plan_status'] = 'healthy'
                product['status_label'] = 'Belum perlu pesan'
                product['suggested_qty'] = 0
                product['reason'] = 'Stok masih di atas reorder point berdasarkan laju penjualan historis.'
    counts = {key: sum(row['plan_status'] == key for row in data['rows'])
              for key in STATUSES if key != 'all'}
    total = len(data['rows'])
    if status != 'all':
        data['rows'] = [p for p in data['rows'] if p['plan_status'] == status]
    order = {'due':0,'insufficient':1,'unconfigured':2,'healthy':3}
    data['rows'].sort(key=lambda p: (order[p['plan_status']],p['name'].casefold()))
    data.update({'status':status,'counts':counts,'total_products':total,
                 'visible_count':len(data['rows'])})
    return data


def restock_csv(data):
    output = StringIO()
    output.write('\ufeff')
    writer = csv.writer(output)
    writer.writerow([header for _,header in EXPORT_COLUMNS])
    for p in data['rows']:
        writer.writerow([safe_text(p[key]) if isinstance(p[key], str) else
                         ('' if p[key] is None else p[key]) for key,_ in EXPORT_COLUMNS])
    return output.getvalue().encode('utf-8')


def restock_xlsx(data):
    wb = Workbook()
    ws = wb.active
    ws.title = 'Rekomendasi'
    ws.append([header for _,header in EXPORT_COLUMNS])
    for p in data['rows']:
        ws.append([safe_text(p[key]) if isinstance(p[key], str) else p[key] for key,_ in EXPORT_COLUMNS])
    ws.freeze_panes='A2'
    ws.auto_filter.ref=ws.dimensions
    for col in ws.columns:
        letter=col[0].column_letter
        ws.column_dimensions[letter].width = 34 if letter in ('B','N') else (22 if letter in ('A','C','M') else 19)
    summary=wb.create_sheet('Metodologi')
    for entry in [
        ('Indikator', 'Keterangan'),
        ('Periode mulai', data['start']), ('Periode akhir', data['as_of']),
        ('Jendela hari', data['days']), ('Produk tampil', data['visible_count']),
        ('Produk perlu pesan', data['counts']['due']),
        ('Rumus ROP', 'CEIL(unit terjual / hari periode x lead time) + safety stock'),
        ('Rumus saran qty', 'Saat stok <= ROP: MAX(1, CEIL(unit terjual / hari periode x (lead time + periode tinjau)) + safety stock - stok); jika tidak, 0'),
        ('Syarat', 'Parameter diisi; usia produk >= periode; ada penjualan dalam periode.'),
        ('Catatan', 'Rekomendasi bersifat indikatif, bukan pesanan pembelian otomatis atau prediksi ML.'),
        ('Catatan', 'Data demo sintetis tidak merepresentasikan permintaan bisnis nyata.'),
    ]:
        summary.append(entry)
    summary.column_dimensions['A'].width=24
    summary.column_dimensions['B'].width=105
    for sh in wb:
        sh.sheet_view.showGridLines=False
        for cell in sh[1]:
            cell.fill=PatternFill('solid',fgColor='173650')
            cell.font=Font(bold=True,color='FFFFFF')
            cell.alignment=Alignment(wrap_text=True,vertical='center')
        sh.row_dimensions[1].height=28
    bio=BytesIO()
    wb.save(bio)
    return bio.getvalue()
