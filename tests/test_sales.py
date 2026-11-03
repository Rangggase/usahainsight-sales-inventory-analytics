"""End-to-end regressions for v1.2: multi-line sales, atomicity, history, idempotence."""
from datetime import date, timedelta
from uuid import uuid4

import pytest
from tests.client import TestClient

from app.database import connection
from app.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("USAHAINSIGHT_DB", str(tmp_path / "sales_test.db"))
    with TestClient(app) as c:
        yield c


def fixture_product(sku, price, stock, *, active=1):
    with connection() as db:
        cur = db.execute("INSERT INTO products(sku,name,category,unit_price,min_stock,is_active) VALUES(?,?,?,?,?,?)",
                         (sku, f"Produk {sku}", "Uji", price, 2, active))
        pid = cur.lastrowid
        db.execute("INSERT INTO stock_movements(product_id,movement_type,delta,note) VALUES(?,'initial',?,'fixture')",
                   (pid, stock))
        db.commit()
    return pid


def sale_post(client, pids, quantities, **overrides):
    data = {
        "invoice_no": "", "sold_at": date.today().isoformat(),
        "product_id": [str(p) for p in pids],
        "quantity": [str(q) for q in quantities],
        "request_key": str(uuid4())
    }
    data.update(overrides)
    return client.post("/transactions/new", data=data, follow_redirects=False)


def state(*pids):
    with connection() as db:
        count = db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        movement_count = db.execute("SELECT COUNT(*) FROM stock_movements WHERE movement_type='sale'").fetchone()[0]
        stocks = [db.execute("SELECT current_stock FROM product_inventory WHERE id=?", (p,)).fetchone()[0] for p in pids]
    return count, movement_count, stocks


def test_new_sale_page_renders_and_migration_created(client):
    result = client.get("/transactions/new")
    assert result.status_code == 200
    assert 'name="request_key"' in result.text
    assert 'id="sale-line-template"' in result.text
    assert client.get("/transactions").status_code == 200
    with connection() as db:
        assert db.execute("SELECT name FROM sqlite_master WHERE name='manual_sale_requests'").fetchone()
    assert client.get("/health").json()["version"] == "1.4b.0"


def test_multi_item_sale_updates_all_stocks_history_reports(client):
    a, b = fixture_product("MAN-001", 15000, 10), fixture_product("MAN-002", 20000, 8)
    before = state(a, b)
    result = sale_post(client, [a, b], [2, 3])
    assert result.status_code == 303, result.text
    detail_url = result.headers["location"].split("?")[0]
    assert detail_url.startswith("/transactions/")
    assert state(a, b) == (before[0]+1, before[1]+2, [8,5])
    page = client.get(detail_url)
    assert page.status_code == 200
    assert "MAN-001" in page.text and "MAN-002" in page.text
    assert "90.000" in page.text
    detail_id = int(detail_url.rsplit("/",1)[-1])
    with connection() as db:
        items = db.execute("SELECT quantity,unit_price,line_total FROM transaction_items WHERE transaction_id=? ORDER BY id", (detail_id,)).fetchall()
        assert [tuple(x) for x in items] == [(2,15000,30000), (3,20000,60000)]
        assert db.execute("SELECT COUNT(*) FROM stock_movements WHERE transaction_id=?",(detail_id,)).fetchone()[0] == 2
    exported = client.get("/reports/export?format=csv").text
    with connection() as db:
        inv = db.execute("SELECT invoice_no FROM transactions WHERE id=?", (detail_id,)).fetchone()[0]
    assert inv in exported
    assert "MAN-001" in exported
    assert client.get("/reports/export?format=xlsx").status_code == 200
    assert client.get("/").status_code == 200
    assert client.get("/inventory").status_code == 200


def test_auto_invoice_generates_distinct_values(client):
    p = fixture_product("MAN-003", 4000, 20)
    a = sale_post(client, [p], [1])
    b = sale_post(client, [p], [1])
    assert a.status_code == 303 and b.status_code == 303
    with connection() as db:
        invoices = [r[0] for r in db.execute("SELECT invoice_no FROM transactions WHERE invoice_no LIKE 'UI-%' ORDER BY id")]
    assert len(invoices) == 2 and invoices[0] != invoices[1]
    assert invoices[0].startswith("UI-" + date.today().strftime("%Y%m%d") + "-")


