"""Manual sales: validated, ledger-backed, idempotent, atomic SQLite transactions.

Server prices are always read from current product records at commit time.
Every sale writes one transaction, its items and matching negative stock movements.
"""
from datetime import date
from hashlib import sha256
import json
import re
import sqlite3
import uuid

from app.database import connection
from app.services.audit import write_audit
from app.services.importers import DataValidationError

MAX_LINES = 20
MAX_TOTAL = 9_000_000_000_000_000


def sale_product_options():
    """Products selectable on the manual sale form, including stock availability."""
    with connection() as db:
        return [dict(r) for r in db.execute("""
            SELECT p.id, p.sku, p.name, p.unit_price, inv.current_stock
            FROM products p JOIN product_inventory inv ON inv.id=p.id
            WHERE p.is_active=1 ORDER BY p.name COLLATE NOCASE, p.sku
        """)]


def _parse_sale(invoice_no, sold_at, product_ids, quantities, request_key):
    errors = []
    invoice = str(invoice_no or "").strip().upper()
    if invoice and not re.fullmatch(r"[A-Z0-9._-]{3,60}", invoice):
        errors.append("Nomor invoice harus 3–60 karakter huruf, angka, titik, - atau _.")
    sold = str(sold_at or "").strip()
    try:
        parsed_date = date.fromisoformat(sold)
        if parsed_date.isoformat() != sold:
            raise ValueError
        if parsed_date > date.today():
            errors.append("Tanggal transaksi tidak boleh di masa depan.")
    except ValueError:
        errors.append("Tanggal transaksi harus dalam format YYYY-MM-DD.")
    try:
        key = str(uuid.UUID(str(request_key)))
    except (ValueError, TypeError, AttributeError):
        errors.append("Sesi formulir tidak valid. Muat ulang halaman transaksi dan coba kembali.")
        key = ""
    if len(product_ids) != len(quantities) or not 1 <= len(product_ids) <= MAX_LINES:
        errors.append(f"Isi 1 sampai {MAX_LINES} baris produk, masing-masing dengan jumlahnya.")
    parsed = []
    seen = set()
    for i, (raw_id, raw_qty) in enumerate(zip(product_ids, quantities), start=1):
        pid, qty = str(raw_id).strip(), str(raw_qty).strip()
        if len(pid) > 10 or not re.fullmatch(r"[1-9][0-9]*", pid) or int(pid) > 1_000_000_000:
            errors.append(f"Baris {i}: pilih produk yang valid.")
            continue
        if len(qty) > 7 or not re.fullmatch(r"[1-9][0-9]*", qty) or int(qty) > 1_000_000:
            errors.append(f"Baris {i}: kuantitas harus 1 sampai 1.000.000 unit.")
            continue
        product_id = int(pid)
        if product_id in seen:
            errors.append(f"Baris {i}: produk yang sama tidak boleh muncul dua kali.")
        seen.add(product_id)
        parsed.append((product_id, int(qty)))
    if errors:
        raise DataValidationError(errors)
    return invoice, sold, parsed, key


def _next_invoice(db, sold_at):
    """Assign a human-readable invoice without breaking preexisting imported invoices."""
    prefix = "UI-" + sold_at.replace("-", "") + "-"
    # Within a BEGIN IMMEDIATE transaction, concurrent sale writers serialize.
    nums = [int(r[0][len(prefix):]) for r in db.execute(
        "SELECT invoice_no FROM transactions WHERE invoice_no LIKE ?", (prefix + "%",)
    ) if re.fullmatch(r"[0-9]{1,9}", r[0][len(prefix):])]
    candidate = max(nums, default=0) + 1
    while candidate < 1_000_000_000:
        invoice = prefix + f"{candidate:04d}"
        if not db.execute("SELECT 1 FROM transactions WHERE invoice_no=?", (invoice,)).fetchone():
            return invoice
        candidate += 1
    raise DataValidationError(["Nomor invoice otomatis habis untuk tanggal tersebut."])


