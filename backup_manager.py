"""Local CLI for safe database backup / verification / offline restore.

Windows: .\\.venv\\Scripts\\python.exe backup_manager.py backup
"""
import argparse
import socket
import sys
from pathlib import Path

from app.services.backups import BackupError, create_backup, list_backups, restore_backup, verify_backup


def ensure_server_stopped():
    """Refuse restore when the local app port is reachable."""
    try:
        with socket.create_connection(("127.0.0.1", 8000), timeout=0.35):
            raise BackupError("Port 8000 masih aktif. Hentikan server FastAPI (Ctrl+C) sebelum restore.")
    except (ConnectionRefusedError, TimeoutError, OSError):
        return


def main(argv=None):
    parser = argparse.ArgumentParser(description="UsahaInsight v1.3: backup dan pemulihan SQLite")
    parser.add_argument("--db", type=Path, help="Lokasi database (opsional; default instance/usahainsight.db)")
    parser.add_argument("--backup-dir", type=Path, help="Folder backup (opsional; default backups/)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("backup", help="Backup database, boleh saat server aktif")
    sub.add_parser("list", help="Daftar snapshot dan status integritas")
    check = sub.add_parser("verify", help="Verifikasi backup + manifest")
    check.add_argument("file", type=Path)
    restore = sub.add_parser("restore", help="Pulihkan database (server harus dihentikan)")
    restore.add_argument("file", type=Path)
    restore.add_argument("--confirm", action="store_true", help="Saya paham database saat ini akan diganti")
    args = parser.parse_args(argv)

    try:
        options = {"db_path": args.db, "backup_dir": args.backup_dir}
        if args.command == "backup":
            file = create_backup(**options)
            print("BERHASIL: Backup tersimpan dan tervalidasi:", file)
            print("Salin berkas .db dan .json ke drive lain sebagai backup tambahan.")
        elif args.command == "list":
            entries = list_backups(backup_dir=args.backup_dir)
            print("Belum ada backup." if not entries else "Daftar backup:")
            for path, status in entries:
                print(f"- {path.name}: {status}")
        elif args.command == "verify":
            manifest = verify_backup(args.file, backup_dir=args.backup_dir)
            print("VALID: SHA-256, integritas SQLite, foreign key, skema, dan jumlah baris cocok.")
            print("Dibuat (UTC):", manifest["created_at_utc"])
            print("Rekap tabel:", manifest["counts"])
        elif args.command == "restore":
            if not args.confirm:
                raise BackupError("Restore membutuhkan --confirm. Hentikan server dan simpan data penting dahulu.")
            ensure_server_stopped()
            safety = restore_backup(args.file, **options)
            print("BERHASIL: Database dipulihkan dari:", args.file)
            if safety:
                print("Salinan keamanan data SEBELUM restore:", safety)
            print("Jalankan pengujian aplikasi dan periksa dashboard sebelum melanjutkan input data.")
        return 0
    except (BackupError, OSError) as exc:
        print("GAGAL:", exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
