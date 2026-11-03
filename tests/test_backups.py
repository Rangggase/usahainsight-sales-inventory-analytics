"""v1.3a: local SQLite backup / restore acceptance and negative tests."""
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.backups import (BackupError, create_backup, list_backups,
                                  restore_backup, verify_backup)
from app.database import connection
from backup_manager import main as cli_main


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    db = tmp_path / "instance" / "business.db"
    backup_dir = tmp_path / "backups"
    monkeypatch.setenv("USAHAINSIGHT_DB", str(db))
    with TestClient(app):
        yield db, backup_dir


def test_backup_contains_all_tables_and_manifest(workspace):
    db, out = workspace
    archive = create_backup(db_path=db, backup_dir=out)
    info = verify_backup(archive, backup_dir=out)
    assert info["counts"]["products"] == 24
    assert info["counts"]["transactions"] >= 100
    assert info["start_empty"] is False
    assert archive.with_suffix(".json").is_file()
    assert info["bytes"] == archive.stat().st_size


def test_backup_list_and_verify(workspace):
    db, out = workspace
    archive = create_backup(db_path=db, backup_dir=out)
    rows = list_backups(backup_dir=out)
    assert rows == [(archive, "VALID")]


def test_tampered_sqlite_is_rejected(workspace):
    db, out = workspace
    archive = create_backup(db_path=db, backup_dir=out)
    with archive.open("ab") as f:
        f.write(b"corrupted")
    with pytest.raises(BackupError, match="hash SHA-256"):
        verify_backup(archive, backup_dir=out)
    assert "TIDAK VALID" in list_backups(backup_dir=out)[0][1]


def test_modified_manifest_is_rejected(workspace):
    db, out = workspace
    archive = create_backup(db_path=db, backup_dir=out)
    path = archive.with_suffix(".json")
    data = json.loads(path.read_text(encoding="utf-8"))
    data["database_file"] = "another.db"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(BackupError, match="manifest"):
        verify_backup(archive, backup_dir=out)


def test_restore_reverts_updates_and_creates_safety_copy(workspace):
    db, out = workspace
    original = create_backup(db_path=db, backup_dir=out)
    with connection() as conn:
        conn.execute("UPDATE products SET unit_price=7654321 WHERE id=1")
        conn.commit()
    snapshot = restore_backup(original, db_path=db, backup_dir=out)
    assert snapshot is not None and "pre-restore" in snapshot.name
    with connection() as conn:
        assert conn.execute("SELECT unit_price FROM products WHERE id=1").fetchone()[0] != 7654321
    # Safety copy contains state immediately before restore.
    assert verify_backup(snapshot, backup_dir=out)["counts"]["products"] == 24
    with sqlite3.connect(snapshot) as conn:
        assert conn.execute("SELECT unit_price FROM products WHERE id=1").fetchone()[0] == 7654321


def test_restore_stores_empty_marker_state(workspace):
    db, out = workspace
    marker = db.parent / ".start_empty"
    marker.touch()
    archive = create_backup(db_path=db, backup_dir=out)
    marker.unlink()
    restore_backup(archive, db_path=db, backup_dir=out)
    assert marker.is_file()
    marker.unlink()


def test_restore_removes_old_empty_marker(workspace):
    db, out = workspace
    archive = create_backup(db_path=db, backup_dir=out)
    marker = db.parent / ".start_empty"
    marker.touch()
    restore_backup(archive, db_path=db, backup_dir=out)
    assert not marker.exists()


def test_no_database_does_not_create_a_fake_backup(tmp_path):
    db = tmp_path / "never-existed.db"
    output = tmp_path / "backups"
    with pytest.raises(BackupError, match="Database belum ada"):
        create_backup(db_path=db, backup_dir=output)
    assert not db.exists()


def test_foreign_key_errors_block_backup(workspace):
    db, out = workspace
    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("INSERT INTO transaction_items(transaction_id,product_id,quantity,unit_price,line_total) VALUES (999999,999999,1,1,1)")
        conn.commit()
    with pytest.raises(BackupError, match="foreign key"):
        create_backup(db_path=db, backup_dir=out)
    assert not list(out.glob("*.db"))


def test_restore_rejects_external_file_even_if_valid(workspace, tmp_path):
    db, out = workspace
    external = tmp_path / "external" / "other"
    other = create_backup(db_path=db, backup_dir=external)
    with pytest.raises(BackupError, match="folder backups"):
        restore_backup(other, db_path=db, backup_dir=out)


def test_cli_local_backup_and_verify(workspace, capsys):
    db, out = workspace
    assert cli_main(["--db", str(db), "--backup-dir", str(out), "backup"]) == 0
    created = next(out.glob("*.db"))
    assert cli_main(["--db", str(db), "--backup-dir", str(out), "verify", str(created)]) == 0
    assert "VALID" in capsys.readouterr().out


def test_cli_restore_requires_explicit_confirmation(workspace, capsys):
    db, out = workspace
    archive = create_backup(db_path=db, backup_dir=out)
    code = cli_main(["--db", str(db), "--backup-dir", str(out), "restore", str(archive)])
    assert code == 1
    assert "--confirm" in capsys.readouterr().err


def test_restore_with_missing_manifest_never_modifies_live_database(workspace):
    db, out = workspace
    archive = create_backup(db_path=db, backup_dir=out)
    archive.with_suffix(".json").unlink()
    before = db.read_bytes()
    with pytest.raises(BackupError, match="Manifest"):
        restore_backup(archive, db_path=db, backup_dir=out)
    assert db.read_bytes() == before
