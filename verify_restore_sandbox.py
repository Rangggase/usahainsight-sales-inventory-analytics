"""Safe offline backup/restore acceptance test for Windows, macOS, and Linux.

Usage: .\\.venv\\Scripts\\python.exe verify_restore_sandbox.py

All modifications are isolated to a temporary database. The production database
is only read through SQLite's online backup API and never used as a restore
TARGET. SQLite connections are explicitly closed before file replacement,
which is essential for reliable behavior on Windows.
"""

from contextlib import closing
from hashlib import sha256
from pathlib import Path
from uuid import uuid4
import shutil
import sqlite3
import tempfile
import traceback

from backup_manager import ensure_server_stopped
from app.database import database_path
from app.services.backups import BackupError, create_backup, restore_backup, verify_backup


def digest(path: Path) -> str:
    checksum = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(block)
    return checksum.hexdigest()


def main() -> int:
    stage = "pemeriksaan awal"
    original_hash = None
    production_db = database_path()

    try:
        ensure_server_stopped()
        if not production_db.is_file():
            raise BackupError(f"Database utama belum ditemukan: {production_db}")
        original_hash = digest(production_db)

        # Store BOTH the test backup and sandbox database in an isolated folder.
        # No file in the project's permanent backups/ folder is modified.
        with tempfile.TemporaryDirectory(prefix="usahainsight-restore-test-") as tmp:
            test_root = Path(tmp)
            test_backup_dir = test_root / "backup_snapshots"
            sandbox_db = test_root / "sandbox.db"

            stage = "membuat snapshot pengujian"
            archive = create_backup(db_path=production_db, backup_dir=test_backup_dir)
            manifest = verify_backup(archive, backup_dir=test_backup_dir)

            stage = "menyiapkan database sandbox"
            shutil.copyfile(archive, sandbox_db)
            test_sku = "SANDBOX-" + uuid4().hex[:12].upper()

            stage = "menulis data percobaan ke sandbox"
            # Unlike `with sqlite3.connect(...) as db`, closing() REALLY closes
            # the OS file handle on Windows when the block exits.
            with closing(sqlite3.connect(sandbox_db, timeout=10)) as db:
                with db:
                    db.execute(
                        "INSERT INTO products (sku, name, category, unit_price, min_stock) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (test_sku, "Hanya di database sandbox", "Pengujian", 1000, 0),
                    )

            stage = "memulihkan database sandbox"
            safety = restore_backup(archive, db_path=sandbox_db, backup_dir=test_backup_dir)

            stage = "memeriksa hasil restore"
            if digest(sandbox_db) != digest(archive):
                raise BackupError("Database sandbox berbeda dari snapshot yang dipulihkan.")

            with closing(sqlite3.connect(sandbox_db, timeout=10)) as db:
                remaining = db.execute(
                    "SELECT COUNT(*) FROM products WHERE sku=?", (test_sku,)
                ).fetchone()[0]
            if remaining != 0:
                raise BackupError("Data percobaan masih ada setelah restore.")

            stage = "memverifikasi backup pengaman"
            if safety is None:
                raise BackupError("Backup pengaman sebelum restore tidak tercipta.")
            if verify_backup(safety, backup_dir=test_backup_dir).get("label") != "pre-restore":
                raise BackupError("Manifest backup pengaman tidak sesuai.")

            stage = "membersihkan file pengujian sementara"
            # TemporaryDirectory cleans up AFTER all SQLite connections close.

        stage = "memastikan database utama tidak berubah"
        if digest(production_db) != original_hash:
            raise BackupError("Checksum database utama berubah. Hentikan pengujian.")

        print("LULUS: Snapshot tervalidasi dan restore sandbox berhasil.")
        print("LULUS: Data percobaan terhapus setelah pemulihan sandbox.")
        print("LULUS: Database utama tidak berubah (SHA-256 identik).")
        print("Rekap snapshot:", manifest["counts"])
        return 0

    except (OSError, sqlite3.Error, BackupError) as exc:
        print(f"GAGAL pada tahap '{stage}': {exc}")
        # Full traceback makes platform-specific errors diagnosable on Windows.
        traceback.print_exc()
        return 1

    finally:
        # Read-only checksum check even when earlier steps fail.
        if original_hash is not None and production_db.is_file():
            try:
                if digest(production_db) != original_hash:
                    print("PERINGATAN: Checksum database utama berubah selama pengujian!")
            except OSError as exc:
                print(f"PERINGATAN: Tidak dapat memeriksa hash database utama: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())
