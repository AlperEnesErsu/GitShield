import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

TOKEN = "s3cret-token-value"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from gitshield.web import app as app_module
    from gitshield.web.config import settings

    monkeypatch.setattr(settings, "db_path", tmp_path / "auth.db")
    monkeypatch.setattr(settings, "auto_review_interval", 0)
    monkeypatch.setattr(settings, "api_token", TOKEN)
    with TestClient(app_module.app, base_url="http://127.0.0.1", headers={"X-GitShield-Client": "test"}) as c:
        yield c


def test_api_requires_the_token_for_every_method(client):
    assert client.get("/api/gamification").status_code == 401
    assert client.put("/api/gamification/goal", json={"goal": 3}).status_code == 401
    assert client.post("/api/gamification/seen").status_code == 401


def test_bearer_header_and_cookie_are_accepted(client):
    assert client.get("/api/gamification", headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 200
    assert client.get("/api/gamification", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/api/gamification", headers={"Authorization": f"Basic {TOKEN}"}).status_code == 401
    client.cookies.set("gitshield_token", TOKEN)
    assert client.get("/api/gamification").status_code == 200


def test_visiting_with_the_token_sets_a_strict_cookie_and_hides_it(client):
    res = client.get(f"/?token={TOKEN}", follow_redirects=False)
    assert res.status_code == 302 and res.headers["location"] == "/"
    cookie = res.headers["set-cookie"].lower()
    assert f"gitshield_token={TOKEN}".lower() in cookie
    assert "httponly" in cookie and "samesite=strict" in cookie

    bad = client.get("/?token=nope", follow_redirects=False)
    assert bad.status_code == 401 and "set-cookie" not in bad.headers


def test_ui_pages_are_not_behind_the_token(client):
    assert client.get("/", follow_redirects=False).status_code != 401


def test_no_token_configured_means_no_check(client, monkeypatch):
    from gitshield.web.config import settings

    monkeypatch.setattr(settings, "api_token", "")
    assert client.get("/api/gamification").status_code == 200
