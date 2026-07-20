"""Voice service — STT via Gemini multimodal (same key as the brain), TTS via Edge TTS.

MOCK mode (llm_mock=1): canned transcript + tiny fake mp3, so tests need no network.
"""
import asyncio
import base64

import httpx

from ..config import get_settings

THAI_VOICE = "th-TH-NiwatNeural"

MOCK_TRANSCRIPT = "วิเคราะห์แคมเปญวันนี้ มีอะไรต้องปรับไหม"
MOCK_MP3 = b"ID3\x03\x00\x00\x00\x00\x00\x00"  # header-only stub


def transcribe(audio: bytes, mime: str = "audio/webm") -> str:
    """Speech-to-text through Gemini generateContent (audio part + instruction)."""
    s = get_settings()
    if s.llm_mock:
        return MOCK_TRANSCRIPT

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{s.llm_model}:generateContent?key={s.google_api_key}"
    )
    body = {
        "contents": [{
            "parts": [
                {"inline_data": {"mime_type": mime, "data": base64.b64encode(audio).decode()}},
                {"text": "ถอดเสียงเป็นข้อความ (ไทยหรืออังกฤษตามที่พูด) ตอบเฉพาะข้อความที่ถอดได้เท่านั้น"},
            ]
        }]
    }
    r = httpx.post(url, json=body, timeout=60)
    r.raise_for_status()
    return r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()


async def synthesize_async(text: str, voice: str = THAI_VOICE) -> bytes:
    import edge_tts

    chunks = []
    async for chunk in edge_tts.Communicate(text, voice).stream():
        if chunk["type"] == "audio":
            chunks.append(chunk["data"])
    return b"".join(chunks)


def synthesize(text: str, voice: str = THAI_VOICE) -> bytes:
    """Text-to-speech mp3 bytes (Thai voice)."""
    if get_settings().llm_mock:
        return MOCK_MP3
    return asyncio.run(synthesize_async(text, voice))
