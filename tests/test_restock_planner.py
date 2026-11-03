"""v1.4b deterministic replenishment planning, security, and compatibility."""
from datetime import date, timedelta
from io import BytesIO
import csv
import json
import sqlite3
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient as GuestClient
from openpyxl import load_workbook

from app.main import app
from app.database import connection, init_db
from app.services.restock_planner import (restock_recommendations, save_reorder_settings,
                                          restock_csv, restock_xlsx)
from tests.client import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('USAHAINSIGHT_DB', str(tmp_path/'restock.db'))
    with TestClient(app) as client:
        yield client


def make_product(sku='ROP-01', stock=10, age=100, min_stock=3):
    created=(date.today() - timedelta(days=age-1)).isoformat()+' 10:00:00'
    with connection() as db:
        cur=db.execute('''INSERT INTO products(sku,name,category,unit_price,min_stock,created_at)
            VALUES (?,?,?,?,?,?)''', (sku,'Produk '+sku,'Test Restock',10000,min_stock,created))
        pid=cur.lastrowid
        db.execute("INSERT INTO stock_movements(product_id,movement_type,delta) VALUES(?,'initial',?)",
                   (pid,stock))
        db.commit()
    return pid


def record_sale(pid, units, ago=0, invoice='ROP-SALE'):
    sold_on=(date.today()-timedelta(days=ago)).isoformat()
    with connection() as db:
        cur=db.execute('INSERT INTO transactions(invoice_no,sold_at) VALUES (?,?)',(invoice,sold_on))
        db.execute('INSERT INTO transaction_items(transaction_id,product_id,quantity,unit_price,line_total) VALUES (?,?,?,?,?)',
                   (cur.lastrowid,pid,units,10000,units*10000))
        db.commit()


def get_row(days=30, sku='ROP-01', **kwargs):
    return next(p for p in restock_recommendations(days,**kwargs)['rows'] if p['sku']==sku)


def test_migration_is_idempotent_and_legacy_data_unchanged(client):
    pid=make_product()
    with connection() as db:
        before=[tuple(r) for r in db.execute('SELECT id,sku,unit_price,min_stock FROM products')]
        assert db.execute("SELECT name FROM sqlite_master WHERE name='reorder_settings'").fetchone()
    init_db()
    with connection() as db:
        assert [tuple(r) for r in db.execute('SELECT id,sku,unit_price,min_stock FROM products')]==before
        assert db.execute('SELECT COUNT(*) FROM reorder_settings').fetchone()[0]==0
    assert pid>0


def test_missing_configuration_does_not_recommend(client):
    pid=make_product()
    record_sale(pid,60)
    p=get_row()
    assert p['plan_status']=='unconfigured'
    assert p['reorder_point'] is None and p['suggested_qty'] is None


def test_reorder_point_and_quantity_ceiling(client):
    pid=make_product()
    record_sale(pid,60)
    save_reorder_settings(pid,5,3,7,actor_id=None)
    p=get_row()
    assert p['units_sold']==60 and p['velocity_raw']==2
    assert p['reorder_point']==13 and p['suggested_qty']==17
    assert p['plan_status']=='due'
    assert 'ROP-01' in [r['sku'] for r in restock_recommendations(status='due')['rows']]
    with connection() as db:
        db.execute("INSERT INTO stock_movements(product_id,movement_type,delta) VALUES (?,'restock',5)",(pid,))
        db.commit()
    p=get_row()
    assert p['current_stock']==15 and p['plan_status']=='healthy' and p['suggested_qty']==0


def test_fractional_daily_sales_uses_ceil_correctly(client):
    pid=make_product(stock=3)
    record_sale(pid,1)
    save_reorder_settings(pid,5,0,4,actor_id=None)
    p=get_row()
    assert p['reorder_point']==1 and p['plan_status']=='healthy'
    assert p['suggested_qty']==0
    with connection() as db:
        db.execute("INSERT INTO stock_movements(product_id,movement_type,delta) VALUES (?,'adjustment',-2)",(pid,))
        db.commit()
    p=get_row()
    assert p['reorder_point']==1 and p['suggested_qty']==1 and p['plan_status']=='due'


def test_recent_registration_and_zero_sales_do_not_guess(client):
    young=make_product('ROP-NEW', age=2, stock=6)
    old=make_product('ROP-ZERO', age=95, stock=8)
    save_reorder_settings(young,5,3,7,actor_id=None)
    save_reorder_settings(old,5,3,7,actor_id=None)
    record_sale(young,50,invoice='NEW-SALE')
    for sku in ('ROP-NEW','ROP-ZERO'):
        row=get_row(sku=sku)
        assert row['plan_status']=='insufficient'
        assert row['reorder_point'] is None and row['suggested_qty'] is None
    assert len(restock_recommendations(status='insufficient')['rows'])>=2


def test_future_sale_excluded(client):
    pid=make_product()
    record_sale(pid,60,ago=-1)
    save_reorder_settings(pid,5,3,7,actor_id=None)
    assert get_row()['plan_status']=='insufficient'


@pytest.mark.parametrize('vals',[
    ('0','2','7'), ('366','2','7'), ('x','2','7'), ('5','-1','7'),
    ('5','1000001','7'), ('5','2','0'), ('5','2','91'), ('5','2','1.2'),
])
def test_invalid_configuration_does_not_write(client,vals):
    pid=make_product()
    with pytest.raises(ValueError):
        save_reorder_settings(pid,*vals,actor_id=None)
    with connection() as db:
        assert db.execute('SELECT COUNT(*) FROM reorder_settings').fetchone()[0]==0
        assert db.execute('SELECT COUNT(*) FROM audit_events').fetchone()[0]==0


