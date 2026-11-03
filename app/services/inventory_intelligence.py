"""v1.4a: descriptive unit-based sales velocity and slow-moving analytics.

Intentionally avoids profitability, purchasing costs, and ML forecasts: no cost basis
or reliable sales history duration is available in the v1.x schema.
"""
from datetime import date, datetime, timedelta
from io import BytesIO, StringIO
import csv

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from app.database import connection
from app.services.reports import safe_text

WINDOWS = (7, 30, 90)
FILTERS = ('all', 'slow', 'new', 'no_sales', 'out_of_stock')
SLOW_THRESHOLD = 2
EXPORT_COLUMNS = (
    ('sku', 'SKU'), ('name', 'Produk'), ('category', 'Kategori'),
    ('registered_at', 'Tanggal Terdaftar'), ('current_stock', 'Stok Sekarang'),
    ('min_stock', 'Stok Minimum'), ('units_sold', 'Unit Terjual'),
    ('revenue', 'Omzet Periode (Rp)'), ('velocity', 'Rata-rata Unit/Hari'),
    ('coverage_days', 'Estimasi Cakupan Stok (Hari)'), ('classification', 'Klasifikasi')
)


def _registered_date(raw: str, today: date) -> date:
    try:
        return date.fromisoformat(str(raw)[:10])
    except (ValueError, TypeError):
        return today  # dates are recorded by SQLite at insertion


def analyze_inventory(days=30, *, today=None, q='', category='', classification='all'):
    """Return all matching active products and KPIs, with a fixed-length day denominator.

    Slow-moving = current_stock > 0, registered >= window length, and 0..2 units sold
    within the chosen window. The registration age is from the app DB only, *not*
    evidence of when the merchant started selling the product.
    """
    if type(days) is not int or days not in WINDOWS:
        raise ValueError('Periode harus 7, 30, atau 90 hari.')
    if classification not in FILTERS:
        raise ValueError('Filter klasifikasi tidak dikenal.')
    today = today or date.today()
    if not isinstance(today, date) or isinstance(today, datetime):
        raise ValueError('Tanggal analisis tidak valid.')
    start = today - timedelta(days=days - 1)
    query = '%' + str(q).strip()[:100] + '%'
    category_filter = str(category).strip()[:80]
    with connection() as db:
        # Aggregate sales first, then join inventory (ledger SUM) once per product.
        # Date bounds explicitly exclude future transactions.
        rows = [dict(r) for r in db.execute("""
            SELECT p.id, p.sku, p.name, p.category, p.min_stock,
                   substr(p.created_at, 1, 10) AS registered_at,
                   inv.current_stock, COALESCE(s.units_sold, 0) AS units_sold,
                   COALESCE(s.revenue, 0) AS revenue
            FROM products p
            JOIN product_inventory inv ON inv.id=p.id
            LEFT JOIN (
                SELECT i.product_id, SUM(i.quantity) AS units_sold,
                       SUM(i.line_total) AS revenue
                FROM transaction_items i
                JOIN transactions t ON t.id=i.transaction_id
                WHERE t.sold_at >= ? AND t.sold_at <= ?
                GROUP BY i.product_id
            ) s ON s.product_id=p.id
            WHERE p.is_active=1
              AND (p.sku LIKE ? OR p.name LIKE ? OR p.category LIKE ?)
              AND (? = '' OR p.category = ? COLLATE NOCASE)
            ORDER BY p.name COLLATE NOCASE, p.id
        """, (start.isoformat(), today.isoformat(), query, query, query,
              category_filter, category_filter))]
        categories = [r['category'] for r in db.execute(
            'SELECT DISTINCT category FROM products WHERE is_active=1 ORDER BY category COLLATE NOCASE')]

    enriched = []
    for r in rows:
        age = max(0, (today - _registered_date(r['registered_at'], today)).days + 1)
        r['age_days'] = age
        r['is_new'] = age < days
        r['velocity_raw'] = r['units_sold'] / days
        r['velocity'] = round(r['velocity_raw'], 3)
        r['coverage_days'] = (round(r['current_stock'] / r['velocity_raw'], 1)
                              if r['velocity_raw'] > 0 and r['current_stock'] > 0 else None)
        r['is_slow'] = bool(r['current_stock'] > 0 and not r['is_new']
                            and r['units_sold'] <= SLOW_THRESHOLD)
        if r['current_stock'] == 0:
            r['classification'] = 'Stok habis'
            r['class_code'] = 'out_of_stock'
        elif r['is_new']:
            r['classification'] = 'Produk baru'
            r['class_code'] = 'new'
        elif r['is_slow']:
            r['classification'] = 'Lambat terjual'
            r['class_code'] = 'slow'
        else:
            r['classification'] = 'Aktif terjual'
            r['class_code'] = 'active'
        enriched.append(r)

    if classification == 'slow':
        visible = [r for r in enriched if r['is_slow']]
    elif classification == 'new':
        visible = [r for r in enriched if r['is_new']]
    elif classification == 'no_sales':
        visible = [r for r in enriched if r['units_sold'] == 0]
    elif classification == 'out_of_stock':
        visible = [r for r in enriched if r['current_stock'] == 0]
    else:
        visible = enriched
    priority = {'out_of_stock': 0, 'slow': 1, 'new': 2, 'active': 3}
    visible.sort(key=lambda r: (priority[r['class_code']],
                                r['coverage_days'] if r['coverage_days'] is not None else float('inf'),
                                r['name'].casefold()))
    return {
        'days': days, 'as_of': today.isoformat(), 'start': start.isoformat(),
        'q': str(q).strip()[:100], 'category': category_filter, 'classification': classification,
        'categories': categories, 'rows': visible,
        'total_products': len(enriched), 'visible_count': len(visible),
        'total_units': sum(r['units_sold'] for r in enriched),
        'slow_count': sum(r['is_slow'] for r in enriched),
        'new_count': sum(r['is_new'] for r in enriched),
        'no_sales_count': sum(r['units_sold'] == 0 for r in enriched),
        'out_count': sum(r['current_stock'] == 0 for r in enriched),
    }