def create_sale(invoice_no, sold_at, product_ids, quantities, request_key, *, actor_id=None):
    """Create a sale with durable one-request-one-invoice guarantee.

    Replaying the exact same request key and payload returns the same invoice;
    reusing a key for different content is rejected.
    """
    invoice, sold, rows, key = _parse_sale(invoice_no, sold_at, product_ids, quantities, request_key)
    payload = json.dumps([invoice, sold, rows], separators=(",", ":"))
    digest = sha256(payload.encode("utf-8")).hexdigest()
    with connection() as db:
        try:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT transaction_id,payload_hash FROM manual_sale_requests WHERE request_key=?", (key,)).fetchone()
            if old:
                if old["payload_hash"] != digest:
                    raise DataValidationError(["Formulir sudah dipakai untuk transaksi yang berbeda. Muat halaman Buat Transaksi baru."])
                previous = db.execute("SELECT invoice_no FROM transactions WHERE id=?", (old["transaction_id"],)).fetchone()
                db.commit()
                return {"transaction_id": old["transaction_id"], "invoice": previous["invoice_no"], "replayed": True}

            if not invoice:
                invoice = _next_invoice(db, sold)
            elif db.execute("SELECT 1 FROM transactions WHERE invoice_no=?", (invoice,)).fetchone():
                raise DataValidationError([f"Nomor invoice {invoice} sudah digunakan. Gunakan nomor lain."])

            lines, total = [], 0
            for product_id, qty in rows:
                product = db.execute("""
                    SELECT p.id,p.sku,p.name,p.unit_price,p.is_active, inv.current_stock
                    FROM products p JOIN product_inventory inv ON inv.id=p.id WHERE p.id=?
                """, (product_id,)).fetchone()
                if not product or not product["is_active"]:
                    raise DataValidationError([f"Produk pada baris ID {product_id} tidak tersedia atau sudah diarsipkan."])
                if product["current_stock"] < qty:
                    raise DataValidationError([f"Stok {product['sku']} tidak cukup: tersedia {product['current_stock']} unit, diminta {qty} unit."])
                line_total = qty * product["unit_price"]
                if line_total > MAX_TOTAL or total + line_total > MAX_TOTAL:
                    raise DataValidationError(["Nilai total transaksi melebihi batas yang diizinkan."])
                total += line_total
                lines.append((product_id, qty, product["unit_price"], line_total))

            transaction_id = db.execute("INSERT INTO transactions(invoice_no,sold_at) VALUES (?,?)", (invoice,sold)).lastrowid
            for product_id, qty, price, line_total in lines:
                db.execute("""INSERT INTO transaction_items(transaction_id, product_id, quantity, unit_price, line_total)
                              VALUES (?,?,?,?,?)""", (transaction_id,product_id,qty,price,line_total))
                db.execute("""INSERT INTO stock_movements(product_id,transaction_id,movement_type,delta,note)
                              VALUES (?,?,'sale',?,?)""", (product_id,transaction_id,-qty,f"Penjualan manual {invoice}"))
            db.execute("INSERT INTO manual_sale_requests(request_key,payload_hash,transaction_id) VALUES (?,?,?)",
                       (key,digest,transaction_id))
            write_audit(db, actor_id, 'sale.created', 'transaction', transaction_id,
                        after={'invoice':invoice,'sold_at':sold, 'line_count':len(lines),
                               'total':total, 'units':sum(line[1] for line in lines)},
                        summary=f"Invoice {invoice} dibuat · total Rp{total:,}")
            db.commit()
            return {"transaction_id": transaction_id, "invoice": invoice, "replayed": False}
        except sqlite3.IntegrityError as exc:
            db.rollback()
            raise DataValidationError(["Nomor invoice sudah digunakan atau data transaksi tidak valid."]) from exc
        except Exception:
            db.rollback()
            raise


def transaction_detail(transaction_id):
    with connection() as db:
        header = db.execute("""SELECT t.id,t.invoice_no,t.sold_at, t.created_at,
                            COALESCE(SUM(i.line_total),0) AS total, COALESCE(SUM(i.quantity),0) AS units
                            FROM transactions t LEFT JOIN transaction_items i ON i.transaction_id=t.id
                            WHERE t.id=? GROUP BY t.id""", (transaction_id,)).fetchone()
        if not header:
            return None
        items = [dict(r) for r in db.execute("""SELECT p.sku, p.name, i.quantity,i.unit_price,i.line_total
             FROM transaction_items i JOIN products p ON p.id=i.product_id
             WHERE i.transaction_id=? ORDER BY i.id""", (transaction_id,))]
    return {"header": dict(header), "items": items}