def test_archived_product_excluded_from_view_and_configuration(client):
    pid=make_product(stock=0)
    with connection() as db:
        db.execute('UPDATE products SET is_active=0 WHERE id=?',(pid,))
        db.commit()
    assert all(p['id']!=pid for p in restock_recommendations()['rows'])
    with pytest.raises(ValueError):
        save_reorder_settings(pid,5,3,7,actor_id=None)


def test_audit_tracks_config_changes_but_not_duplicate_save(client):
    pid=make_product()
    from app.services.auth import get_session, COOKIE_NAME
    user=get_session(client.cookies[COOKIE_NAME])
    data={'lead_time_days':'5','safety_stock_units':'3','review_days':'7'}
    response=client.post(f'/restock-planner/{pid}/settings',data=data,follow_redirects=False)
    assert response.status_code==303
    assert 'Parameter%20berhasil' in response.headers['location']
    response=client.post(f'/restock-planner/{pid}/settings',data=data,follow_redirects=False)
    assert response.status_code==303
    changed=client.post(f'/restock-planner/{pid}/settings',data={**data,'safety_stock_units':'4'},follow_redirects=False)
    assert changed.status_code==303
    with connection() as db:
        ev=[dict(e) for e in db.execute('SELECT * FROM audit_events WHERE action=? ORDER BY id ASC',('reorder.settings_updated',))]
        assert len(ev)==2
        assert ev[0]['actor_user_id']==user['id']
        assert json.loads(ev[0]['after_json'])['safety_stock_units']==3
        assert json.loads(ev[1]['before_json'])['safety_stock_units']==3
        assert json.loads(ev[1]['after_json'])['safety_stock_units']==4
    assert 'reorder.settings_updated' in client.get('/audit').text


def test_atomic_rollback_when_audit_fails(client):
    pid=make_product()
    from app.services.auth import get_session, COOKIE_NAME
    user=get_session(client.cookies[COOKIE_NAME])
    with patch('app.services.restock_planner.write_audit', side_effect=RuntimeError('audit unavailable')):
        with pytest.raises(RuntimeError):
            save_reorder_settings(pid,5,3,7,actor_id=user['id'])
    with connection() as db:
        assert db.execute('SELECT COUNT(*) FROM reorder_settings').fetchone()[0]==0


def test_authenticated_page_and_exports(client):
    pid=make_product()
    record_sale(pid,60)
    save_reorder_settings(pid,5,3,7,actor_id=None)
    html=client.get('/restock-planner?days=30&status=due')
    assert html.status_code==200 and 'ROP-01' in html.text and 'Rekomendasi Restock' in html.text
    csv_response=client.get('/restock-planner/export?format=csv&days=30&status=due')
    assert csv_response.status_code==200
    assert csv_response.content.startswith(b'\xef\xbb\xbf')
    parsed=list(csv.reader(csv_response.content.decode('utf-8-sig').splitlines()))
    assert parsed[1][0]=='ROP-01'
    assert parsed[1][10]=='13' and parsed[1][11]=='17'
    xlsx=client.get('/restock-planner/export?format=xlsx&days=30&status=due')
    assert xlsx.status_code==200
    wb=load_workbook(BytesIO(xlsx.content))
    assert wb.sheetnames==['Rekomendasi','Metodologi']
    assert wb['Rekomendasi']['A2'].value=='ROP-01'
    assert wb['Rekomendasi']['K2'].value==13
    assert wb['Rekomendasi']['L2'].value==17
    assert 'ROP-01' not in client.get('/restock-planner?status=healthy').text


def test_export_input_validation_and_authentication(client,tmp_path,monkeypatch):
    assert client.get('/restock-planner/export?days=8').status_code==400
    assert client.get('/restock-planner/export?status=undefined').status_code==400
    assert client.get('/restock-planner/export?format=pdf').status_code==400
    client.cookies.clear()
    assert client.get('/restock-planner',follow_redirects=False).status_code==303
    assert client.get('/restock-planner/export',follow_redirects=False).status_code==303
    with GuestClient(app) as guest:
        assert guest.post('/restock-planner/1/settings',data={'lead_time_days':'1'},follow_redirects=False).status_code==401


def test_csv_excel_formula_escape(client):
    make_product('ROP-CSV')
    with connection() as db:
        db.execute("UPDATE products SET name='=HYPERLINK(1)' WHERE sku='ROP-CSV'")
        db.commit()
    result=restock_recommendations(q='ROP-CSV')
    assert "'=HYPERLINK" in restock_csv(result).decode('utf-8-sig')
    wb=load_workbook(BytesIO(restock_xlsx(result)))
    assert wb['Rekomendasi']['B2'].value.startswith("'=HYPERLINK")
    assert wb['Rekomendasi']['B2'].data_type != 'f'


def test_csrf_guard_blocks_invalid_token(client):
    pid=make_product()
    from fastapi.testclient import TestClient as PlainClient
    # Bypass the test harness' automatic CSRF insertion deliberately.
    response=PlainClient.post(client, f'/restock-planner/{pid}/settings',
        data={'lead_time_days':'5','safety_stock_units':'3','review_days':'7','csrf_token':'invalid'},
        follow_redirects=False)
    assert response.status_code==403
    with connection() as db:
        assert db.execute('SELECT COUNT(*) FROM reorder_settings').fetchone()[0]==0
