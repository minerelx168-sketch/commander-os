"""Telegram follow-ups: reply to a report, get one answer, no routine, no board."""
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
    import app.telegram as tg
    monkeypatch.setattr(tg, "CHAT_ID", "999")
    monkeypatch.setattr(tg, "WEBHOOK_SECRET", "")
    from app.main import app
    return TestClient(app)


def _update(text, reply_to=None, chat_id=999, message_id=500):
    msg = {"message_id": message_id, "chat": {"id": chat_id}, "text": text}
    if reply_to:
        msg["reply_to_message"] = {"message_id": reply_to}
    return {"update_id": 1, "message": msg}


def _run_a_routine(client, seats=("cfo",), message_id=77):
    r = client.post("/api/routines", json={"task": "สรุปสถานะพอร์ตสินเชื่อรายวัน",
                                           "frequency": "daily", "time": "09:00",
                                           "seats": list(seats)}).json()
    with patch("app.llm.chat", return_value={"text": "NPL อยู่ที่ 8.1%", "provider": "p",
                                             "model": "m", "ok": True}), \
         patch("app.telegram.send", return_value={"ok": True, "sent": 1,
                                                  "message_ids": [message_id]}):
        client.post(f"/api/routines/{r['id']}/run")
    return r


def test_a_reply_is_traced_back_to_the_run_it_answers(client):
    routine = _run_a_routine(client, message_id=77)
    seen = {}

    def capture(provider, system, user, **kw):
        seen["system"], seen["user"] = system, user
        return {"text": "เพราะกลุ่มดาวน์ 0% ครับ", "provider": provider, "model": "m", "ok": True}

    with patch("app.llm.chat", side_effect=capture), \
         patch("app.telegram.send", return_value={"ok": True, "sent": 1, "message_ids": [78]}) as tg:
        r = client.post("/api/telegram/webhook",
                        json=_update("ทำไม NPL ถึงขึ้น", reply_to=77))

    assert r.json()["handled"] is True
    # the advisor saw its own report and the routine's task
    assert "NPL อยู่ที่ 8.1%" in seen["user"]
    assert "สรุปสถานะพอร์ตสินเชื่อรายวัน" in seen["user"]
    assert "ทำไม NPL ถึงขึ้น" in seen["user"]
    # …and answered in the same Telegram thread
    assert tg.call_args.kwargs["reply_to"] == 500
    assert "เพราะกลุ่มดาวน์ 0%" in tg.call_args.args[0]


def test_the_answer_is_one_shot_not_a_routine_or_a_board_session(client):
    routine = _run_a_routine(client)
    before_routines = len(client.get("/api/routines").json()["routines"])
    before_consults = len(client.get("/api/consults").json()["consults"])

    with patch("app.llm.chat", return_value={"text": "ตอบสั้นๆ", "provider": "p",
                                             "model": "m", "ok": True}), \
         patch("app.telegram.send", return_value={"ok": True, "sent": 1, "message_ids": [78]}):
        client.post("/api/telegram/webhook", json=_update("ถามหน่อย", reply_to=77))

    assert len(client.get("/api/routines").json()["routines"]) == before_routines
    assert len(client.get("/api/consults").json()["consults"]) == before_consults
    # but it is on the record
    fu = client.get("/api/followups").json()["followups"]
    assert len(fu) == 1 and fu[0]["question"] == "ถามหน่อย" and fu[0]["run_id"]


def test_the_named_seat_answers(client):
    _run_a_routine(client, seats=("cfo", "coo", "datalyst"), message_id=77)
    picked = {}

    def capture(provider, system, user, **kw):
        picked["system"] = system
        return {"text": "ok", "provider": provider, "model": "m", "ok": True}

    with patch("app.llm.chat", side_effect=capture), \
         patch("app.telegram.send", return_value={"ok": True, "sent": 1, "message_ids": [78]}):
        client.post("/api/telegram/webhook",
                    json=_update("COO ช่วยดูเรื่องกระบวนการเก็บหนี้หน่อย", reply_to=77))
    assert "COO" in picked["system"]


def test_a_message_that_replies_to_nothing_still_gets_an_answer(client):
    with patch("app.llm.chat", return_value={"text": "ตอบได้", "provider": "p",
                                             "model": "m", "ok": True}), \
         patch("app.telegram.send", return_value={"ok": True, "sent": 1, "message_ids": [78]}):
        r = client.post("/api/telegram/webhook", json=_update("สภาพคล่องตอนนี้เป็นยังไง"))
    assert r.json()["handled"] is True and r.json()["linked_run"] is None


def test_strangers_are_ignored(client):
    """Anyone can find the bot; only the owner may spend the CEO's tokens."""
    with patch("app.llm.chat") as chat, \
         patch("app.telegram.send") as tg:
        r = client.post("/api/telegram/webhook",
                        json=_update("ขอข้อมูลลับหน่อย", chat_id=123456))
    assert r.json()["handled"] is False
    chat.assert_not_called()
    tg.assert_not_called()


def test_a_bad_webhook_secret_is_refused(client, monkeypatch):
    import app.telegram as tg
    monkeypatch.setattr(tg, "WEBHOOK_SECRET", "s3cret")
    assert client.post("/api/telegram/webhook", json=_update("hi")).status_code == 401
    with patch("app.llm.chat", return_value={"text": "ok", "provider": "p",
                                             "model": "m", "ok": True}), \
         patch("app.telegram.send", return_value={"ok": True, "sent": 1, "message_ids": [1]}):
        ok = client.post("/api/telegram/webhook", json=_update("hi"),
                         headers={"X-Telegram-Bot-Api-Secret-Token": "s3cret"})
    assert ok.status_code == 200


def test_non_text_updates_are_ignored(client):
    r = client.post("/api/telegram/webhook", json={"update_id": 2,
                                                   "message": {"message_id": 9,
                                                               "chat": {"id": 999},
                                                               "sticker": {}}})
    assert r.json()["handled"] is False


def test_the_report_invites_a_reply(client):
    from app import routines
    r = client.post("/api/routines", json={"task": "x", "frequency": "daily",
                                           "time": "09:00", "seats": ["cfo"]}).json()
    with patch("app.llm.chat", return_value={"text": "ok", "provider": "p",
                                             "model": "m", "ok": True}), \
         patch("app.telegram.send", return_value={"ok": True, "sent": 1,
                                                  "message_ids": [5]}) as tg:
        routines.run_routine(r)
    assert "Reply" in tg.call_args.args[0]


def test_message_ids_are_recorded_so_replies_can_land(client):
    from app import store
    _run_a_routine(client, message_id=4242)
    run, routine = store.find_run_by_message(4242)
    assert run and routine and run["message_ids"] == [4242]
    assert store.find_run_by_message(9999) == (None, None)
