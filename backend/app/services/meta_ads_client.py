"""HTTP client for the meta-ads-agent backend (CMO department tools).

Real endpoints (meta-ads-agent :8000):
  GET  /api/metrics/summary                   -> dashboard summary
  GET  /api/recommendations?status_filter=PENDING
  POST /api/recommendations/{id}/approve|reject
  POST /api/ingest/run , POST /api/agent/run  -> refresh data + generate recos
"""
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


def _base() -> str:
    return get_settings().meta_agent_url.rstrip("/")


def get_dashboard() -> dict:
    if get_settings().meta_agent_mock:
        return MOCK_DASHBOARD
    r = httpx.get(f"{_base()}/api/metrics/summary", timeout=30)
    r.raise_for_status()
    return r.json()


def get_recommendations(status: str = "PENDING") -> list[dict]:
    if get_settings().meta_agent_mock:
        return [x for x in MOCK_RECOMMENDATIONS if x["status"] == status]
    r = httpx.get(
        f"{_base()}/api/recommendations",
        params={"status_filter": status},
        timeout=30,
    )
    r.raise_for_status()
    # normalize to the shape the CMO node expects
    return [
        {
            "id": rec["id"],
            "action": rec["action_type"],
            "target": rec.get("entity_name") or rec["entity_meta_id"],
            "params": {
                "current": rec.get("current_value"),
                "proposed": rec.get("proposed_value"),
            },
            "reason": rec["justification"],
            "status": rec["status"],
        }
        for rec in r.json()
    ]


def decide_recommendation(reco_id: int, decision: str) -> dict:
    """Forward owner's decision to meta-ads-agent, which executes via Meta API."""
    if get_settings().meta_agent_mock:
        return {"id": reco_id, "status": "APPROVED" if decision == "approve" else "REJECTED"}
    action = "approve" if decision == "approve" else "reject"
    r = httpx.post(f"{_base()}/api/recommendations/{reco_id}/{action}", timeout=60)
    r.raise_for_status()
    return r.json()


def run_pipeline() -> dict:
    """Refresh metrics + let the meta-ads agent generate new recommendations."""
    if get_settings().meta_agent_mock:
        return {"status": "ok", "new_recommendations": 1}
    out = {}
    r = httpx.post(f"{_base()}/api/ingest/run", timeout=120)
    r.raise_for_status()
    out["ingest"] = r.json()
    r = httpx.post(f"{_base()}/api/agent/run", timeout=120)
    r.raise_for_status()
    out["agent"] = r.json()
    return out
