"""Populate the first-run local demo with labeled synthetic data."""
from pathlib import Path
from app.database import connection, database_path
from app.services.importers import import_products, import_sales

DATA_PATH = Path(__file__).resolve().parents[1] / "data"


def seed_when_empty():
    with connection() as db:
        count = db.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        sales = db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    # Respect a deliberate empty reset (even on subsequent restarts).
    if (database_path().parent / ".start_empty").exists():
        return False
    if count == 0 and sales == 0:
        import_products((DATA_PATH / "sample_products.csv").read_bytes())
        import_sales((DATA_PATH / "sample_sales.csv").read_bytes())
        return True
    return False
