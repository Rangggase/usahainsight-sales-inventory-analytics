"""Integration & migration tests for v1.1 product management."""
import sqlite3

import pytest
from tests.client import TestClient

from app.database import connection
from app.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("USAHAINSIGHT_DB", str(tmp_path / "test.db"))
    with TestClient(app) as c:
        yield c


def create(c, sku="NEW-001", qty="10", price="12000"):
    return c.post("/products/new", data={"sku": sku, "name": "Produk Tes", "category": "Uji",
              "unit_price": price, "min_stock": "3", "initial_stock": qty}, follow_redirects=False)


def test_products_page_and_create_updates_inventory(client):
    assert client.get("/products").status_code == 200
    assert client.get("/products/new").status_code == 200
    assert create(client).status_code == 303
    with connection() as db:
        row = db.execute("SELECT * FROM product_inventory WHERE sku='NEW-001'").fetchone()
        assert row["current_stock"] == 10
        assert row["unit_price"] == 12000
        count = db.execute("SELECT COUNT(*) FROM stock_movements WHERE product_id=?", (row["id"],)).fetchone()[0]
        assert count == 1
    assert "NEW-001" in client.get("/inventory").text


def test_duplicate_sku_rejected_atomic(client):
    assert create(client).status_code == 303
    rejected = create(client, sku="new-001", qty="999")
    assert rejected.status_code == 422
    assert "sudah terdaftar" in rejected.text
    with connection() as db:
        assert db.execute("SELECT COUNT(*) FROM products WHERE sku='NEW-001'").fetchone()[0] == 1
        assert db.execute("SELECT current_stock FROM product_inventory WHERE sku='NEW-001'").fetchone()[0] == 10


@pytest.mark.parametrize("key,bad_value",[("unit_price","-1"),("unit_price","1.2"),("min_stock","abc"),("initial_stock","-4"),("sku","***"),("name","")])
def test_invalid_product_rejected(client,key,bad_value):
    fields = {"sku": "NEW-002", "name": "Beras Uji", "category": "Sembako",
              "unit_price": "15000", "min_stock": "2", "initial_stock": "4"}
    fields[key] = bad_value
    r = client.post("/products/new", data=fields)
    assert r.status_code == 422
    with connection() as db:
        assert db.execute("SELECT COUNT(*) FROM products WHERE sku='NEW-002'").fetchone()[0] == 0


def test_edit_retains_stock_and_invoice_history(client):
    with connection() as db:
        original = db.execute("SELECT id, unit_price, current_stock FROM product_inventory WHERE sku='BRG-001'").fetchone()
        invoice_total = db.execute("""SELECT SUM(i.line_total) FROM transaction_items i WHERE i.product_id=?""", (original["id"],)).fetchone()[0]
    r = client.post(f"/products/{original['id']}/edit", data={"name": "Produk Diganti", "category": "Baru", "unit_price": "77777", "min_stock": "8"}, follow_redirects=False)
    assert r.status_code == 303
    with connection() as db:
        p = db.execute("SELECT * FROM products WHERE id=?",(original["id"],)).fetchone()
        inv = db.execute("SELECT current_stock FROM product_inventory WHERE id=?", (original["id"],)).fetchone()
        after_total = db.execute("SELECT SUM(i.line_total) FROM transaction_items i WHERE i.product_id=?", (original["id"],)).fetchone()[0]
        assert p["sku"] == "BRG-001"
        assert p["name"] == "Produk Diganti"
        assert p["unit_price"] == 77777
        assert inv["current_stock"] == original["current_stock"]
        assert after_total == invoice_total


def test_archive_requires_zero_stock_and_can_restore(client):
    assert create(client).status_code == 303
    with connection() as db:
        row = db.execute("SELECT id FROM products WHERE sku='NEW-001'").fetchone()
        pid = row["id"]
    denied = client.post(f"/products/{pid}/archive", follow_redirects=False)
    assert denied.status_code == 303 and "error=" in denied.headers["location"]
    with connection() as db:
        assert db.execute("SELECT is_active FROM products WHERE id=?",(pid,)).fetchone()[0] == 1
        db.execute("INSERT INTO stock_movements(product_id, movement_type, delta, note) VALUES (?, 'adjustment', -10, 'Fixture: write-off')", (pid,))
        db.commit()
    ok = client.post(f"/products/{pid}/archive", follow_redirects=False)
    assert ok.status_code == 303 and "success=" in ok.headers["location"]
    assert "NEW-001" not in client.get("/inventory").text
    assert "NEW-001" in client.get("/products?status=archived").text
    assert client.post(f"/inventory/{pid}/restock", data={"quantity": "2"}, follow_redirects=False).status_code == 303
    with connection() as db:
        assert db.execute("SELECT current_stock FROM product_inventory WHERE id=?", (pid,)).fetchone()[0] == 0
    assert client.post(f"/products/{pid}/restore", follow_redirects=False).status_code == 303
    assert "NEW-001" in client.get("/inventory").text


