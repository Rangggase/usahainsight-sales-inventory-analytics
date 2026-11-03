"""v1.4a: descriptive inventory analytics, period boundaries, exports and access."""
from datetime import date, timedelta
from io import BytesIO

import pytest
from fastapi.testclient import TestClient as PlainClient
from openpyxl import load_workbook

from app.database import connection
from app.main import app
from app.services.inventory_intelligence import analyze_inventory, intelligence_csv, intelligence_xlsx
from tests.client import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('USAHAINSIGHT_DB', str(tmp_path / 'insights.db'))
    with TestClient(app) as c:
        yield c


def register_product(sku, *, stock=10, age=120, category='Testing'):
    created = date.today() - timedelta(days=age - 1)
    with connection() as db:
        cur = db.execute('''INSERT INTO products(sku,name,category,unit_price,min_stock,created_at)
          VALUES(?,?,?,?,?,?)''', (sku, 'Produk '+sku, category, 12000, 3, created.isoformat()+' 10:00:00'))
        product_id = cur.lastrowid
        db.execute('''INSERT INTO stock_movements(product_id,movement_type,delta) VALUES(?,?,?)''',
                   (product_id, 'initial', stock))
        db.commit()
    return product_id


def sell_direct(product_id, days_ago, units=1, *, invoice='INS-1'):
    day = date.today() - timedelta(days=days_ago)
    with connection() as db:
        cur=db.execute('INSERT INTO transactions(invoice_no,sold_at) VALUES (?,?)',
                       (invoice, day.isoformat()))
        db.execute('''INSERT INTO transaction_items(transaction_id,product_id,quantity,unit_price,line_total)
                      VALUES(?,?,?,?,?)''', (cur.lastrowid, product_id, units, 12000, units*12000))
        db.commit()


def lookup(result, sku):
    return next(r for r in result['rows'] if r['sku'] == sku)


def test_velocities_boundaries_and_no_future_sales(client):
    prod = register_product('VEL-TEST')
    sell_direct(prod, 29, 2, invoice='VEL-29')
    sell_direct(prod, 30, 5, invoice='VEL-30')
    sell_direct(prod, 7, 3, invoice='VEL-7')
    sell_direct(prod, 6, 1, invoice='VEL-6')
    sell_direct(prod, -1, 20, invoice='VEL-FUTURE')
    r7 = lookup(analyze_inventory(7), 'VEL-TEST')
    assert r7['units_sold'] == 1
    assert r7['velocity_raw'] == pytest.approx(1/7)
    assert r7['coverage_days'] == 70.0
    r30 = lookup(analyze_inventory(30), 'VEL-TEST')
    assert r30['units_sold'] == 6  # 29+7+6 days are all within window
    assert r30['velocity_raw'] == pytest.approx(6/30)
    assert r30['coverage_days'] == 50.0
    r90 = lookup(analyze_inventory(90), 'VEL-TEST')
    assert r90['units_sold'] == 11
    assert r90['revenue'] == 11 * 12000


def test_zero_sales_non_division_and_slow_moving(client):
    old = register_product('OLD-NO-SALE', age=95, stock=12)
    result = analyze_inventory(90)
    row = lookup(result, 'OLD-NO-SALE')
    assert row['is_slow'] and row['classification']=='Lambat terjual'
    assert row['velocity']==0 and row['coverage_days'] is None
    assert old > 0
    filtered=analyze_inventory(90, classification='slow')
    assert 'OLD-NO-SALE' in [p['sku'] for p in filtered['rows']]


def test_new_product_not_false_slow(client):
    register_product('NEW-NO-SALE', age=2, stock=7)
    result=analyze_inventory(30)
    row=lookup(result, 'NEW-NO-SALE')
    assert row['is_new'] and not row['is_slow']
    assert row['classification']=='Produk baru'
    assert 'NEW-NO-SALE' not in [p['sku'] for p in analyze_inventory(30, classification='slow')['rows']]
    assert 'NEW-NO-SALE' in [p['sku'] for p in analyze_inventory(30, classification='no_sales')['rows']]


def test_out_of_stock_not_slow_and_archived_excluded(client):
    register_product('OLD-EMPTY', age=95, stock=0)
    archived = register_product('OLD-ARCHIVED', age=95, stock=0)
    with connection() as db:
        db.execute('UPDATE products SET is_active=0 WHERE id=?',(archived,))
        db.commit()
    result=analyze_inventory(30)
    row=lookup(result,'OLD-EMPTY')
    assert row['classification']=='Stok habis' and not row['is_slow']
    assert all(p['sku']!='OLD-ARCHIVED' for p in result['rows'])


def test_category_search_and_parameter_validation(client):
    register_product('SHOP-SEALED', age=60, category='Bahan')
    assert 'SHOP-SEALED' in [r['sku'] for r in analyze_inventory(30,q='sealed',category='Bahan')['rows']]
    assert 'SHOP-SEALED' not in [r['sku'] for r in analyze_inventory(30,q='sealed',category="Bahan' OR 1=1 --")['rows']]
    with pytest.raises(ValueError): analyze_inventory(0)
    with pytest.raises(ValueError): analyze_inventory(30,classification='unknown')


def test_filtered_page_and_exports(client):
    register_product('EXPORT-OLD', age=95)
    html=client.get('/insights?days=90&status=slow')
    assert html.status_code==200
    assert 'Analitik Persediaan' in html.text
    assert 'EXPORT-OLD' in html.text
    csv_response=client.get('/insights/export?days=90&status=slow&format=csv')
    assert csv_response.status_code==200 and csv_response.content.startswith(b'\xef\xbb\xbf')
    assert b'EXPORT-OLD' in csv_response.content
    xlsx=client.get('/insights/export?days=90&status=slow&format=xlsx')
    assert xlsx.status_code==200 and xlsx.content[:2]==b'PK'
    book=load_workbook(BytesIO(xlsx.content),read_only=True)
    assert book.sheetnames==['Ringkasan','Analisis Produk']
    assert any(row[0]=='EXPORT-OLD' for row in list(book['Analisis Produk'].values)[1:])


def test_export_invalid_query_and_authentication(client, tmp_path, monkeypatch):
    assert client.get('/insights/export?days=8').status_code==400
    assert client.get('/insights/export?format=pdf').status_code==400
    client.cookies.clear()
    assert client.get('/insights',follow_redirects=False).status_code==303
    assert client.get('/insights/export?format=xlsx',follow_redirects=False).status_code==303


def test_csv_and_excel_formula_escaping(client):
    register_product('EXCEL-PREFIX',age=100)
    with connection() as db:
        db.execute("UPDATE products SET name='=HYPERLINK(1)' WHERE sku='EXCEL-PREFIX'")
        db.commit()
    result=analyze_inventory(30,q='EXCEL-PREFIX')
    assert "'=HYPERLINK(1)" in intelligence_csv(result).decode('utf-8-sig')
    book=load_workbook(BytesIO(intelligence_xlsx(result)))
    row=list(book['Analisis Produk'].values)[1]
    assert row[1]=="'=HYPERLINK(1)"
    assert book['Analisis Produk']['B2'].data_type!='f'
