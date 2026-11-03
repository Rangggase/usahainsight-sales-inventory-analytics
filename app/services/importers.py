"""Atomic CSV imports: reject malformed files, duplicate invoices and negative stock."""
import io
import csv
import re
from collections import defaultdict
from datetime import date

import pandas as pd

from app.database import connection
from app.services.audit import write_audit

PRODUCT_COLS = ("sku", "name", "category", "unit_price", "min_stock", "initial_stock")
SALES_COLS = ("transaction_id", "date", "sku", "quantity", "unit_price")
MAX_FILE_SIZE = 2 * 1024 * 1024
MAX_ROWS = 5000


class DataValidationError(ValueError):
    def __init__(self, errors):
        self.errors = errors[:15]
        super().__init__(self.errors[0] if self.errors else "Data tidak valid")


def load_csv(content: bytes, required: tuple):
    if not content:
        raise DataValidationError(["File CSV kosong."])
    if len(content) > MAX_FILE_SIZE:
        raise DataValidationError(["Ukuran CSV maksimal 2 MB."])
    try:
        raw_text = content.decode("utf-8-sig")
        header = next(csv.reader(io.StringIO(raw_text)))
        clean_headers = [name.strip().lower() for name in header]
        if len(set(clean_headers)) != len(clean_headers):
            raise DataValidationError(["Header CSV mengandung kolom duplikat."])
        df = pd.read_csv(io.BytesIO(content), dtype=str, keep_default_na=False, encoding="utf-8-sig")
    except (UnicodeDecodeError, StopIteration, csv.Error, pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
        raise DataValidationError(["CSV tidak dapat dibaca. Simpan file sebagai CSV UTF-8."]) from exc
    df.columns = [str(c).strip().lower() for c in df.columns]
    if len(set(df.columns)) != len(df.columns):
        raise DataValidationError(["Header CSV mengandung kolom duplikat."])
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise DataValidationError(["Kolom wajib tidak ditemukan: " + ", ".join(missing)])
    if df.empty:
        raise DataValidationError(["CSV harus memiliki minimal satu baris data."])
    if len(df) > MAX_ROWS:
        raise DataValidationError([f"Maksimal {MAX_ROWS} baris per impor."])
    return df


def natural_number(value, label, row, *, positive=False):
    value = str(value).strip()
    if not re.fullmatch(r"\d+", value):
        raise ValueError(f"Baris {row}: {label} harus bilangan bulat >= 0, tanpa pemisah ribuan.")
    val = int(value)
    if positive and not val:
        raise ValueError(f"Baris {row}: {label} harus lebih besar dari nol.")
    if val > 1_000_000_000:
        raise ValueError(f"Baris {row}: {label} melebihi batas nilai yang diizinkan.")
    return val


def parse_products(content):
    df = load_csv(content, PRODUCT_COLS)
    rows, errors, seen = [], [], set()
    for idx, record in enumerate(df.to_dict("records"), start=2):
        try:
            sku = str(record["sku"]).strip().upper()
            name = str(record["name"]).strip()
            category = str(record["category"]).strip()
            if not re.fullmatch(r"[A-Z0-9._-]{2,32}", sku):
                raise ValueError(f"Baris {idx}: SKU harus 2–32 karakter huruf, angka, titik, - atau _.")
            if not name or len(name) > 120 or not category or len(category) > 80:
                raise ValueError(f"Baris {idx}: nama/kategori wajib diisi (maksimal 120/80 karakter).")
            if sku in seen:
                raise ValueError(f"Baris {idx}: SKU {sku} duplikat dalam file.")
            seen.add(sku)
            rows.append({"sku": sku, "name": name, "category": category,
                         "unit_price": natural_number(record["unit_price"], "unit_price", idx),
                         "min_stock": natural_number(record["min_stock"], "min_stock", idx),
                         "initial_stock": natural_number(record["initial_stock"], "initial_stock", idx)})
        except ValueError as e:
            errors.append(str(e))
    if errors:
        raise DataValidationError(errors)
    return rows


def parse_sales(content):
    df = load_csv(content, SALES_COLS)
    rows, errors, seen, invoice_dates = [], [], set(), {}
    for idx, record in enumerate(df.to_dict("records"), start=2):
        try:
            invoice = str(record["transaction_id"]).strip()
            sku = str(record["sku"]).strip().upper()
            if not invoice or len(invoice) > 60:
                raise ValueError(f"Baris {idx}: transaction_id wajib diisi (maksimal 60 karakter).")
            if not re.fullmatch(r"[A-Z0-9._-]{2,32}", sku):
                raise ValueError(f"Baris {idx}: SKU tidak valid.")
            sold = str(record["date"]).strip()
            try:
                dt = date.fromisoformat(sold)
                if dt.isoformat() != sold:
                    raise ValueError
            except ValueError:
                raise ValueError(f"Baris {idx}: date harus YYYY-MM-DD.") from None
            if dt > date.today():
                raise ValueError(f"Baris {idx}: tanggal transaksi tidak boleh di masa depan.")
            if invoice in invoice_dates and invoice_dates[invoice] != sold:
                raise ValueError(f"Baris {idx}: tanggal untuk transaksi {invoice} tidak konsisten.")
            invoice_dates[invoice] = sold
            key = (invoice, sku)
            if key in seen:
                raise ValueError(f"Baris {idx}: pasangan transaction_id + SKU duplikat ({invoice}, {sku}).")
            seen.add(key)
            rows.append({"invoice": invoice, "sold_at": sold, "sku": sku,
                         "quantity": natural_number(record["quantity"], "quantity", idx, positive=True),
                         "unit_price": natural_number(record["unit_price"], "unit_price", idx)})
        except ValueError as e:
            errors.append(str(e))
    if errors:
        raise DataValidationError(errors)
    return sorted(rows, key=lambda r: (r["sold_at"], r["invoice"], r["sku"]))


def import_products(content, *, actor_id=None):
    rows = parse_products(content)
    created = updated = 0
    with connection() as db:
        try:
            db.execute("BEGIN IMMEDIATE")
            for r in rows:
                existing = db.execute("SELECT id,is_active FROM products WHERE sku=?", (r["sku"],)).fetchone()
                if existing:
                    if not existing["is_active"]:
                        raise DataValidationError([f"SKU {r['sku']} diarsipkan. Aktifkan kembali melalui menu Produk sebelum mengimpor."])
                    db.execute("""UPDATE products SET name=?, category=?, unit_price=?, min_stock=?,
                               updated_at=datetime('now') WHERE id=?""",
                               (r["name"], r["category"], r["unit_price"], r["min_stock"], existing["id"]))
                    updated += 1
                else:
                    cur = db.execute("INSERT INTO products (sku,name,category,unit_price,min_stock) VALUES (?,?,?,?,?)",
                                     (r["sku"], r["name"], r["category"], r["unit_price"], r["min_stock"]))
                    db.execute("INSERT INTO stock_movements (product_id,movement_type,delta,note) VALUES (?,?,?,?)",
                               (cur.lastrowid, "initial", r["initial_stock"], "Stok awal dari CSV produk"))
                    created += 1
            write_audit(db, actor_id, 'products.imported', 'import',
                after={'created': created, 'updated': updated, 'total': len(rows),
                       'sample_skus': [r['sku'] for r in rows[:25]]},
                summary=f"Impor produk: {created} baru, {updated} diperbarui ({len(rows)} baris)")
            db.commit()
        except Exception:
            db.rollback()
            raise
    return {"created": created, "updated": updated, "total": len(rows)}


def import_sales(content, *, actor_id=None):
    rows = parse_sales(content)
    with connection() as db:
        try:
            db.execute("BEGIN IMMEDIATE")
            products = {r["sku"]: (r["id"], r["current_stock"]) for r in db.execute("SELECT inv.id,inv.sku,inv.current_stock FROM product_inventory inv JOIN products p ON p.id=inv.id WHERE p.is_active=1")}
            invoice_rows = defaultdict(list)
            for r in rows:
                invoice_rows[r["invoice"]].append(r)
            invoice_ids = list(invoice_rows)
            existing = []
            # Parameter chunking avoids SQLite bind parameter limits on large uploads.
            for i in range(0, len(invoice_ids), 400):
                chunk = invoice_ids[i:i+400]
                placeholders = ",".join("?" for _ in chunk)
                existing.extend(x["invoice_no"] for x in db.execute(
                    f"SELECT invoice_no FROM transactions WHERE invoice_no IN ({placeholders})", chunk))
            errors = []
            if existing:
                errors.append("Transaksi sudah pernah diimpor: " + ", ".join(sorted(existing)[:8]) + ". Impor dibatalkan agar tidak menghitung ganda.")
            for r in rows:
                if r["sku"] not in products:
                    errors.append(f"SKU {r['sku']} belum terdaftar. Impor produk lebih dahulu.")
            if errors:
                raise DataValidationError(errors)
            remaining = {sku: qty for sku, (_, qty) in products.items()}
            for r in rows:
                remaining[r["sku"]] -= r["quantity"]
                if remaining[r["sku"]] < 0:
                    raise DataValidationError([f"Stok SKU {r['sku']} tidak cukup untuk transaksi {r['invoice']}. Sisa akan menjadi {remaining[r['sku']]}. Tambahkan stok dahulu."])
            created_invoice_ids = {}
            for invoice, invoice_items in invoice_rows.items():
                cur = db.execute("INSERT INTO transactions (invoice_no, sold_at) VALUES (?, ?)",
                                 (invoice, invoice_items[0]["sold_at"]))
                created_invoice_ids[invoice] = cur.lastrowid
            for r in rows:
                transaction_id = created_invoice_ids[r["invoice"]]
                product_id = products[r["sku"]][0]
                db.execute("INSERT INTO transaction_items (transaction_id, product_id, quantity, unit_price, line_total) VALUES (?,?,?,?,?)",
                           (transaction_id, product_id, r["quantity"], r["unit_price"], r["quantity"] * r["unit_price"]))
                db.execute("INSERT INTO stock_movements (product_id,transaction_id,movement_type,delta,note) VALUES (?,?,?,?,?)",
                           (product_id, transaction_id, "sale", -r["quantity"], f"Penjualan {r['invoice']}"))
            write_audit(db, actor_id, 'sales.imported', 'import',
                after={'transactions': len(created_invoice_ids), 'items': len(rows),
                       'sample_invoices': list(created_invoice_ids)[:25]},
                summary=f"Impor {len(created_invoice_ids)} invoice dan {len(rows)} rincian")
            db.commit()
        except Exception:
            db.rollback()
            raise
    return {"transactions": len(created_invoice_ids), "items": len(rows)}


def restock(product_id: int, quantity: int, note: str, *, actor_id=None):
    if not 1 <= quantity <= 1_000_000:
        raise DataValidationError(["Jumlah penambahan stok harus 1 sampai 1.000.000."])
    if len(note) > 200:
        raise DataValidationError(["Catatan maksimal 200 karakter."])
    with connection() as db:
        try:
            db.execute("BEGIN IMMEDIATE")
            product = db.execute("""SELECT p.id,p.sku,inv.current_stock FROM products p
                JOIN product_inventory inv ON inv.id=p.id
                WHERE p.id=? AND p.is_active=1""", (product_id,)).fetchone()
            if not product:
                raise DataValidationError(["Produk tidak ditemukan."])
            movement = db.execute("INSERT INTO stock_movements (product_id,movement_type,delta,note) VALUES (?,?,?,?)",
                       (product_id, "restock", quantity, note or "Penambahan stok manual"))
            write_audit(db, actor_id, 'stock.restocked', 'stock_movement', movement.lastrowid,
                        before={'product_id':product_id, 'stock':product['current_stock']},
                        after={'product_id':product_id, 'stock':product['current_stock'] + quantity,
                               'delta':quantity, 'note':note or 'Penambahan stok manual'},
                        summary=f"Restock {product['sku']}: +{quantity} unit")
            db.commit()
        except Exception:
            db.rollback()
            raise