def test_csv_cannot_reactivate_archived_product(client):
    assert create(client, sku="NEW-003",qty="0").status_code == 303
    with connection() as db:
        pid = db.execute("SELECT id FROM products WHERE sku='NEW-003'").fetchone()[0]
    client.post(f"/products/{pid}/archive",follow_redirects=False)
    source = b"sku,name,category,unit_price,min_stock,initial_stock\nNEW-003,Edited,Example,10,1,10\n"
    response = client.post("/imports/products",files={"file": ("p.csv",source,"text/csv")})
    assert response.status_code == 422
    with connection() as db:
        r = db.execute("SELECT is_active,name FROM products WHERE id=?",(pid,)).fetchone()
        assert r["is_active"] == 0 and r["name"] == "Produk Tes"


def test_existing_v1_0_database_auto_migrates(tmp_path,monkeypatch):
    from app.database import ROOT
    old_db = tmp_path / "existing_v1.db"
    conn = sqlite3.connect(old_db)
    schema = (ROOT / "app" / "schema.sql").read_text(encoding="utf-8")
    conn.executescript(schema)
    conn.execute("INSERT INTO products(sku,name,category,unit_price,min_stock) VALUES('PRE-001','Sebelumnya','Old',6000,2)")
    conn.commit()
    conn.close()
    monkeypatch.setenv("USAHAINSIGHT_DB", str(old_db))
    with TestClient(app) as c:
        assert c.get("/products").status_code == 200
        assert "PRE-001" in c.get("/products").text
    with connection() as db:
        columns = {x["name"] for x in db.execute("PRAGMA table_info(products)")}
        assert "is_active" in columns
        assert db.execute("SELECT is_active FROM products WHERE sku='PRE-001'").fetchone()[0] == 1
    # Migration is idempotent on second app startup
    with TestClient(app) as c:
        assert c.get("/products").status_code == 200


def test_archived_sku_sale_rejected_without_changing_invoice_count(client):
    from datetime import date
    assert create(client,sku="NEW-004",qty="0").status_code == 303
    with connection() as db:
        pid = db.execute("SELECT id FROM products WHERE sku='NEW-004'").fetchone()[0]
        before = db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    assert client.post(f"/products/{pid}/archive",follow_redirects=False).status_code == 303
    rows = ("transaction_id,date,sku,quantity,unit_price\n"
            f"TEST-ARCHIVED-001,{date.today().isoformat()},NEW-004,1,2000\n").encode()
    r = client.post("/imports/sales",files={"file": ("s.csv",rows,"text/csv")})
    assert r.status_code == 422
    with connection() as db:
        assert db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == before
        assert db.execute("SELECT current_stock FROM product_inventory WHERE id=?",(pid,)).fetchone()[0] == 0


def test_no_history_loss_when_archiving_zero_stock_product_with_sales(client):
    from datetime import date
    assert create(client,sku="NEW-005",qty="1").status_code == 303
    rows = ("transaction_id,date,sku,quantity,unit_price\n"
            f"TEST-ARCHIVED-002,{date.today().isoformat()},NEW-005,1,2000\n").encode()
    assert client.post("/imports/sales",files={"file": ("s.csv",rows,"text/csv")},follow_redirects=False).status_code == 303
    with connection() as db:
        pid = db.execute("SELECT id FROM products WHERE sku='NEW-005'").fetchone()[0]
        revenue_before = db.execute("SELECT SUM(line_total) FROM transaction_items WHERE product_id=?",(pid,)).fetchone()[0]
    assert client.post(f"/products/{pid}/archive",follow_redirects=False).status_code == 303
    assert "NEW-005" not in client.get("/inventory").text
    with connection() as db:
        assert db.execute("SELECT SUM(line_total) FROM transaction_items WHERE product_id=?",(pid,)).fetchone()[0] == revenue_before
    assert b"TEST-ARCHIVED-002" in client.get("/reports/export?format=csv").content
