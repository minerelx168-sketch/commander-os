"""Live voice check: real Edge TTS synth + real Gemini STT round-trip."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services import voice


def main() -> None:
    # 1) TTS: Thai text -> mp3
    mp3 = voice.synthesize("สวัสดีครับ ระบบคอมมานเดอร์พร้อมทำงาน")
    print(f"TTS: {len(mp3)} bytes mp3")
    assert len(mp3) > 5000, "mp3 too small — TTS likely failed"

    # 2) STT: feed that mp3 back to Gemini -> text
    text = voice.transcribe(mp3, "audio/mpeg")
    print(f"STT: {text}")
    assert len(text) > 0

    print("VOICE ROUND-TRIP OK")


if __name__ == "__main__":
    main()
