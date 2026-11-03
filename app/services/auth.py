"""Single-admin local web auth: Argon2id, server-side revocable sessions, CSRF.

No hardcoded credentials; provision admin via local auth_manager.py CLI.
"""
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher, Type
from argon2.exceptions import VerifyMismatchError, VerificationError
from app.database import connection

COOKIE_NAME = 'ui_session'
LOGIN_CSRF_COOKIE = 'ui_login_csrf_v2'
SESSION_HOURS = 8
MAX_FAILURES = 5
LOCK_MINUTES = 15
ph = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2, hash_len=32, salt_len=16, type=Type.ID)
DUMMY_HASH = ph.hash(secrets.token_urlsafe(32))  # Consistent work for unknown usernames


def utcnow():
    return datetime.now(timezone.utc)


def setup_schema():
    with connection() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS auth_users (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          username TEXT NOT NULL UNIQUE,
          password_hash TEXT NOT NULL,
          failures INTEGER NOT NULL DEFAULT 0,
          locked_until TEXT,
          created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS auth_sessions (
          token_hash TEXT PRIMARY KEY,
          user_id INTEGER NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
          csrf_token TEXT NOT NULL,
          expires_at TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_ui_sessions_expiry ON auth_sessions(expires_at);
        ''')


def _validate_password(password):
    if len(password) < 12 or len(password) > 256:
        raise ValueError('Password harus 12–256 karakter.')
    if not any(ch.isalpha() for ch in password) or not any(ch.isdigit() for ch in password):
        raise ValueError('Password harus mengandung huruf dan angka.')


def init_admin(username: str, password: str, *, reset=False):
    """Explicit CLI-only provisioning; reset invalidates every existing session."""
    if not re.fullmatch(r'[A-Za-z0-9_]{3,40}', username):
        raise ValueError('Username hanya boleh huruf, angka, underscore (3–40 karakter).')
    _validate_password(password)
    setup_schema()
    encoded = ph.hash(password)
    with connection() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT id, username FROM auth_users LIMIT 1').fetchone()
        if row and not reset:
            raise ValueError('Administrator sudah ada; gunakan set-password untuk mengubah password.')
        if row and reset:
            if row['username'] != username:
                raise ValueError('Username tidak cocok dengan administrator yang sudah ada.')
            db.execute('UPDATE auth_users SET password_hash=?, failures=0, locked_until=NULL WHERE id=?', (encoded, row['id']))
            db.execute('DELETE FROM auth_sessions')
        else:
            db.execute('INSERT INTO auth_users(username,password_hash) VALUES(?,?)', (username, encoded))
        db.commit()


def has_admin():
    with connection() as db:
        return bool(db.execute('SELECT 1 FROM auth_users LIMIT 1').fetchone())


def authenticate(username, password):
    """Return authenticated user id, or None. Lock account after repeated bad guesses."""
    with connection() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT * FROM auth_users WHERE username=?', (username,)).fetchone()
        if row is None:
            try:
                ph.verify(DUMMY_HASH, password or 'invalid')
            except (VerifyMismatchError, VerificationError, ValueError, TypeError):
                pass
            db.commit()
            return None
        until = row['locked_until']
        if until and datetime.fromisoformat(until) > utcnow():
            db.commit()
            return None
        try:
            passed = ph.verify(row['password_hash'], password)
        except (VerifyMismatchError, VerificationError, ValueError, TypeError):
            passed = False
        if not passed:
            failures = int(row['failures']) + 1
            lock = (utcnow() + timedelta(minutes=LOCK_MINUTES)).isoformat() if failures >= MAX_FAILURES else None
            db.execute('UPDATE auth_users SET failures=?, locked_until=? WHERE id=?', (failures, lock, row['id']))
            db.commit()
            return None
        db.execute('UPDATE auth_users SET failures=0, locked_until=NULL WHERE id=?', (row['id'],))
        db.commit()
        return row['id']


def create_session(user_id):
    token = secrets.token_urlsafe(36)
    csrf = secrets.token_urlsafe(36)
    now = utcnow()
    expiry = now + timedelta(hours=SESSION_HOURS)
    with connection() as db:
        db.execute('DELETE FROM auth_sessions WHERE expires_at<=?', (now.isoformat(),))
        db.execute('INSERT INTO auth_sessions(token_hash,user_id,csrf_token,expires_at,created_at) VALUES(?,?,?,?,?)',
                   (_digest(token), user_id, csrf, expiry.isoformat(), now.isoformat()))
        db.commit()
    return token


def _digest(token):
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def get_session(token):
    if not token or len(token) > 512:
        return None
    with connection() as db:
        row = db.execute('''SELECT s.csrf_token,s.expires_at,u.id,u.username
            FROM auth_sessions s JOIN auth_users u ON u.id=s.user_id
            WHERE s.token_hash=?''', (_digest(token),)).fetchone()
    if not row or datetime.fromisoformat(row['expires_at']) <= utcnow():
        return None
    return {'id': row['id'], 'username': row['username'], 'csrf_token': row['csrf_token']}


def revoke_session(token):
    if not token:
        return
    with connection() as db:
        db.execute('DELETE FROM auth_sessions WHERE token_hash=?', (_digest(token),))
        db.commit()


def secure_cookie():
    # HTTPS deployment MUST set USAHAINSIGHT_COOKIE_SECURE=1.
    return os.environ.get('USAHAINSIGHT_COOKIE_SECURE', '').strip().lower() in {'1','true','yes'}


def csrf_matches(actual, expected):
    return isinstance(actual, str) and isinstance(expected, str) and hmac.compare_digest(actual, expected)
