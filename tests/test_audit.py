"""Audit trail security, lifecycle, migration and atomicity coverage."""
from datetime import date
import json
import sqlite3
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient as GuestClient
from tests.client import TestClient
from app.database import connection, init_db
from app.main import app
from app.services.audit import list_events, write_audit
from app.services.importers import DataValidationError


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('USAHAINSIGHT_DB', str(tmp_path/'audit.db'))
    with TestClient(app) as c:
        yield c


def event_rows():
    with connection() as db:
        return [dict(x) for x in db.execute('SELECT * FROM audit_events ORDER BY id')]


def create(c, *, sku='AUD-001', stock='10', name='Uji Audit', price='15000'):
    return c.post('/products/new', data={'sku':sku,'name':name,'category':'Pengujian',
       'unit_price':price,'min_stock':'3','initial_stock':stock},follow_redirects=False)


def test_migration_create_table_and_empty_history(client):
    with connection() as db:
        assert db.execute("SELECT name FROM sqlite_master WHERE name='audit_events'").fetchone()
        assert db.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0] == 0
    assert 'Belum ada aktivitas' in client.get('/audit').text
    init_db()
    with connection() as db:
        assert db.execute('SELECT COUNT(*) FROM audit_events').fetchone()[0] == 0


def test_audit_page_requires_login(tmp_path, monkeypatch):
    monkeypatch.setenv('USAHAINSIGHT_DB', str(tmp_path/'guest.db'))
    with GuestClient(app) as guest:
        r=guest.get('/audit',follow_redirects=False)
        assert r.status_code == 303 and r.headers['location']=='/login'


def test_create_edit_capture_identity_and_before_after(client):
    assert create(client).status_code==303
    with connection() as db:
        product_id=db.execute("SELECT id FROM products WHERE sku='AUD-001'").fetchone()[0]
    assert client.post(f'/products/{product_id}/edit',data={
        'name':'Produk Audit Baru','category':'Pengujian','unit_price':'25000','min_stock':'4'},
        follow_redirects=False).status_code==303
    events=event_rows()
    assert [e['action'] for e in events] == ['product.created','product.updated']
    assert all(e['actor_username']=='admin' and e['actor_user_id'] for e in events)
    before=json.loads(events[-1]['before_json'])
    after=json.loads(events[-1]['after_json'])
    assert before['unit_price']==15000 and after['unit_price']==25000
    assert before['name']=='Uji Audit' and after['name']=='Produk Audit Baru'
    assert 'Produk Audit Baru' not in events[-1]['before_json']
    assert '25000' in client.get('/audit?action=product.updated').text


def test_duplicate_product_fails_without_audit(client):
    create(client)
    assert create(client).status_code==422
    assert [e['action'] for e in event_rows()] == ['product.created']


def test_archive_restock_restore_and_failed_archive(client):
    create(client,stock='0')
    with connection() as db:
        pid=db.execute("SELECT id FROM products WHERE sku='AUD-001'").fetchone()[0]
    assert client.post(f'/products/{pid}/archive',follow_redirects=False).status_code==303
    assert client.post(f'/products/{pid}/restore',follow_redirects=False).status_code==303
    assert client.post(f'/inventory/{pid}/restock',data={'quantity':'5','note':'Terima barang'},follow_redirects=False).status_code==303
    assert client.post(f'/products/{pid}/archive',follow_redirects=False).status_code==303
    events=event_rows()
    assert [r['action'] for r in events]==[
        'product.created','product.archived','product.restored','stock.restocked']
    assert json.loads(events[-1]['before_json'])['stock']==0
    assert json.loads(events[-1]['after_json'])['stock']==5
    assert 'product.archived' in client.get('/audit').text


