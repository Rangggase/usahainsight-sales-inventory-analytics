"""Regressions for browser login-cookie and CSRF flow (v1.3b hotfix)."""
import re
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.services.auth import LOGIN_CSRF_COOKIE, COOKIE_NAME, init_admin


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('USAHAINSIGHT_DB', str(tmp_path/'csrf-test.db'))
    monkeypatch.setenv('USAHAINSIGHT_COOKIE_SECURE', '0')
    with TestClient(app) as c:
        init_admin('admin', 'StrongPassword12345')
        yield c


def form_token(html):
    return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)


def test_two_login_tabs_do_not_invalidate_earlier_form(client):
    first = client.get('/login')
    second = client.get('/login')
    assert form_token(first.text) == form_token(second.text)
    assert client.cookies.get(LOGIN_CSRF_COOKIE) == form_token(first.text)
    response = client.post('/login', data={'username':'admin','password':'StrongPassword12345',
                    'csrf_token':form_token(first.text)}, follow_redirects=False)
    assert response.status_code == 303
    assert client.cookies.get(COOKIE_NAME)


def test_missing_cookie_returns_readable_retry_form_but_does_not_authenticate(client):
    old_form = client.get('/login')
    client.cookies.delete(LOGIN_CSRF_COOKIE)
    resp = client.post('/login', data={'username':'admin','password':'StrongPassword12345',
                          'csrf_token':form_token(old_form.text)}, follow_redirects=False)
    assert resp.status_code == 403
    assert 'Cookie keamanan login tidak dikirim' in resp.text
    assert not client.cookies.get(COOKIE_NAME)
    new_token = form_token(resp.text)
    assert client.cookies.get(LOGIN_CSRF_COOKIE) == new_token
    good = client.post('/login', data={'username':'admin','password':'StrongPassword12345',
                              'csrf_token':new_token}, follow_redirects=False)
    assert good.status_code == 303


def test_mismatched_form_rotates_token_and_allows_retry(client):
    client.get('/login')
    resp = client.post('/login', data={'username':'admin','password':'StrongPassword12345',
                         'csrf_token':'not-correct'}, follow_redirects=False)
    assert resp.status_code == 403
    assert 'Token keamanan tidak cocok' in resp.text
    assert not client.cookies.get(COOKIE_NAME)
    new_token = form_token(resp.text)
    assert client.post('/login', data={'username':'admin','password':'StrongPassword12345',
                        'csrf_token':new_token}, follow_redirects=False).status_code == 303


def test_secure_flag_still_respected(client,monkeypatch):
    monkeypatch.setenv('USAHAINSIGHT_COOKIE_SECURE', '1')
    r = client.get('/login')
    assert 'secure' in r.headers.get('set-cookie','').lower()


def test_login_cookie_still_httponly_and_lax(client):
    r = client.get('/login')
    header = r.headers.get('set-cookie','').lower()
    assert 'httponly' in header
    assert 'samesite=lax' in header
