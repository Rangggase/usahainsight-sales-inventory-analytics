"""Regenerate synthetic sample CSVs with transaction dates relative to today.
Run before resetting an empty local database if you want freshly dated demo data.
"""
from pathlib import Path
from datetime import date, timedelta
import csv
import random

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data"
OUT.mkdir(exist_ok=True)
PRODUCTS = [
    ("BRG-001", "Beras Premium 5 kg", "Sembako", 77000, 18, 230),
    ("BRG-002", "Minyak Goreng 2 L", "Sembako", 38000, 18, 230),
    ("BRG-003", "Gula Pasir 1 kg", "Sembako", 18000, 16, 210),
    ("BRG-004", "Tepung Terigu 1 kg", "Sembako", 14000, 15, 150),
    ("BRG-005", "Mie Instan Goreng", "Makanan", 3500, 25, 310),
    ("BRG-006", "Biskuit Cokelat", "Makanan", 12500, 10, 135),
    ("BRG-007", "Roti Tawar", "Makanan", 17000, 10, 130),
    ("BRG-008", "Kopi Sachet", "Minuman", 2500, 20, 240),
    ("BRG-009", "Teh Celup 25 pcs", "Minuman", 11000, 15, 130),
    ("BRG-010", "Air Mineral 600 ml", "Minuman", 4000, 20, 240),
    ("BRG-011", "Susu UHT 1 L", "Minuman", 19500, 10, 140),
    ("BRG-012", "Sabun Mandi", "Perawatan", 6500, 15, 115),
    ("BRG-013", "Pasta Gigi", "Perawatan", 15000, 12, 115),
    ("BRG-014", "Sampo Sachet", "Perawatan", 2000, 15, 170),
    ("BRG-015", "Deterjen Bubuk 800 g", "Rumah Tangga", 21500, 12, 115),
    ("BRG-016", "Sabun Cuci Piring", "Rumah Tangga", 14500, 12, 110),
    ("BRG-017", "Tisu Wajah", "Rumah Tangga", 12500, 8, 90),
    ("BRG-018", "Baterai AA 2 pcs", "Rumah Tangga", 12000, 8, 90),
    ("BRG-019", "Kecap Manis", "Sembako", 12500, 15, 11),
    ("BRG-020", "Saus Sambal", "Sembako", 11500, 15, 12),
    ("BRG-021", "Sereal Jagung", "Makanan", 33000, 10, 8),
    ("BRG-022", "Minuman Isotonik", "Minuman", 9000, 12, 9),
    ("BRG-023", "Pembersih Lantai", "Rumah Tangga", 16000, 10, 8),
    ("BRG-024", "Permen Mint", "Makanan", 6500, 7, 55),
]


def main():
    rng = random.Random(2026)
    with (OUT / "sample_products.csv").open("w", newline="", encoding="utf-8") as out:
        writer = csv.writer(out)
        writer.writerow(["sku", "name", "category", "unit_price", "min_stock", "initial_stock"])
        writer.writerows(PRODUCTS)
    remain = {p[0]: p[5] for p in PRODUCTS}
    rows = []
    choices = list(range(len(PRODUCTS)))
    weights = [9, 9, 8, 6, 12, 4, 5, 8, 4, 8, 5, 5, 4, 7, 4, 4, 3, 2, .15, .15, .07, .1, .08, 2]
    dates = [date.today() - timedelta(days=rng.randint(0, 83)) for _ in range(180)]
    dates.sort()
    for invoice_num, sold in enumerate(dates, start=1):
        used = set()
        for _ in range(rng.randint(1, 3)):
            idx = rng.choices(choices, weights=weights, k=1)[0]
            product = PRODUCTS[idx]
            sku = product[0]
            if sku in used or remain[sku] < 1:
                continue
            used.add(sku)
            qty = min(rng.randint(1, 3), remain[sku])
            remain[sku] -= qty
            rows.append([f"INV-{invoice_num:04d}", sold.isoformat(), sku, qty, product[3]])
    with (OUT / "sample_sales.csv").open("w", newline="", encoding="utf-8") as out:
        writer = csv.writer(out)
        writer.writerow(["transaction_id", "date", "sku", "quantity", "unit_price"])
        writer.writerows(rows)
    print(f"Generated {len(PRODUCTS)} synthetic products and {len(rows)} sale lines, {len(dates)} invoices max.")


if __name__ == "__main__":
    main()