def test_custom_invoice_duplicate_rolls_back(client):
    p = fixture_product("MAN-004", 5000, 5)
    assert sale_post(client, [p], [2], invoice_no="CUSTOM-001").status_code == 303
    before = state(p)
    r = sale_post(client, [p], [1], invoice_no="custom-001")
    assert r.status_code == 422
    assert "sudah digunakan" in r.text
    assert state(p) == before


def test_insufficient_second_product_keeps_first_unchanged(client):
    a,b = fixture_product("MAN-005", 2500, 5),fixture_product("MAN-006", 3000, 1)
    before = state(a,b)
    r = sale_post(client, [a,b], [2,2])
    assert r.status_code == 422 and "tidak cukup" in r.text
    assert state(a,b) == before


def test_duplicate_product_lines_rejected_atomically(client):
    p = fixture_product("MAN-007", 800, 7)
    before = state(p)
    r = sale_post(client, [p,p], [2,1])
    assert r.status_code == 422
    assert "yang sama" in r.text
    assert state(p) == before


def test_inactive_product_and_unknown_product_rejected(client):
    p = fixture_product("MAN-008", 1000, 0, active=0)
    before = state(p)
    assert sale_post(client,[p],[1]).status_code == 422
    assert sale_post(client,[99999999],[1]).status_code == 422
    assert state(p) == before


@pytest.mark.parametrize("quantity", ["0", "-1", "1.5", "abc", "1000001", "9"*100])
def test_invalid_quantities_rejected(client, quantity):
    p = fixture_product("MAN-009", 3000, 10)
    before=state(p)
    assert sale_post(client, [p], [quantity]).status_code == 422
    assert state(p) == before


def test_missing_lines_rejected(client):
    with connection() as db:
        before=db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    response = sale_post(client, [], [])
    assert response.status_code == 422
    with connection() as db:
        assert db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == before


def test_invalid_date_future_and_invoice_input(client):
    p=fixture_product("MAN-010", 3000, 10)
    before=state(p)
    assert sale_post(client,[p],[1],sold_at=(date.today()+timedelta(days=1)).isoformat()).status_code==422
    assert sale_post(client,[p],[1],sold_at="2026-13-01").status_code==422
    assert sale_post(client,[p],[1],invoice_no="<script>").status_code==422
    assert state(p)==before


def test_idempotency_same_payload_exactly_once(client):
    p=fixture_product("MAN-011", 3000, 10)
    key=str(uuid4())
    first=sale_post(client,[p],[2],request_key=key)
    assert first.status_code==303
    after=state(p)
    again=sale_post(client,[p],[2],request_key=key)
    assert again.status_code==303
    assert again.headers["location"].split("?")[0]==first.headers["location"].split("?")[0]
    assert state(p)==after
    assert "tidak dibuat dua kali" in client.get(again.headers["location"]).text


def test_idempotency_key_different_payload_rejected(client):
    p=fixture_product("MAN-012", 3000, 10)
    key=str(uuid4())
    assert sale_post(client,[p],[2],request_key=key).status_code==303
    after=state(p)
    assert sale_post(client,[p],[3],request_key=key).status_code==422
    assert state(p)==after


def test_price_snapshot_immutable_after_edit(client):
    p=fixture_product("MAN-013", 11111, 10)
    response=sale_post(client,[p],[2])
    assert response.status_code==303
    detail_url=response.headers["location"].split("?")[0]
    with connection() as db:
        db.execute("UPDATE products SET unit_price=99999 WHERE id=?", (p,))
        db.commit()
    with connection() as db:
        detail=db.execute("SELECT unit_price,line_total FROM transaction_items WHERE product_id=? ORDER BY id DESC LIMIT 1",(p,)).fetchone()
        assert tuple(detail)==(11111,22222)
    assert "22.222" in client.get(detail_url).text


