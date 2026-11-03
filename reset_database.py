"""Destructive local reset, run while server is stopped."""
import argparse
import sqlite3
from pathlib import Path
from app.database import database_path, init_db
from app.demo import seed_when_empty

MARKER = database_path().parent / ".start_empty"


def reset(mode):
    path = database_path()
    # Remove SQLite database plus possible write-ahead log remnants.
    for target in [path, Path(str(path) + "-wal"), Path(str(path) + "-shm")]:
        if target.exists():
            target.unlink()
    if mode == "empty":
        MARKER.touch()
        init_db()
        print("Database kosong dibuat. Impor produk sebelum penjualan.")
    elif mode == "demo":
        MARKER.unlink(missing_ok=True)
        init_db()
        seed_when_empty()
        print("Database data demo sintetis dibuat ulang.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HAPUS database lokal lalu buat data demo atau kosong.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--empty", action="store_true", help="reset ke database kosong")
    group.add_argument("--demo", action="store_true", help="reset ke data contoh sintetis")
    args = parser.parse_args()
    print("PERINGATAN: semua data database lokal saat ini akan terhapus.")
    reply = input("Ketik RESET untuk melanjutkan: ").strip()
    if reply != "RESET":
        print("Dibatalkan.")
    else:
        reset("empty" if args.empty else "demo")
