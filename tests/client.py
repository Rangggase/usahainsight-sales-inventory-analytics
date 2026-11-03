"""Authenticated harness for existing regression tests (no production bypass)."""
import re
from fastapi.testclient import TestClient as FastAPITestClient
from app.services.auth import init_admin, get_session, COOKIE_NAME

class TestClient(FastAPITestClient):
    def __enter__(self):
        super().__enter__()
        try:
            init_admin('admin', 'Testing12345!')
        except ValueError as exc:
            if 'sudah ada' not in str(exc):
                raise
        token = re.search(r'name="csrf_token" value="([^"]+)"', super().get('/login').text).group(1)
        response = super().post('/login', data={'username':'admin','password':'Testing12345!','csrf_token':token}, follow_redirects=False)
        assert response.status_code == 303, response.text
        return self

    def post(self, url, *, data=None, files=None, **kwargs):
        if url not in {'/login'}:
            session = get_session(self.cookies.get(COOKIE_NAME, ''))
            if session:
                if isinstance(data, dict):
                    data = dict(data)
                elif isinstance(data, list):
                    data = list(data)
                else:
                    data = {}
                if isinstance(data, dict):
                    data['csrf_token'] = session['csrf_token']
                else:
                    data.append(('csrf_token', session['csrf_token']))
        return super().post(url, data=data, files=files, **kwargs)
