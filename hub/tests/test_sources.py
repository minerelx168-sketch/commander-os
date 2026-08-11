"""Per-project POS / back-office API connectors."""
import json
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from app import config
    monkeypatch.setattr(config, "MEMORY_DIR", tmp_path)
    import app.store as store
    monkeypatch.setattr(store, "_FILE", tmp_path / "hub_store.json")
    import app.sources as sources
    monkeypatch.setattr(sources, "_FILE", tmp_path / "sources.json")
    import app.docs as docs
    monkeypatch.setattr(docs, "LOCAL_DIR", tmp_path)
    monkeypatch.setattr(docs, "_META", tmp_path / "_meta.json")
    from app.main import app
    return TestClient(app)


def _add(client, **over):
    body = {"project": "FlowerVending", "name": "POS เอกมัย", "kind": "pos_rest",
            "url": "https://pos.example.com/api/sales", "auth": "bearer",
            "secret": "s3cr3t", "data_path": "data.orders"} | over
    return client.post("/api/sources", json=body)


def test_secret_is_stored_but_never_returned(client):
    j = _add(client).json()
    assert "secret" not in j and j["has_secret"] is True
    listed = client.get("/api/sources").json()["sources"][0]
    assert "secret" not in listed and listed["has_secret"] is True
    # …but the server still holds it for the actual call
    from app import sources
    assert sources.get_source(j["id"])["secret"] == "s3cr3t"


def test_validation_rejects_junk(client):
    assert _add(client, project=" ").status_code == 400
    assert _add(client, name="").status_code == 400
    assert _add(client, kind="carrier-pigeon").status_code == 400
    assert _add(client, auth="vibes").status_code == 400
    assert _add(client, url="pos.example.com").status_code == 400        # no scheme
    assert _add(client, kind="webhook", url="").status_code == 200       # webhook needs no URL


def test_sources_are_scoped_per_project(client):
    _add(client, project="FlowerVending", name="POS ดอกไม้")
    _add(client, project="YourFin", name="ระบบสินเชื่อ")
    assert len(client.get("/api/sources").json()["sources"]) == 2
    only = client.get("/api/sources?project=YourFin").json()["sources"]
    assert [s["name"] for s in only] == ["ระบบสินเชื่อ"]


def test_fetch_authenticates_and_digs_out_the_rows(client):
    sid = _add(client).json()["id"]
    seen = {}

    def fake_get(url, headers=None, params=None, **kw):
        seen["url"], seen["headers"] = url, headers
        return httpx.Response(200, json={"data": {"orders": [
            {"id": 1, "total": 250}, {"id": 2, "total": 400}]}},
            request=httpx.Request("GET", url))

    with patch("httpx.get", side_effect=fake_get):
        j = client.post(f"/api/sources/{sid}/fetch").json()

    assert seen["headers"]["Authorization"] == "Bearer s3cr3t"
    assert j["ok"] and j["rows"] == 2 and j["preview"][0]["total"] == 250


def test_header_and_query_auth_modes(client):
    hid = _add(client, auth="header", header_name="X-API-Key", data_path="").json()["id"]
    qid = _add(client, auth="query", header_name="api_key", data_path="").json()["id"]
    seen = []

    def fake_get(url, headers=None, params=None, **kw):
        seen.append((headers, params))
        return httpx.Response(200, json=[{"a": 1}], request=httpx.Request("GET", url))

    with patch("httpx.get", side_effect=fake_get):
        client.post(f"/api/sources/{hid}/fetch")
        client.post(f"/api/sources/{qid}/fetch")
    assert seen[0][0]["X-API-Key"] == "s3cr3t"
    assert seen[1][1]["api_key"] == "s3cr3t"


def test_dead_pos_is_reported_not_swallowed(client):
    sid = _add(client).json()["id"]
    with patch("httpx.get", side_effect=httpx.ConnectError("refused")):
        j = client.post(f"/api/sources/{sid}/fetch").json()
    assert j["ok"] is False and "ConnectError" in j["error"]
    s = client.get("/api/sources").json()["sources"][0]
    assert s["last_status"].startswith("error:")


