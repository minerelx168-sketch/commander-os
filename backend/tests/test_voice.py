"""Voice API tests (MOCK mode: canned transcript + stub mp3)."""


def test_voice_command_transcribes_and_dispatches(client, db):
    r = client.post(
        "/api/voice/command",
        files={"audio": ("cmd.webm", b"fake-audio-bytes", "audio/webm")},
    )
    assert r.status_code == 200
    j = r.json()
    assert "วิเคราะห์แคมเปญ" in j["transcript"]
    assert j["task_id"] > 0

    # dispatched like a typed command -> task exists
    t = client.get(f"/api/tasks/{j['task_id']}").json()
    assert t["status"] in ("in_progress", "waiting_approval", "done")


def test_tts_returns_audio(client):
    r = client.get("/api/voice/tts", params={"text": "ระบบพร้อม"})
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/mpeg"
    assert len(r.content) > 0
