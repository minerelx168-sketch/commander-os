"""Routine scheduling, execution, delivery and filing."""
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from app import config
    monkeypatch.setattr(config, "MEMORY_DIR", tmp_path)
    import app.store as store
    monkeypatch.setattr(store, "_FILE", tmp_path / "hub_store.json")
    import app.docs as docs
    monkeypatch.setattr(docs, "LOCAL_DIR", tmp_path)
    monkeypatch.setattr(docs, "_META", tmp_path / "_meta.json")
    from app.main import app
    return TestClient(app)


def _at(s: str) -> datetime:
    from app.routines import TZ
    return datetime.fromisoformat(s).replace(tzinfo=TZ)


# ── schedule maths (pure) ──

def test_daily_next_run_rolls_to_tomorrow_once_past():
    from app.routines import next_run
    assert next_run("daily", "09:00", None, _at("2026-07-24T08:00")).hour == 9
    assert next_run("daily", "09:00", None, _at("2026-07-24T08:00")).day == 24
    assert next_run("daily", "09:00", None, _at("2026-07-24T09:30")).day == 25


def test_weekly_picks_the_named_weekday():
    from app.routines import next_run
    # 2026-07-24 is a Friday (weekday 4); ask for Monday (0)
    nxt = next_run("weekly", "07:30", 0, _at("2026-07-24T12:00"))
    assert nxt.weekday() == 0 and nxt.day == 27 and nxt.hour == 7


def test_monthly_clamps_to_the_last_day_of_short_months():
    from app.routines import next_run
    # the 31st in February must not silently skip the month
    nxt = next_run("monthly", "08:00", 31, _at("2026-02-01T00:00"))
    assert nxt.month == 2 and nxt.day == 28


def test_times_are_utc7():
    from app.routines import TZ
    assert TZ.utcoffset(None) == timedelta(hours=7)


# ── API ──

def test_create_validates_and_schedules(client):
    bad = client.post("/api/routines", json={"task": "", "frequency": "daily",
                                             "time": "09:00", "seats": ["cfo"]})
    assert bad.status_code == 400
    assert client.post("/api/routines", json={"task": "x", "frequency": "yearly",
                                              "time": "09:00", "seats": ["cfo"]}).status_code == 400
    assert client.post("/api/routines", json={"task": "x", "frequency": "daily",
                                              "time": "25:00", "seats": ["cfo"]}).status_code == 400
    assert client.post("/api/routines", json={"task": "x", "frequency": "daily",
                                              "time": "09:00", "seats": []}).status_code == 400

    r = client.post("/api/routines", json={"task": "สรุปยอดขาย", "frequency": "daily",
                                           "time": "09:00", "seats": ["cfo", "cmo", "bogus"]})
    assert r.status_code == 200
    j = r.json()
    assert j["seats"] == ["cfo", "cmo"]          # unknown seat dropped
    assert j["next_at"] and j["enabled"] is True
    assert client.get("/api/routines").json()["routines"][0]["id"] == j["id"]


def test_run_asks_only_the_assigned_seats_and_delivers(client):
    r = client.post("/api/routines", json={"task": "เช็คกระแสเงินสด", "frequency": "daily",
                                           "time": "09:00", "seats": ["cfo"]}).json()
    calls = []

    def fake_chat(provider, system, user, **kw):
        calls.append((provider, system, user))
        return {"text": "สถานะ: ปกติ", "provider": provider, "model": "m", "ok": True}

    with patch("app.llm.chat", side_effect=fake_chat), \
         patch("app.telegram.send", return_value={"ok": True, "sent": 1}) as tg:
        run = client.post(f"/api/routines/{r['id']}/run").json()

    assert set(run["results"]) == {"cfo"}            # CMO was not assigned
    assert len(calls) == 1
    assert "งานประจำ" in calls[0][1] and "เช็คกระแสเงินสด" in calls[0][2]
    body = tg.call_args.args[0]
    assert "เช็คกระแสเงินสด" in body and "UTC+7" in body
    assert run["delivery"]["ok"] is True


def test_run_is_filed_into_the_document_library(client):
    r = client.post("/api/routines", json={"task": "รายงานสต็อก", "frequency": "weekly",
                                           "time": "08:00", "day": 0,
                                           "seats": ["coo"]}).json()
    with patch("app.llm.chat", return_value={"text": "สถานะ: ok", "provider": "p",
                                             "model": "m", "ok": True}), \
         patch("app.telegram.send", return_value={"ok": True, "sent": 1}):
        client.post(f"/api/routines/{r['id']}/run")

    docs_j = client.get("/api/docs").json()
    filed = [d for d in docs_j["documents"] if d["source"] == "routine"]
    assert filed and "รายงานสต็อก" in filed[0]["text"]
    # …and therefore reaches the board as evidence
    assert "รายงานสต็อก" in client.get("/api/docs").json()["documents"][0]["text"]


def test_previous_run_is_fed_back_in(client):
    r = client.post("/api/routines", json={"task": "ติดตาม KPI", "frequency": "daily",
                                           "time": "09:00", "seats": ["datalyst"]}).json()
    with patch("app.llm.chat", return_value={"text": "รอบแรก: ยอด 100", "provider": "p",
                                             "model": "m", "ok": True}), \
         patch("app.telegram.send", return_value={"ok": True, "sent": 1}):
        client.post(f"/api/routines/{r['id']}/run")

    seen = {}

    def capture(provider, system, user, **kw):
        seen["user"] = user
        return {"text": "รอบสอง", "provider": provider, "model": "m", "ok": True}

    with patch("app.llm.chat", side_effect=capture), \
         patch("app.telegram.send", return_value={"ok": True, "sent": 1}):
        client.post(f"/api/routines/{r['id']}/run")
    assert "รายงานรอบก่อน" in seen["user"] and "ยอด 100" in seen["user"]


