import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from gitshield.web.security import hostname


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from gitshield.web import app as app_module
    from gitshield.web.config import settings

    monkeypatch.setattr(settings, "db_path", tmp_path / "s.db")
    monkeypatch.setattr(settings, "auto_review_interval", 0)
    with TestClient(app_module.app, base_url="http://127.0.0.1:8000") as c:
        yield c


@pytest.mark.parametrize("raw,expected", [
    ("localhost:8000", "localhost"), ("127.0.0.1", "127.0.0.1"), ("[::1]:8000", "::1"), ("Evil.Example:80", "evil.example"),
])
def test_hostname(raw, expected):
    assert hostname(raw) == expected


def test_dns_rebinding_host_is_refused(client):
    assert client.get("/api/gamification", headers={"Host": "evil.example:8000"}).status_code == 400
    assert client.get("/api/gamification", headers={"Host": "localhost:5173"}).status_code == 200


def test_writes_need_the_client_header(client):
    assert client.post("/api/gamification/seen").status_code == 403, "plain cross-site POST (CSRF)"
    ok = client.post("/api/gamification/seen", headers={"X-GitShield-Client": "web"})
    assert ok.status_code == 204


def test_foreign_origin_is_refused_even_with_header(client):
    res = client.post("/api/gamification/seen",
                      headers={"X-GitShield-Client": "web", "Origin": "https://evil.example"})
    assert res.status_code == 403
    same = client.post("/api/gamification/seen",
                       headers={"X-GitShield-Client": "web", "Origin": "http://localhost:5173"})
    assert same.status_code == 204


def test_reads_do_not_need_the_header(client):
    assert client.get("/api/gamification").status_code == 200


def test_setup_page_when_frontend_is_not_built(tmp_path, monkeypatch):
    import importlib

    from gitshield.web import app as app_module

    monkeypatch.setattr("pathlib.Path.exists", lambda self: False if self.name == "dist" else True)
    reloaded = importlib.reload(app_module)
    try:
        monkeypatch.setattr(reloaded.settings, "db_path", tmp_path / "x.db")
        monkeypatch.setattr(reloaded.settings, "auto_review_interval", 0)
        with TestClient(reloaded.app, base_url="http://127.0.0.1") as c:
            res = c.get("/")
            assert res.status_code == 503 and "npm run build" in res.text
    finally:
        monkeypatch.undo()
        importlib.reload(app_module)
