"""Pipeline: a dashboard over Routine. It owns no records of its own."""
from unittest.mock import patch

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
    import app.routines as routines
    routines._LIVE.clear()
    from app.main import app
    return TestClient(app)


def _routine(client, task="สรุปยอดขายรายวัน", seats=("cfo",), project=None):
    return client.post("/api/routines", json={
        "task": task, "frequency": "daily", "time": "09:00",
        "seats": list(seats), "project": project}).json()


def _run(client, rid, texts=None, ok=True, deliver=True):
    """Run a routine with canned seat replies."""
    def reply(provider, system, user, **kw):
        return {"text": (texts or {}).get(provider, "รายงาน") if isinstance(texts, dict)
                else (texts if texts is not None else "รายงาน"),
                "provider": provider, "model": "m", "ok": ok}
    with patch("app.llm.chat", side_effect=reply), \
         patch("app.telegram.send",
               return_value={"ok": deliver, "sent": 1 if deliver else 0, "message_ids": [1]}):
        return client.post(f"/api/routines/{rid}/run").json()


def test_pipeline_shows_the_routines_page_records(client):
    """The dashboard must read Routine's records, not a copy of its own."""
    r = _routine(client, task="วิเคราะห์พอร์ตสินเชื่อ", seats=("cfo", "coo"))
    j = client.get("/api/pipeline").json()
    assert [x["id"] for x in j["routines"]] == [r["id"]]
    v = j["routines"][0]
    assert v["task"] == "วิเคราะห์พอร์ตสินเชื่อ"
    assert [c["key"] for c in v["seat_cards"]] == ["cfo", "coo"]


def test_pipeline_creates_nothing_of_its_own(client):
    """Every write goes through Routine; Pipeline is read-only by construction."""
    assert client.post("/api/pipeline/routines", json={"name": "x"}).status_code in (404, 405)
    assert client.patch("/api/pipeline/routines/1", json={"name": "x"}).status_code in (404, 405)
    assert client.delete("/api/pipeline/routines/1").status_code in (404, 405)


def test_a_routine_that_never_ran_says_so(client):
    _routine(client)
    v = client.get("/api/pipeline").json()["routines"][0]
    assert v["health"] == "todo" and v["last_run"] is None and v["runs_total"] == 0


def test_health_is_derived_from_the_last_run_not_stored(client):
    """A stored status drifts; yesterday's success must not describe today."""
    r = _routine(client, seats=("cfo", "coo"))
    _run(client, r["id"])
    assert client.get("/api/pipeline").json()["routines"][0]["health"] == "done"

    # now a run where one seat comes back empty. The seat is identified from its
    # own system prompt — two seats can share a provider, so the provider name
    # cannot tell them apart.
    def half(provider, system, user, **kw):
        silent = "COO" in system
        return {"text": "" if silent else "รายงาน", "provider": provider,
                "model": "m", "ok": not silent}

    with patch("app.llm.chat", side_effect=half), \
         patch("app.telegram.send", return_value={"ok": True, "sent": 1, "message_ids": [2]}):
        client.post(f"/api/routines/{r['id']}/run")
    v = client.get("/api/pipeline").json()["routines"][0]
    assert v["health"] == "review", v
    assert v["last_run"]["seats_ok"] == 1 and v["last_run"]["seats_total"] == 2
    cards = {c["key"]: c for c in v["seat_cards"]}
    assert cards["cfo"]["reported"] and not cards["coo"]["reported"]


def test_a_silent_seat_is_shown_not_omitted(client):
    """Silence is the finding — a seat that said nothing must still appear."""
    r = _routine(client, seats=("cfo", "coo"))
    with patch("app.llm.chat", return_value={"text": "", "provider": "p",
                                             "model": "m", "ok": False}), \
         patch("app.telegram.send", return_value={"ok": True, "sent": 1, "message_ids": [3]}):
        client.post(f"/api/routines/{r['id']}/run")
    v = client.get("/api/pipeline").json()["routines"][0]
    assert len(v["seat_cards"]) == 2
    assert all(not c["reported"] and not c["ok"] for c in v["seat_cards"])
    assert v["health"] == "blocked"


def test_each_seat_carries_its_own_latest_word(client):
    r = _routine(client, seats=("cfo", "coo"))
    seats = {}

    def per_seat(provider, system, user, **kw):
        # the seat is identifiable from its own system prompt
        who = "cfo" if "CFO" in system else "coo"
        seats[who] = provider
        return {"text": f"รายงานของ {who.upper()}", "provider": provider,
                "model": "m", "ok": True}

    with patch("app.llm.chat", side_effect=per_seat), \
         patch("app.telegram.send", return_value={"ok": True, "sent": 1, "message_ids": [4]}):
        client.post(f"/api/routines/{r['id']}/run")

    cards = {c["key"]: c for c in client.get("/api/pipeline").json()["routines"][0]["seat_cards"]}
    assert "CFO" in cards["cfo"]["excerpt"] and "COO" in cards["coo"]["excerpt"]