def test_sale_records_once_and_no_event_when_insufficient_stock(client):
    create(client,stock='10')
    with connection() as db:
        pid=db.execute("SELECT id FROM products WHERE sku='AUD-001'").fetchone()[0]
    key=str(uuid4())
    sale={'invoice_no':'AUD-INV-1','sold_at':date.today().isoformat(),
          'product_id':[str(pid)],'quantity':['2'],'request_key':key}
    first=client.post('/transactions/new',data=sale,follow_redirects=False)
    assert first.status_code==303
    second=client.post('/transactions/new',data=sale,follow_redirects=False)
    assert second.status_code==303
    assert client.post('/transactions/new',data={**sale,'request_key':str(uuid4()),
             'invoice_no':'AUD-INV-2','quantity':['99']}).status_code==422
    actions=[e['action'] for e in event_rows()]
    assert actions.count('sale.created')==1
    with connection() as db:
        assert db.execute("SELECT current_stock FROM product_inventory WHERE id=?",(pid,)).fetchone()[0]==8


def test_csv_upload_batch_audit_and_invalid_file_no_event(client):
    csv=b'sku,name,category,unit_price,min_stock,initial_stock\nCSV-A01,CSV Item,CAT,1000,2,5\n'
    ok=client.post('/imports/products',files={'file':('products.csv',csv,'text/csv')},follow_redirects=False)
    assert ok.status_code==303
    event=event_rows()[-1]
    assert event['action']=='products.imported'
    assert json.loads(event['after_json'])['created']==1
    bad=client.post('/imports/products',files={'file':('invalid.csv',b'badheader\nline\n','text/csv')})
    assert bad.status_code==422
    assert len(event_rows())==1
    sales=(f'transaction_id,date,sku,quantity,unit_price\nCSV-INV-1,{date.today().isoformat()},CSV-A01,2,1000\n').encode()
    assert client.post('/imports/sales',files={'file':('sales.csv',sales,'text/csv')},follow_redirects=False).status_code==303
    assert event_rows()[-1]['action']=='sales.imported'


def test_rollback_if_audit_insert_fails(client,monkeypatch):
    import app.services.products as products
    def explode(*args,**kwargs):
        raise RuntimeError('simulated log failure')
    monkeypatch.setattr(products,'write_audit',explode)
    with pytest.raises(RuntimeError,match='simulated log failure'):
        create(client)
    with connection() as db:
        assert db.execute("SELECT COUNT(*) FROM products WHERE sku='AUD-001'").fetchone()[0]==0
        assert db.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]==0


def test_append_only_rows(client):
    create(client)
    with connection() as db:
        with pytest.raises(sqlite3.IntegrityError,match='tidak boleh diubah'):
            db.execute("UPDATE audit_events SET summary='tampered' WHERE id=(SELECT MIN(id) FROM audit_events)")
        with pytest.raises(sqlite3.IntegrityError,match='tidak boleh dihapus'):
            db.execute('DELETE FROM audit_events')


def test_search_filter_and_pagination(client):
    create(client)
    with connection() as db:
        user_id=db.execute("SELECT id FROM auth_users WHERE username='admin'").fetchone()[0]
        db.execute('BEGIN IMMEDIATE')
        for n in range(30):
            write_audit(db,user_id,'product.updated','product',n,summary=f'Pencarian tes {n}')
        db.commit()
    record=list_events(page=1)
    assert record['total']==31 and record['pages']==2 and len(record['events'])==25
    assert len(list_events(page=2)['events'])==6
    assert list_events(query='Pencarian')['total']==30
    assert list_events(query='%')['total']==0 # literal wildcards
    assert list_events(action='stock.restocked')['total']==0
    assert client.get('/audit?p=2').status_code==200
    assert client.get('/audit?action=product.updated&q=Pencarian').status_code==200


def test_audit_does_not_store_auth_secrets(client):
    create(client)
    text=json.dumps(event_rows())
    assert 'Testing12345!' not in text
    assert 'password_hash' not in text
    assert 'csrf_token' not in text


def test_escaping_in_details(client):
    r=create(client,name='<script>alert("audit")</script>')
    assert r.status_code==303
    r=client.get('/audit')
    assert r.status_code==200
    assert '<script>alert("audit")</script>' not in r.text
    assert '\\u003cscript\\u003e' in r.text or '&lt;script&gt;' in r.text
