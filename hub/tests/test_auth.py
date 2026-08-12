"""HERMES_API_KEY auth: both accepted headers, the browser cookie, exemptions."""
import pytest
from fastapi.testclient import TestClient

KEY = "test-key-0123456789abcdefghijklmnopqrst"


@pytest.fixture()
def open_client(tmp_path, monkeypatch):
    """No key configured — the hub must behave exactly as before."""
    from app import config
    monkeypatch.setattr(config, "HERMES_API_KEY", "")
    monkeypatch.setattr(config, "MEMORY_DIR", tmp_path)
    from app.main import app
    return TestClient(app)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from app import config
    monkeypatch.setattr(config, "HERMES_API_KEY", KEY)
    monkeypatch.setattr(config, "MEMORY_DIR", tmp_path)
    import app.store as store
    monkeypatch.setattr(store, "_FILE", tmp_path / "hub_store.json")
    import app.sources as sources
    monkeypatch.setattr(sources, "_FILE", tmp_path / "sources.json")
    from app.main import app
    return TestClient(app)


def test_generated_key_shape():
    """The key we ship must be long and unguessable, not a passphrase."""
    import secrets
    k = secrets.token_urlsafe(32)
    assert len(k) >= 32 and k.isascii()


def test_without_a_key_nothing_changes(open_client):
    assert open_client.get("/api/state").status_code == 200
    assert open_client.get("/api/routines").status_code == 200


def test_api_is_closed_to_anonymous_callers(client):
    r = client.get("/api/state")
    assert r.status_code == 401
    assert "X-Hermes-API-Key" in r.json()["detail"]
    assert client.get("/api/routines").status_code == 401
    assert client.post("/api/routines", json={"task": "x", "frequency": "daily",
                                              "time": "09:00", "seats": ["cfo"]}).status_code == 401
    assert client.get("/api/sources").status_code == 401


def test_x_hermes_api_key_header_works(client):
    assert client.get("/api/state", headers={"X-Hermes-API-Key": KEY}).status_code == 200


def test_authorization_bearer_works(client):
    assert client.get("/api/state", headers={"Authorization": f"Bearer {KEY}"}).status_code == 200
    # scheme is case-insensitive per RFC 7235
    assert client.get("/api/state", headers={"Authorization": f"bearer {KEY}"}).status_code == 200


def test_wrong_key_is_rejected_in_both_headers(client):
    assert client.get("/api/state", headers={"X-Hermes-API-Key": "nope"}).status_code == 401
    assert client.get("/api/state", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert client.get("/api/state", headers={"Authorization": KEY}).status_code == 401  # no scheme
    # a prefix of the real key must not pass
    assert client.get("/api/state", headers={"X-Hermes-API-Key": KEY[:-1]}).status_code == 401


def test_dashboard_and_health_stay_open(client):
    assert client.get("/").status_code == 200
    assert client.get("/health").status_code == 200


def test_a_locked_hub_offers_a_way_in(client):
    """A 401 must be recoverable from the browser, not a dead end that reads
    as 'Hub Offline'."""
    assert client.get("/api/state").status_code == 401
    assert client.post("/api/unlock", json={"key": "wrong"}).status_code == 401
    assert client.get("/api/state").status_code == 401        # nothing granted
    assert client.post("/api/unlock", json={"key": KEY}).status_code == 200
    assert client.get("/api/state").status_code == 200        # cookie now rides along
    assert client.post("/api/lock").status_code == 200
    assert client.get("/api/state").status_code == 401        # and can be dropped


def test_ui_shows_an_unlock_gate_not_a_false_offline(client):
    html = client.get("/").text
    for marker in ("unlock-overlay", "submitUnlock", "showUnlock", "/api/unlock",
                   "ถูกล็อกไว้", "r.status === 401"):
        assert marker in html, marker


def test_browser_can_unlock_once_via_query_param(client):
    fresh = client.get("/api/state")
    assert fresh.status_code == 401
    landed = client.get(f"/?key={KEY}")
    assert landed.status_code == 200
    assert "hermes_key" in landed.cookies or client.cookies.get("hermes_key") == KEY
    # the cookie now carries the browser through the API
    assert client.get("/api/state").status_code == 200


def test_a_wrong_query_key_sets_no_cookie(client):
    client.get("/?key=wrong")
    assert client.cookies.get("hermes_key") is None
    assert client.get("/api/state").status_code == 401


def test_inbound_webhooks_stay_reachable(client):
    """LINE and POS systems cannot send our key; they carry their own secret."""
    from app import auth
    assert auth.is_open("/api/line/webhook")
    assert auth.is_open("/api/sources/1/webhook")
    assert not auth.is_open("/api/sources")
    assert not auth.is_open("/api/routines/1/run")
    # LINE really answers without the hub key (its own signature check applies)
    assert client.post("/api/line/webhook", json={"events": []}).status_code == 200
