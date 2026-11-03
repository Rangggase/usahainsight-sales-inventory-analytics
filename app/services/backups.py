"""Offline recovery and online-consistent SQLite backup for local UsahaInsight.

No web route is exposed: a backup holds all sales data; only a local terminal
user should be able to create, inspect and restore it until authentication exists.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from contextlib import closing
from pathlib import Path
import shutil
import sqlite3
from uuid import uuid4

from app.database import ROOT, database_path

BACKUP_FORMAT = "usahainsight.sqlite.backup.v1"
BACKUP_DIRECTORY = ROOT / "backups"
REQUIRED_TABLES = {"products", "transactions", "transaction_items", "stock_movements", "manual_sale_requests"}


class BackupError(Exception):
    """An expected backup validation / restore error, suitable for CLI display."""


def _paths(db_path: Path | str | None, backup_dir: Path | str | None) -> tuple[Path, Path]:
    return (Path(db_path).resolve() if db_path is not None else database_path(),
            Path(backup_dir).resolve() if backup_dir is not None else BACKUP_DIRECTORY.resolve())


def _open_readonly(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise BackupError(f"File database tidak ditemukan: {path}")
    # SQLite's URI mode=ro prevents accidentally creating a missing SQLite file.
    from urllib.parse import quote
    uri = "file:" + quote(path.as_posix(), safe="/:\\") + "?mode=ro"
    return sqlite3.connect(uri, uri=True, timeout=20)


def _inspect(path: Path) -> dict[str, int]:
    try:
        with closing(_open_readonly(path)) as conn:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()
            if integrity is None or integrity[0] != "ok":
                raise BackupError(f"Integritas SQLite gagal: {integrity}")
            violation = conn.execute("PRAGMA foreign_key_check").fetchone()
            if violation is not None:
                raise BackupError("Ada foreign key yang tidak valid pada database.")
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            missing = REQUIRED_TABLES - tables
            if missing:
                raise BackupError("Tabel yang diperlukan tidak ada: " + ", ".join(sorted(missing)))
            return {name: conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
                    for name in sorted(REQUIRED_TABLES)}
    except BackupError:
        raise
    except (sqlite3.Error, OSError) as exc:
        raise BackupError(f"Database tidak dapat diverifikasi: {exc}") from exc


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fp:
        for chunk in iter(lambda: fp.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_json_atomic(path: Path, document: dict) -> None:
    tmp = path.with_name("." + path.name + "." + uuid4().hex + ".tmp")
    try:
        with tmp.open("x", encoding="utf-8") as fp:
            json.dump(document, fp, ensure_ascii=False, indent=2, sort_keys=True)
            fp.write("\n")
            fp.flush()
            os.fsync(fp.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def create_backup(*, db_path: Path | str | None = None,
                  backup_dir: Path | str | None = None,
                  label: str = "manual") -> Path:
    """Create a SQLite-consistent DB snapshot plus hash manifest; server may run."""
    db, directory = _paths(db_path, backup_dir)
    if label not in {"manual", "pre-restore"}:
        raise BackupError("Label backup tidak dikenal.")
    if not db.is_file():
        raise BackupError(f"Database belum ada: {db}. Jalankan aplikasi terlebih dahulu.")
    directory.mkdir(parents=True, exist_ok=True)
    if directory == db.parent:
        raise BackupError("Folder backup sebaiknya terpisah dari folder database.")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    filename = f"usahainsight-{label}-{stamp}-{uuid4().hex[:6]}.db"
    final = directory / filename
    temporary = directory / ("." + filename + "." + uuid4().hex + ".tmp")
    try:
        try:
            with closing(_open_readonly(db)) as source:
                with closing(sqlite3.connect(temporary, timeout=30)) as target:
                    source.backup(target, pages=256, sleep=0.1)
        except (sqlite3.Error, OSError) as exc:
            raise BackupError(f"Pembuatan snapshot gagal: {exc}") from exc
        counts = _inspect(temporary)
        manifest = {
            "format": BACKUP_FORMAT,
            "database_file": filename,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "label": label,
            "sha256": _hash_file(temporary),
            "bytes": temporary.stat().st_size,
            "counts": counts,
            "start_empty": (db.parent / ".start_empty").exists(),
        }
        os.replace(temporary, final)
        try:
            _write_json_atomic(final.with_suffix(".json"), manifest)
        except OSError as exc:
            final.unlink(missing_ok=True)
            raise BackupError(f"Manifest backup gagal disimpan: {exc}") from exc
        return final
    finally:
        temporary.unlink(missing_ok=True)


def _check_managed_backup(file_path: Path, directory: Path) -> Path:
    path = file_path.absolute()
    if path.suffix.lower() != ".db" or path.parent.resolve() != directory.resolve() or path.is_symlink():
        raise BackupError("Backup harus berupa file .db langsung di folder backups, bukan link/path luar.")
    if not path.is_file():
        raise BackupError(f"File backup tidak ditemukan: {path}")
    return path


def verify_backup(file_path: Path | str, *, backup_dir: Path | str | None = None) -> dict:
    """Validate provenance, SHA-256, SQLite integrity, schema and row counts."""
    directory = Path(backup_dir).resolve() if backup_dir is not None else BACKUP_DIRECTORY.resolve()
    file_path = _check_managed_backup(Path(file_path), directory)
    manifest_file = file_path.with_suffix(".json")
    try:
        metadata = json.loads(manifest_file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BackupError("Manifest JSON tidak tersedia atau tidak valid.") from exc
    if not isinstance(metadata, dict):
        raise BackupError("Format manifest tidak valid.")
    if (metadata.get("format") != BACKUP_FORMAT or metadata.get("database_file") != file_path.name
            or type(metadata.get("start_empty")) is not bool):
        raise BackupError("Identitas atau format manifest backup tidak sesuai.")
    if metadata.get("bytes") != file_path.stat().st_size or metadata.get("sha256") != _hash_file(file_path):
        raise BackupError("Ukuran atau hash SHA-256 backup berubah. Backup ditolak.")
    counts = _inspect(file_path)
    if counts != metadata.get("counts"):
        raise BackupError("Jumlah data dalam backup berbeda dari manifest.")
    return metadata


def list_backups(*, backup_dir: Path | str | None = None) -> list[tuple[Path, str]]:
    directory = Path(backup_dir).resolve() if backup_dir is not None else BACKUP_DIRECTORY.resolve()
    if not directory.exists():
        return []
    result = []
    for path in sorted(directory.glob("usahainsight-*.db"), reverse=True):
        try:
            verify_backup(path, backup_dir=directory)
            state = "VALID"
        except BackupError as exc:
            state = f"TIDAK VALID ({exc})"
        result.append((path, state))
    return result


def restore_backup(file_path: Path | str, *, db_path: Path | str | None = None,
                   backup_dir: Path | str | None = None) -> Path | None:
    """Offline restore, with an automatic pre-restore safety backup.

    Caller MUST stop the server first. The CLI checks its default local port;
    this function remains useful for isolated programmatic testing.
    """
    db, directory = _paths(db_path, backup_dir)
    info = verify_backup(file_path, backup_dir=directory)
    backup = _check_managed_backup(Path(file_path), directory)
    if db.resolve() == backup.resolve():
        raise BackupError("Database aktif dan backup tidak boleh sama.")
    db.parent.mkdir(parents=True, exist_ok=True)

    # Checkpoint any leftover WAL on a stopped server, so no stale WAL is
    # replayed onto the newly restored main database file.
    if db.is_file():
        try:
            with closing(sqlite3.connect(db, timeout=2)) as active:
                active.execute("PRAGMA busy_timeout=2000")
                active.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                active.execute("PRAGMA journal_mode=DELETE")
        except sqlite3.Error as exc:
            raise BackupError("Database masih dipakai atau gagal checkpoint. Hentikan server: " + str(exc)) from exc
        if (db.parent / (db.name + "-wal")).exists():
            raise BackupError("File WAL masih ada. Pastikan semua koneksi aplikasi telah berhenti.")

    safety = create_backup(db_path=db, backup_dir=directory, label="pre-restore") if db.is_file() else None
    staging = db.parent / (".restore-" + uuid4().hex + ".tmp")
    try:
        # Transfer verified bytes to same filesystem as the target for atomic replace.
        with backup.open("rb") as src, staging.open("xb") as dst:
            shutil.copyfileobj(src, dst, 1024 * 1024)
            dst.flush()
            os.fsync(dst.fileno())
        if _hash_file(staging) != info["sha256"]:
            raise BackupError("Salinan restore berubah selama proses penyalinan.")
        _inspect(staging)
        # Restore backup's explicit empty-reset marker so empty databases do
        # not get silently populated with demo data upon next app startup.
        marker = db.parent / ".start_empty"
        was_empty = marker.exists()
        want_empty = info["start_empty"]
        try:
            if want_empty:
                marker.touch(exist_ok=True)
            else:
                marker.unlink(missing_ok=True)
            os.replace(staging, db)
        except OSError as exc:
            # Roll back marker if Windows denies replacing an open database.
            if was_empty:
                marker.touch(exist_ok=True)
            else:
                marker.unlink(missing_ok=True)
            raise BackupError("Restore gagal (database mungkin masih terbuka): " + str(exc)) from exc
        return safety
    finally:
        staging.unlink(missing_ok=True)