def test_a_failed_telegram_delivery_is_surfaced(client):
    """A report nobody received is not a report."""
    r = _routine(client)
    _run(client, r["id"], deliver=False)
    j = client.get("/api/pipeline").json()
    assert j["routines"][0]["last_run"]["delivered"] is False
    assert j["stats"]["undelivered"] == 1


def test_a_running_routine_is_visible_while_it_runs(client):
    """Otherwise a slow seat is indistinguishable from one that never answered."""
    import threading
    from app import routines
    r = _routine(client, seats=("cfo",))
    seen = threading.Event()
    release = threading.Event()

    def slow(provider, system, user, **kw):
        seen.set()
        release.wait(3)
        return {"text": "ok", "provider": provider, "model": "m", "ok": True}

    with patch("app.llm.chat", side_effect=slow), \
         patch("app.telegram.send", return_value={"ok": True, "sent": 1, "message_ids": [5]}):
        t = threading.Thread(target=lambda: client.post(f"/api/routines/{r['id']}/run"))
        t.start()
        assert seen.wait(3)
        live = client.get("/api/pipeline/live").json()
        assert live["stats"]["running"] == 1
        assert live["live"][0]["routine_id"] == r["id"]
        assert "cfo" in live["live"][0]["pending"]
        release.set()
        t.join(10)

    assert client.get("/api/pipeline/live").json()["stats"]["running"] == 0
    assert not routines.is_running(r["id"])


def test_a_crashed_run_does_not_stay_running_forever(client):
    from app import routines
    r = _routine(client)
    with patch("app.llm.chat", side_effect=RuntimeError("boom")), \
         patch("app.telegram.send", return_value={"ok": True, "sent": 1, "message_ids": [6]}):
        try:
            client.post(f"/api/routines/{r['id']}/run")
        except Exception:  # noqa: BLE001 — the crash is the point
            pass
    assert not routines.is_running(r["id"]), "a phantom run would never clear"


def test_the_dashboard_reads_the_newest_run_not_the_oldest(client):
    """The store returns runs newest-first. Taking the tail showed yesterday's
    report as today's status — the exact drift this page exists to prevent."""
    r = _routine(client, seats=("cfo",))
    _run(client, r["id"], texts="รายงานเก่า")
    _run(client, r["id"], texts="รายงานใหม่")
    v = client.get("/api/pipeline").json()["routines"][0]
    assert "ใหม่" in v["seat_cards"][0]["excerpt"], v["seat_cards"][0]["excerpt"]
    assert v["runs_total"] == 2
    hist = client.get(f"/api/pipeline/routines/{r['id']}").json()["runs"]
    assert "ใหม่" in hist[0]["results"]["cfo"]["text"], "history is not newest-first"


def test_the_page_calls_no_function_that_was_deleted(client):
    """A call to a removed function throws, and the catch in loadState used to
    turn that into "Hub Offline" — a working hub reported as down. Static
    markers never catch it: to a test the page is just a string."""
    import subprocess
    import sys
    from pathlib import Path
    script = Path(__file__).resolve().parents[1] / "scripts" / "check_js_calls.py"
    r = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_a_render_error_does_not_masquerade_as_a_dead_hub(client):
    """Only a transport failure may say Offline."""
    html = client.get("/").text
    assert "e instanceof TypeError" in html, "the catch still reports any error as offline"


def test_the_history_endpoint_returns_every_report(client):
    r = _routine(client)
    for _ in range(3):
        _run(client, r["id"])
    j = client.get(f"/api/pipeline/routines/{r['id']}").json()
    assert len(j["runs"]) == 3
    assert all("health" in run for run in j["runs"])
    assert j["routine"]["runs_total"] == 3
    assert client.get("/api/pipeline/routines/999").status_code == 404


def test_stats_count_what_the_ceo_must_act_on(client):
    good = _routine(client, task="ดี", seats=("cfo",))
    bad = _routine(client, task="เสีย", seats=("cfo",))
    _run(client, good["id"])
    with patch("app.llm.chat", return_value={"text": "", "provider": "p",
                                             "model": "m", "ok": False}), \
         patch("app.telegram.send", return_value={"ok": False, "sent": 0, "message_ids": []}):
        client.post(f"/api/routines/{bad['id']}/run")

    s = client.get("/api/pipeline").json()["stats"]
    assert s["routines"] == 2 and s["done"] == 1 and s["blocked"] == 1
    assert s["undelivered"] == 1 and s["seats_silent"] == 1


def test_the_shared_state_call_carries_the_same_counters(client):
    """The nav badge and the page must never disagree."""
    r = _routine(client)
    _run(client, r["id"])
    state = client.get("/api/state").json()["pipeline"]
    page = client.get("/api/pipeline").json()["stats"]
    assert state == page