def test_old_imported_sale_detail_and_404(client):
    with connection() as db:
        old_id=db.execute("SELECT id FROM transactions ORDER BY id LIMIT 1").fetchone()[0]
    assert client.get(f"/transactions/{old_id}").status_code==200
    assert client.get("/transactions/99999999").status_code==404


def test_csv_conflict_with_form_sale_number(client):
    p=fixture_product("MAN-014", 10000, 10)
    assert sale_post(client,[p],[1],invoice_no="CSV-CONFLICT-01").status_code==303
    before=state(p)
    content=("transaction_id,date,sku,quantity,unit_price\n"+f"CSV-CONFLICT-01,{date.today().isoformat()},MAN-014,1,10000\n").encode()
    result=client.post("/imports/sales",files={"file": ("sample.csv",content,"text/csv")})
    assert result.status_code==422
    assert state(p)==before


def test_total_limit_rejected(client):
    pids=[fixture_product(f"BIG-{i:03d}", 1000000000, 1000000) for i in range(10)]
    before=state(*pids)
    r=sale_post(client,pids,[1000000]*10)
    assert r.status_code==422
    assert state(*pids)==before


def test_concurrent_sales_cannot_oversell(client):
    from concurrent.futures import ThreadPoolExecutor
    from app.services.sales import create_sale
    from app.services.importers import DataValidationError
    p = fixture_product("MAN-CONCUR", 1500, 1)
    before=state(p)
    def attempt(n):
        try:
            return create_sale(f"RACE-{n}",date.today().isoformat(),[str(p)],["1"],str(uuid4()))
        except DataValidationError as exc:
            return exc
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(attempt,(1,2)))
    assert sum(isinstance(x,dict) for x in results)==1
    assert sum(isinstance(x,DataValidationError) for x in results)==1
    assert state(p)==(before[0]+1,before[1]+1,[0])


def test_empty_database_form_has_no_products_and_cannot_sell(client):
    with connection() as db:
        db.execute("DELETE FROM stock_movements")
        db.execute("DELETE FROM transaction_items")
        db.execute("DELETE FROM transactions")
        db.execute("DELETE FROM products")
        db.commit()
    response=client.get('/transactions/new')
    assert response.status_code==200
    assert 'Tidak ada produk aktif' in response.text
    assert 'id="sale-submit"' in response.text and 'disabled' in response.text
    assert sale_post(client,["99"],[1]).status_code==422


def test_v1_1_database_upgrades_without_losing_existing_records(tmp_path, monkeypatch):
    import sqlite3
    from app.database import ROOT
    legacy = tmp_path / "legacy_v11.db"
    old_schema = (ROOT / "app" / "schema.sql").read_text(encoding="utf-8").split("-- V1.2 idempotency")[0]
    db = sqlite3.connect(legacy)
    db.executescript(old_schema)
    db.execute("ALTER TABLE products ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0,1))")
    db.execute("INSERT INTO products (sku,name,category,unit_price,min_stock) VALUES ('LEGACY-01','Lama','Test',15000,2)")
    pid = db.execute("SELECT id FROM products WHERE sku='LEGACY-01'").fetchone()[0]
    db.execute("INSERT INTO stock_movements(product_id,movement_type,delta) VALUES(?,'initial',10)",(pid,))
    db.execute("INSERT INTO transactions(invoice_no,sold_at) VALUES('LEGACY-INVOICE',?)",(date.today().isoformat(),))
    db.commit()
    db.close()
    monkeypatch.setenv("USAHAINSIGHT_DB", str(legacy))
    with TestClient(app) as c:
        assert c.get('/transactions/new').status_code == 200
        assert c.get('/transactions').status_code == 200
        assert c.get('/products').status_code == 200
    with connection() as newdb:
        assert newdb.execute("SELECT COUNT(*) FROM transactions WHERE invoice_no='LEGACY-INVOICE'").fetchone()[0] == 1
        assert newdb.execute("SELECT current_stock FROM product_inventory WHERE sku='LEGACY-01'").fetchone()[0] == 10
        assert newdb.execute("SELECT 1 FROM sqlite_master WHERE name='manual_sale_requests'").fetchone()