def test_tick_runs_due_routines_and_reschedules(client):
    from app import routines, store
    r = client.post("/api/routines", json={"task": "งานถึงกำหนด", "frequency": "daily",
                                           "time": "09:00", "seats": ["cfo"]}).json()
    store.update_routine(r["id"], next_at=(routines.now() - timedelta(minutes=1)).isoformat())

    with patch("app.llm.chat", return_value={"text": "ok", "provider": "p", "model": "m", "ok": True}), \
         patch("app.telegram.send", return_value={"ok": True, "sent": 1}):
        assert routines.tick() == 1

    after = store.get_routine(r["id"])
    assert datetime.fromisoformat(after["next_at"]) > routines.now()
    assert after["last_at"]


def test_disabled_routine_is_skipped(client):
    from app import routines, store
    r = client.post("/api/routines", json={"task": "พักไว้", "frequency": "daily",
                                           "time": "09:00", "seats": ["cfo"]}).json()
    store.update_routine(r["id"], next_at=(routines.now() - timedelta(minutes=1)).isoformat())
    client.post(f"/api/routines/{r['id']}/toggle", json={"enabled": False})
    with patch("app.llm.chat") as chat:
        assert routines.tick() == 0
    chat.assert_not_called()


def test_delete_removes_routine_and_its_runs(client):
    r = client.post("/api/routines", json={"task": "ลบทิ้ง", "frequency": "daily",
                                           "time": "09:00", "seats": ["cfo"]}).json()
    with patch("app.llm.chat", return_value={"text": "ok", "provider": "p", "model": "m", "ok": True}), \
         patch("app.telegram.send", return_value={"ok": True, "sent": 1}):
        client.post(f"/api/routines/{r['id']}/run")
    assert client.delete(f"/api/routines/{r['id']}").status_code == 200
    assert client.get("/api/routines").json()["routines"] == []
    assert client.get(f"/api/routines/{r['id']}/runs").status_code == 404
    assert client.post(f"/api/routines/{r['id']}/run").status_code == 404


def test_routine_says_so_when_there_is_nothing_to_analyse(client):
    """Three advisors each rediscovering 'no data' wastes a round — and worse,
    invites one of them to invent numbers."""
    from app import docs, routines
    docs.create_project("EmptyCo")
    r = client.post("/api/routines", json={"task": "สรุปยอดขาย", "frequency": "daily",
                                           "time": "09:00", "seats": ["cfo"],
                                           "project": "EmptyCo"}).json()
    seen = {}

    def capture(provider, system, user, **kw):
        seen["user"] = user
        return {"text": "ยังประเมินไม่ได้", "provider": provider, "model": "m", "ok": True}

    with patch("app.llm.chat", side_effect=capture), \
         patch("app.telegram.send", return_value={"ok": True, "sent": 1}):
        routines.run_routine(r)
    assert "ยังไม่มีข้อมูลจากระบบ" in seen["user"]
    assert "ห้ามเดาตัวเลข" in seen["user"]


def test_no_such_warning_once_data_exists(client):
    import httpx
    from app import docs, routines, sources
    docs.create_project("FullCo")
    s = client.post("/api/sources", json={
        "project": "FullCo", "name": "POS", "kind": "pos_rest",
        "url": "https://pos.example.com/x", "auth": "none",
        "data_path": "data.orders"}).json()
    with patch("httpx.get", return_value=httpx.Response(
            200, json={"data": {"orders": [{"sales": 1200}]}},
            request=httpx.Request("GET", "https://x"))):
        client.post(f"/api/sources/{s['id']}/fetch")
    assert sources.live_context(project="FullCo")

    r = client.post("/api/routines", json={"task": "สรุปยอดขาย", "frequency": "daily",
                                           "time": "09:00", "seats": ["cfo"],
                                           "project": "FullCo"}).json()
    seen = {}

    def capture(provider, system, user, **kw):
        seen["user"] = user
        return {"text": "ok", "provider": provider, "model": "m", "ok": True}

    with patch("app.llm.chat", side_effect=capture), \
         patch("app.telegram.send", return_value={"ok": True, "sent": 1}):
        routines.run_routine(r)
    assert "ยังไม่มีข้อมูลจากระบบ" not in seen["user"]
    assert "1200" in seen["user"]


def test_ui_exposes_the_routine_page(client):
    html = client.get("/").text
    for marker in ('data-view="routine"', "view-routine", "loadRoutines", "createRoutine",
                   "rt-seat-menu", "toggleSeatDD", "UTC+7", "Routine"):
        assert marker in html, marker


def test_seat_dropdown_is_not_clipped_by_its_card(client):
    """`.card { overflow:hidden }` silently cut the pop-out menu off after two
    rows, so only the top seats were selectable. The card that holds it must
    opt out, and the menu itself must scroll."""
    html = client.get("/").text
    assert ".card.has-dropdown { overflow: visible; }" in html
    card = html[html.index('<div class="view" id="view-routine"'):html.index("rt-seat-menu")]
    assert 'class="card has-dropdown"' in card, "routine form card does not opt out of clipping"
    menu_css = html[html.index(".dropdown-menu {"):html.index(".dropdown.open")]
    assert "overflow-y: auto" in menu_css and "max-height" in menu_css
