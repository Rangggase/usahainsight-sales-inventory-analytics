"""Security regression tests; do not bypass authentication."""
from datetime import timedelta
import re
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.database import connection
from app.services.auth import (init_admin, authenticate, get_session,
    revoke_session, create_session, COOKIE_NAME, utcnow)

@pytest.fixture
def guest(tmp_path, monkeypatch):
    monkeypatch.setenv('USAHAINSIGHT_DB', str(tmp_path / 'auth.db'))
    with TestClient(app) as client:
        yield client


def login(client, username='admin', password='GreatTestPassword123'):
    page = client.get('/login')
    assert page.status_code == 200
    token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
    return client.post('/login', data={'username':username, 'password':password,
                                       'csrf_token':token}, follow_redirects=False)


def test_all_business_pages_and_exports_require_login(guest):
    for url in ('/','/products','/transactions/new','/reports/export?format=xlsx','/api/docs','/openapi.json','/samples/products'):
        response = guest.get(url, follow_redirects=False)
        assert response.status_code == 303, (url,response.status_code)
        assert response.headers['location'] == '/login'
    assert guest.get('/health').status_code == 200
    assert guest.get('/static/style.css').status_code == 200
    assert guest.post('/products/new', data={'sku':'BAD'}).status_code == 401


def test_setup_has_no_default_password_and_validates_password(guest):
    assert 'Administrator belum dibuat' in guest.get('/login').text
    assert login(guest).status_code == 401
    with pytest.raises(ValueError, match='12'):
        init_admin('admin', 'weak')
    init_admin('admin','GreatTestPassword123')
    with pytest.raises(ValueError, match='sudah ada'):
        init_admin('attacker','AnotherStrongPassword12')
    with connection() as db:
        rec = db.execute('SELECT username,password_hash FROM auth_users').fetchone()
    assert rec['username'] == 'admin'
    assert rec['password_hash'].startswith('$argon2id$')
    assert 'GreatTestPassword123' not in rec['password_hash']


def test_login_logout_and_session_revocation(guest):
    init_admin('admin','GreatTestPassword123')
    response = login(guest)
    assert response.status_code == 303
    assert response.headers['location']=='/'
    assert 'httponly' in response.headers['set-cookie'].lower()
    assert 'samesite=strict' in response.headers['set-cookie'].lower()
    token = guest.cookies.get(COOKIE_NAME)
    assert token and get_session(token)
    assert guest.get('/').status_code == 200
    assert 'name="csrf_token"' in guest.get('/products/new').text
    logout = guest.post('/logout', data={'csrf_token':get_session(token)['csrf_token']}, follow_redirects=False)
    assert logout.status_code == 303
    assert get_session(token) is None
    assert guest.get('/products', follow_redirects=False).status_code == 303


def test_login_rejects_missing_or_wrong_csrf(guest):
    init_admin('admin','GreatTestPassword123')
    guest.get('/login')
    response = guest.post('/login', data={'username':'admin', 'password':'GreatTestPassword123'})
    assert response.status_code == 403
    assert not guest.cookies.get(COOKIE_NAME)
    response = guest.post('/login', data={'username':'admin','password':'GreatTestPassword123','csrf_token':'fake'})
    assert response.status_code == 403


def test_business_writes_reject_missing_and_wrong_csrf(guest):
    init_admin('admin','GreatTestPassword123')
    assert login(guest).status_code==303
    initial = guest.post('/products/new', data={'sku':'TEST-BAD','name':'Bad','category':'T','unit_price':'10', 'min_stock':'1','initial_stock':'1'}, follow_redirects=False)
    assert initial.status_code==403
    wrong = guest.post('/products/new', data={'csrf_token':'INVALID', 'sku':'TEST-BAD','name':'Bad','category':'T','unit_price':'10','min_stock':'1','initial_stock':'1'}, follow_redirects=False)
    assert wrong.status_code==403
    assert guest.post('/logout').status_code==403
    token=guest.cookies.get(COOKIE_NAME)
    good=guest.post('/products/new', data={'csrf_token':get_session(token)['csrf_token'], 'sku':'TEST-GOOD','name':'Good','category':'T','unit_price':'10','min_stock':'1','initial_stock':'1'}, follow_redirects=False)
    assert good.status_code==303
    with connection() as db:
        assert db.execute("SELECT COUNT(*) FROM products WHERE sku='TEST-BAD'").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM products WHERE sku='TEST-GOOD'").fetchone()[0] == 1


def test_login_bad_password_and_lockout(guest):
    init_admin('admin','GreatTestPassword123')
    for i in range(5):
        assert login(guest,password='WrongPassword101') .status_code==401
    assert login(guest).status_code==401  # valid password still locked
    with connection() as db:
        rec=db.execute("SELECT failures,locked_until FROM auth_users WHERE username='admin'").fetchone()
        assert rec['failures']==5 and rec['locked_until']
        db.execute("UPDATE auth_users SET locked_until=? WHERE username='admin'",((utcnow()-timedelta(seconds=1)).isoformat(),))
        db.commit()
    assert login(guest).status_code==303


def test_session_expiry_and_reset_password_invalidates_sessions(guest):
    init_admin('admin','GreatTestPassword123')
    assert login(guest).status_code==303
    token=guest.cookies.get(COOKIE_NAME)
    with connection() as db:
        db.execute('UPDATE auth_sessions SET expires_at=?', ((utcnow()-timedelta(seconds=1)).isoformat(),))
        db.commit()
    assert get_session(token) is None
    assert guest.get('/inventory',follow_redirects=False).status_code==303
    assert login(guest).status_code==303
    token2=guest.cookies.get(COOKIE_NAME)
    init_admin('admin','BrandNewPassword1234',reset=True)
    assert get_session(token2) is None
    assert login(guest,password='GreatTestPassword123').status_code==401
    assert login(guest,password='BrandNewPassword1234').status_code==303


def test_session_rejects_modified_cookie_and_token_not_stored_raw(guest):
    init_admin('admin','GreatTestPassword123')
    assert login(guest).status_code==303
    token=guest.cookies.get(COOKIE_NAME)
    with connection() as db:
        stored=db.execute('SELECT token_hash FROM auth_sessions').fetchone()['token_hash']
        assert len(stored)==64 and token not in stored
    assert get_session(token + 'BAD') is None
    revoke_session(token)
    assert get_session(token) is None


def test_secure_cookie_flag_for_https(monkeypatch, guest):
    monkeypatch.setenv('USAHAINSIGHT_COOKIE_SECURE','1')
    init_admin('admin','GreatTestPassword123')
    response=guest.get('/login')
    assert 'secure' in response.headers['set-cookie'].lower()
