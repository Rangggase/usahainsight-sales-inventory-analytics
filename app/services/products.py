"""Product catalogue CRUD. Historical sales are retained; SKU cannot be changed."""
import re
import sqlite3

from app.database import connection
from app.services.audit import write_audit
from app.services.importers import DataValidationError


def _quantity(value, field):
    value = str(value).strip()
    if not re.fullmatch(r"[0-9]+", value):
        raise DataValidationError([f"{field} harus bilangan bulat tanpa pemisah ribuan."])
    result = int(value)
    if result > 1_000_000_000:
        raise DataValidationError([f"{field} maksimal 1.000.000.000."])
    return result


def _clean(sku, name, category, unit_price, min_stock, *, initial_stock=None):
    sku = str(sku).strip().upper()
    name = str(name).strip()
    category = str(category).strip()
    errors = []
    if not re.fullmatch(r"[A-Z0-9._-]{2,32}", sku):
        errors.append("SKU harus 2–32 karakter: huruf, angka, titik, - atau _.")
    if not name or len(name) > 120:
        errors.append("Nama produk wajib diisi, maksimal 120 karakter.")
    if not category or len(category) > 80:
        errors.append("Kategori wajib diisi, maksimal 80 karakter.")
    if errors:
        raise DataValidationError(errors)
    values = dict(sku=sku, name=name, category=category,
                  unit_price=_quantity(unit_price, "Harga jual"),
                  min_stock=_quantity(min_stock, "Stok minimum"))
    if initial_stock is not None:
        values["initial_stock"] = _quantity(initial_stock, "Stok awal")
    return values


def create_product(sku, name, category, unit_price, min_stock, initial_stock, *, actor_id=None):
    p = _clean(sku, name, category, unit_price, min_stock, initial_stock=initial_stock)
    with connection() as db:
        try:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM products WHERE sku=?", (p["sku"],)).fetchone():
                raise DataValidationError([f"SKU {p['sku']} sudah terdaftar. Gunakan fitur Edit Produk."])
            cursor = db.execute("""INSERT INTO products(sku,name,category,unit_price,min_stock)
                                    VALUES(?,?,?,?,?)""", (p["sku"], p["name"], p["category"],
                                                        p["unit_price"], p["min_stock"]))
            db.execute("""INSERT INTO stock_movements(product_id,movement_type,delta,note)
                          VALUES(?, 'initial', ?, 'Stok awal dari formulir produk')""",
                       (cursor.lastrowid, p["initial_stock"]))
            write_audit(db, actor_id, 'product.created', 'product', cursor.lastrowid,
                after={**{k:p[k] for k in ('sku','name','category','unit_price','min_stock')},
                       'initial_stock':p['initial_stock'], 'is_active':1},
                summary=f"Produk {p['sku']} dibuat")
            db.commit()
            return cursor.lastrowid
        except sqlite3.IntegrityError as exc:
            db.rollback()
            raise DataValidationError(["SKU sudah digunakan atau data tidak valid."]) from exc
        except Exception:
            db.rollback()
            raise


def get_product(product_id):
    with connection() as db:
        row = db.execute("""SELECT p.*, inv.current_stock FROM products p
                  JOIN product_inventory inv ON inv.id=p.id WHERE p.id=?""", (product_id,)).fetchone()
        return dict(row) if row else None


def list_products(q="", *, status="active"):
    if status not in ("active", "archived"):
        status = "active"
    pattern = "%" + q.strip()[:100] + "%"
    with connection() as db:
        return [dict(r) for r in db.execute("""SELECT p.id,p.sku,p.name,p.category,p.unit_price,p.min_stock,
                        p.is_active, inv.current_stock FROM products p
                        JOIN product_inventory inv ON inv.id=p.id
                        WHERE p.is_active=? AND (p.sku LIKE ? OR p.name LIKE ? OR p.category LIKE ?)
                        ORDER BY p.name COLLATE NOCASE, p.id""",
                (1 if status == "active" else 0, pattern, pattern, pattern))]


def update_product(product_id, name, category, unit_price, min_stock, *, actor_id=None):
    current = get_product(product_id)
    if not current:
        raise DataValidationError(["Produk tidak ditemukan."])
    p = _clean(current["sku"], name, category, unit_price, min_stock)
    with connection() as db:
        try:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT sku,name,category,unit_price,min_stock,is_active FROM products WHERE id=?", (product_id,)).fetchone()
            if not row or not row["is_active"]:
                raise DataValidationError(["Produk tidak aktif atau tidak ditemukan. Aktifkan dahulu sebelum mengedit."])
            db.execute("""UPDATE products SET name=?, category=?, unit_price=?, min_stock=?,
                          updated_at=datetime('now') WHERE id=?""",
                       (p["name"], p["category"], p["unit_price"], p["min_stock"], product_id))
            before = {k: row[k] for k in ('sku','name','category','unit_price','min_stock')}
            after = {k: p[k] for k in ('sku','name','category','unit_price','min_stock')}
            write_audit(db, actor_id, 'product.updated', 'product', product_id,
                        before=before, after=after, summary=f"Produk {row['sku']} diperbarui")
            db.commit()
        except Exception:
            db.rollback()
            raise


def archive_product(product_id, *, actor_id=None):
    with connection() as db:
        try:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("""SELECT p.sku,p.is_active, inv.current_stock FROM products p
                  JOIN product_inventory inv ON inv.id=p.id WHERE p.id=?""", (product_id,)).fetchone()
            if not row:
                raise DataValidationError(["Produk tidak ditemukan."])
            if not row["is_active"]:
                raise DataValidationError(["Produk sudah diarsipkan."])
            if row["current_stock"] != 0:
                raise DataValidationError(["Produk hanya dapat diarsipkan jika stok 0. Habiskan atau sesuaikan stok melalui mekanisme yang terdokumentasi terlebih dahulu."])
            db.execute("UPDATE products SET is_active=0, updated_at=datetime('now') WHERE id=?", (product_id,))
            write_audit(db, actor_id, 'product.archived', 'product', product_id,
                        before={'is_active':1}, after={'is_active':0},
                        summary=f"Produk {row['sku']} diarsipkan")
            db.commit()
        except Exception:
            db.rollback()
            raise


def restore_product(product_id, *, actor_id=None):
    with connection() as db:
        try:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT sku,is_active FROM products WHERE id=?", (product_id,)).fetchone()
            if not row:
                raise DataValidationError(["Produk tidak ditemukan."])
            if row["is_active"]:
                raise DataValidationError(["Produk sudah aktif."])
            db.execute("UPDATE products SET is_active=1, updated_at=datetime('now') WHERE id=?", (product_id,))
            write_audit(db, actor_id, 'product.restored', 'product', product_id,
                        before={'is_active':0}, after={'is_active':1},
                        summary=f"Produk {row['sku']} diaktifkan kembali")
            db.commit()
        except Exception:
            db.rollback()
            raise
