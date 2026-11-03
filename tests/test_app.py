from io import BytesIO

import pytest
from tests.client import TestClient

from app.database import connection
from app.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("USAHAINSIGHT_DB", str(tmp_path / "test.db"))
    with TestClient(app) as test_client:
        yield test_client


def test_demo_dashboard_and_pages(client):
    for url in ("/", "/inventory", "/imports", "/transactions", "/reports", "/health"):
        r = client.get(url)
        assert r.status_code == 200, (url, r.text[:500])
    assert "Dashboard Bisnis" in client.get("/").text
    assert "DATA DEMO SINTETIS" in client.get("/").text
    with connection() as db:
        assert db.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 24
        assert db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] > 100
        assert db.execute("SELECT MIN(current_stock) FROM product_inventory").fetchone()[0] >= 0


def test_duplicate_invoice_import_is_atomic(client):
    before = client.get("/reports/export?format=csv").content
    sample = client.get("/samples/sales").content
    response = client.post("/imports/sales", files={"file": ("sales.csv", sample, "text/csv")})
    assert response.status_code == 422
    assert "sudah pernah diimpor" in response.text
    assert client.get("/reports/export?format=csv").content == before


def test_invalid_product_rows_roll_back_everything(client):
    bad = b"sku,name,category,unit_price,min_stock,initial_stock\nZZ-1,Produk Baru,Contoh,12000,3,20\nZZ-2,Rusak,Contoh,-5,3,20\n"
    response = client.post("/imports/products", files={"file": ("products.csv", bad, "text/csv")})
    assert response.status_code == 422
    with connection() as db:
        assert db.execute("SELECT COUNT(*) FROM products WHERE sku='ZZ-1'").fetchone()[0] == 0


def test_product_upsert_does_not_repeat_initial_stock(client):
    csv_bytes = b"sku,name,category,unit_price,min_stock,initial_stock\nZZ-1,Produk Baru,Contoh,12000,3,20\n"
    first = client.post("/imports/products", files={"file": ("p.csv", csv_bytes, "text/csv")}, follow_redirects=False)
    second = client.post("/imports/products", files={"file": ("p.csv", csv_bytes, "text/csv")}, follow_redirects=False)
    assert first.status_code == second.status_code == 303
    with connection() as db:
        r = db.execute("SELECT current_stock FROM product_inventory WHERE sku='ZZ-1'").fetchone()
        assert r["current_stock"] == 20


def test_valid_sale_reduces_stock_and_preserves_sale_price(client):
    with connection() as db:
        old_stock = db.execute("SELECT current_stock FROM product_inventory WHERE sku='BRG-001'").fetchone()[0]
    invoice = b"transaction_id,date,sku,quantity,unit_price\nEXTRA-100,2026-10-01,BRG-001,2,99000\n"
    response = client.post("/imports/sales", files={"file": ("s.csv", invoice, "text/csv")}, follow_redirects=False)
    assert response.status_code == 303
    with connection() as db:
        new_stock = db.execute("SELECT current_stock FROM product_inventory WHERE sku='BRG-001'").fetchone()[0]
        row = db.execute("SELECT line_total FROM transaction_items i JOIN transactions t ON t.id=i.transaction_id WHERE t.invoice_no='EXTRA-100'").fetchone()
        assert new_stock == old_stock - 2
        assert row["line_total"] == 198000


def test_restock_increases_stock(client):
    with connection() as db:
        row = db.execute("SELECT id,current_stock FROM product_inventory WHERE sku='BRG-019'").fetchone()
        product_id, old_stock = row["id"], row["current_stock"]
    response = client.post(f"/inventory/{product_id}/restock", data={"quantity": "32", "note": "Test restock"}, follow_redirects=False)
    assert response.status_code == 303
    with connection() as db:
        updated = db.execute("SELECT current_stock FROM product_inventory WHERE id=?", (product_id,)).fetchone()[0]
        assert updated == old_stock + 32


def test_exports(client):
    csv_response = client.get("/reports/export?format=csv")
    assert csv_response.status_code == 200
    assert csv_response.content.startswith(b"\xef\xbb\xbf")
    assert b"transaction_id" in csv_response.content
    excel_response = client.get("/reports/export?format=xlsx")
    assert excel_response.status_code == 200
    assert excel_response.content[:2] == b"PK"
    assert len(excel_response.content) > 4000


def test_date_validation(client):
    response = client.get("/reports/export?format=csv&from=2026-11-01&to=2026-01-01")
    assert response.status_code == 400