def intelligence_csv(result):
    out = StringIO()
    out.write('\ufeff')
    writer = csv.writer(out)
    writer.writerow([header for key, header in EXPORT_COLUMNS])
    for row in result['rows']:
        writer.writerow([safe_text(row[key]) if isinstance(row[key], str) else
                         ('' if row[key] is None else row[key])
                         for key, header in EXPORT_COLUMNS])
    return out.getvalue().encode('utf-8')


def intelligence_xlsx(result):
    book = Workbook()
    summary = book.active
    summary.title = 'Ringkasan'
    for row in [
        ('Indikator', 'Nilai'), ('Periode mulai', result['start']),
        ('Periode akhir', result['as_of']), ('Jendela hari', result['days']),
        ('Produk pada filter pencarian', result['total_products']),
        ('Produk ditampilkan', result['visible_count']),
        ('Unit terjual', result['total_units']),
        ('Produk lambat terjual', result['slow_count']),
        ('Produk baru', result['new_count']),
        ('Produk tanpa penjualan', result['no_sales_count']),
        ('Stok habis', result['out_count']),
        ('Catatan', 'Lambat terjual: stok > 0, terdaftar >= periode, terjual <= 2 unit.'),
        ('Catatan', 'Kecepatan = unit terjual / jumlah hari periode; data demo bukan transaksi nyata.'),
        ('Catatan', 'Cakupan stok hanyalah perkiraan jika laju penjualan konstan.'),
    ]:
        summary.append(row)
    summary.column_dimensions['A'].width = 34
    summary.column_dimensions['B'].width = 88
    detail = book.create_sheet('Analisis Produk')
    detail.append([header for key, header in EXPORT_COLUMNS])
    for row in result['rows']:
        detail.append([safe_text(row[key]) if isinstance(row[key], str) else row[key]
                       for key, header in EXPORT_COLUMNS])
    detail.freeze_panes = 'A2'
    detail.auto_filter.ref = detail.dimensions
    for col in 'ABCD':
        detail.column_dimensions[col].width = {'A':20,'B':34,'C':22,'D':22}[col]
    for col in 'EFGHIJK':
        detail.column_dimensions[col].width = 23
    for sheet in book:
        sheet.sheet_view.showGridLines = False
        for cell in sheet[1]:
            cell.fill = PatternFill('solid', fgColor='173650')
            cell.font = Font(bold=True, color='FFFFFF')
            cell.alignment = Alignment(vertical='center', wrap_text=True)
        sheet.row_dimensions[1].height = 28
    for cells in detail.iter_cols(min_col=8, max_col=8, min_row=2):
        for cell in cells:
            cell.number_format = '"Rp" #,##0'
    for cells in detail.iter_cols(min_col=9, max_col=10, min_row=2):
        for cell in cells:
            cell.number_format = '0.0##'
    output = BytesIO()
    book.save(output)
    return output.getvalue()
