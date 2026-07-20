"""Live check: CEO resolves to Claude Fable 5 and a real call succeeds."""
import sys
sys.path.insert(0, ".")

from app.config import get_settings
from app.services.llm import _resolve_model, _extract_text

settings = get_settings()
print(f"llm_mock={settings.llm_mock}")
print(f"anthropic_key_set={bool(settings.anthropic_api_key)} (…{settings.anthropic_api_key[-6:] if settings.anthropic_api_key else ''})")

provider, model = _resolve_model(settings, "ceo")
print(f"CEO resolves to: {provider}:{model}")
assert (provider, model) == ("anthropic", "claude-fable-5"), "CEO not routed to Claude!"

from langchain_anthropic import ChatAnthropic

llm = ChatAnthropic(model=model, api_key=settings.anthropic_api_key, max_tokens=1024)
msg = llm.invoke([("system", "You are the CEO agent of Commander OS. Reply in Thai, one short sentence."),
                  ("user", "ยืนยันว่าคุณคือ CEO ที่รันบน Claude Fable 5")])
text = _extract_text(msg.content)
meta = getattr(msg, "response_metadata", {}) or {}
print(f"model_reported_by_api={meta.get('model') or meta.get('model_name')}")
print(f"CEO_CLAUDE_RESPONSE: {text}")
usage = getattr(msg, "usage_metadata", None) or {}
print(f"tokens in={usage.get('input_tokens')} out={usage.get('output_tokens')}")
print("LIVE CEO CLAUDE CHECK PASSED")