def test_csv_source_is_parsed(client):
    sid = _add(client, kind="sheet_csv", url="https://docs.google.com/x/pub?output=csv",
               auth="none", secret="").json()["id"]
    csv = "date,sales\n2026-08-01,1200\n2026-08-02,1450\n"
    with patch("httpx.get", return_value=httpx.Response(
            200, text=csv, headers={"content-type": "text/csv"},
            request=httpx.Request("GET", "https://x"))):
        j = client.post(f"/api/sources/{sid}/fetch").json()
    assert j["rows"] == 2 and j["preview"][0]["sales"] == "1200"


def test_webhook_push_requires_the_key(client):
    sid = _add(client, kind="webhook", url="", secret="hook-key").json()["id"]
    bad = client.post(f"/api/sources/{sid}/webhook", json=[{"x": 1}])
    assert bad.status_code == 401
    ok = client.post(f"/api/sources/{sid}/webhook", json=[{"sale": 100}, {"sale": 200}],
                     headers={"X-Source-Key": "hook-key"})
    assert ok.status_code == 200 and ok.json()["rows"] == 2


def test_live_data_reaches_the_advisors(client):
    from app import sources
    sid = _add(client).json()["id"]
    with patch("httpx.get", return_value=httpx.Response(
            200, json={"data": {"orders": [{"sku": "rose", "qty": 12}]}},
            request=httpx.Request("GET", "https://x"))):
        client.post(f"/api/sources/{sid}/fetch")

    ctx = sources.live_context(project="FlowerVending")
    assert "POS เอกมัย" in ctx and "rose" in ctx
    assert sources.live_context(project="YourFin") == ""     # scoped, not leaked

    # a paused source stops feeding the board
    client.post(f"/api/sources/{sid}/toggle", json={"enabled": False})
    assert sources.live_context(project="FlowerVending") == ""


def test_routine_prompt_includes_live_data(client):
    from app import routines
    sid = _add(client, project="FlowerVending").json()["id"]
    with patch("httpx.get", return_value=httpx.Response(
            200, json={"data": {"orders": [{"sku": "tulip", "qty": 7}]}},
            request=httpx.Request("GET", "https://x"))):
        client.post(f"/api/sources/{sid}/fetch")

    r = client.post("/api/routines", json={"task": "เช็คสต็อก", "frequency": "daily",
                                           "time": "09:00", "seats": ["coo"],
                                           "project": "FlowerVending"}).json()
    seen = {}

    def capture(provider, system, user, **kw):
        seen["user"] = user
        return {"text": "ok", "provider": provider, "model": "m", "ok": True}

    with patch("app.llm.chat", side_effect=capture), \
         patch("app.telegram.send", return_value={"ok": True, "sent": 1}):
        routines.run_routine(r)
    assert "ข้อมูลสดจากระบบ POS" in seen["user"] and "tulip" in seen["user"]


def test_delete_removes_it(client):
    sid = _add(client).json()["id"]
    assert client.delete(f"/api/sources/{sid}").status_code == 200
    assert client.get("/api/sources").json()["sources"] == []
    assert client.post(f"/api/sources/{sid}/fetch").status_code == 404


def test_ui_exposes_connector_and_seat_dropdown(client):
    html = client.get("/").text
    for marker in ("src-project", "src-kind", "addSource", "fetchSource", "copyHook",
                   "API Connector", "conn-scope", "rt-seat-menu", "toggleSeatDD",
                   "renderSeatSummary", "rt-textarea"):
        assert marker in html, marker


def test_a_project_never_sees_another_project_data(client):
    """The isolation the UI promises must hold in the data layer."""
    from app import sources
    flower = _add(client, project="FlowerVending", name="POS ดอกไม้").json()["id"]
    fin = _add(client, project="YourFin", name="ระบบสินเชื่อ").json()["id"]

    def payload(tag):
        return httpx.Response(200, json={"data": {"orders": [{"tag": tag}]}},
                              request=httpx.Request("GET", "https://x"))

    with patch("httpx.get", return_value=payload("FLOWER-ONLY")):
        client.post(f"/api/sources/{flower}/fetch")
    with patch("httpx.get", return_value=payload("FIN-ONLY")):
        client.post(f"/api/sources/{fin}/fetch")

    flower_ctx = sources.live_context(project="FlowerVending")
    fin_ctx = sources.live_context(project="YourFin")
    assert "FLOWER-ONLY" in flower_ctx and "FIN-ONLY" not in flower_ctx
    assert "FIN-ONLY" in fin_ctx and "FLOWER-ONLY" not in fin_ctx
