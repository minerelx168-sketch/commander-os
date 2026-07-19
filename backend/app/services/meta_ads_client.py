"""HTTP client for the meta-ads-agent backend (CMO department tools)."""
import httpx

from ..config import get_settings

MOCK_DASHBOARD = {
    "campaigns": [
        {"id": "camp_A", "name": "Campaign A — Lead Gen", "status": "ACTIVE",
         "spend": 4200.0, "cpa": 138.0, "roas": 2.1},
        {"id": "camp_B", "name": "Campaign B — Retargeting", "status": "ACTIVE",
         "spend": 1800.0, "cpa": 92.0, "roas": 3.4},
    ],
    "period": "last_7d",
}

MOCK_RECOMMENDATIONS = [
    {
        "id": 101,
        "action": "DECREASE_BUDGET",
        "target": "camp_A",
        "params": {"percent": 20},
        "reason": "CPA สูงกว่าเป้า 15% ต่อเนื่อง 3 วัน",
        "status": "PENDING",
    }
]


def get_dashboard() -> dict:
    s = get_settings()
    if s.meta_agent_mock:
        return MOCK_DASHBOARD
    r = httpx.get(f"{s.meta_agent_url}/api/dashboard", timeout=30)
    r.raise_for_status()
    return r.json()


def get_recommendations(status: str = "PENDING") -> list[dict]:
    s = get_settings()
    if s.meta_agent_mock:
        return [x for x in MOCK_RECOMMENDATIONS if x["status"] == status]
    r = httpx.get(
        f"{s.meta_agent_url}/api/recommendations",
        params={"status": status},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def run_pipeline() -> dict:
    s = get_settings()
    if s.meta_agent_mock:
        return {"status": "ok", "new_recommendations": 1}
    r = httpx.post(f"{s.meta_agent_url}/api/pipeline/run", timeout=120)
    r.raise_for_status()
    return r.json()
