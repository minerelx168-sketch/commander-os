from app.models import Approval, CostEntry, Task


def test_task_crud(db):
    t = Task(created_by="owner", assigned_to="ceo", title="ทดสอบ", description="d")
    db.add(t)
    db.commit()
    db.refresh(t)
    assert t.id is not None
    assert t.status == "pending"


def test_llm_mock_records_cost(db):
    from app.services import llm

    text = llm.complete(
        db, agent="ceo", purpose="ceo_plan", system="s", user="u", task_id=None
    )
    assert "subtasks" in text
    entry = db.query(CostEntry).one()
    assert entry.agent == "ceo"
    assert entry.input_tokens == 500
    assert float(entry.cost_thb) > 0


def test_meta_ads_client_mock():
    from app.services import meta_ads_client as mac

    dash = mac.get_dashboard()
    assert len(dash["campaigns"]) == 2
    recs = mac.get_recommendations()
    assert recs[0]["action"] == "DECREASE_BUDGET"


def test_approval_decide(db):
    from app.services import approval as svc

    a = Approval(agent="cmo", action_type="X", payload={})
    db.add(a)
    db.commit()
    out = svc.decide(db, a.id, "approve")
    assert out.status == "approved"
    assert out.decided_by == "owner"
