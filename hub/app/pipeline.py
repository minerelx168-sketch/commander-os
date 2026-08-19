"""Pipeline — recurring work, one work tree per routine.

The Boardroom answers a hard question once. This is the other half: the work
that comes back every week and has to be owned by somebody, done to a standard,
and corrected when it comes back wrong.

Three things it is built around:

**A routine is a tree, not a queue.** Each routine carries its own project,
owner and tasks, and nothing is shared between them — a lane can be re-run,
branched or deleted without touching another. A task can fork at any run into a
sibling, so two answers to the same task can sit side by side while the CEO
decides which he wants, exactly like the Boardroom's branch.

**A comment is a correction, not a note.** When a reply is not what the CEO
asked for, he comments; the task runs again with that comment quoted as a
binding instruction and the rejected answer attached. Nothing is overwritten:
run 1 stays next to run 2, so it is always visible what was said, what was
demanded, and what actually changed.

**The reasoning is part of the deliverable.** Every run returns not just an
answer but how it was reached — the restated problem, the steps, the
assumptions it had to invent, the evidence it actually used, what it still does
not know, what would make it wrong, and what changed since the last run. A hub
that shows only conclusions asks the CEO to trust a model he cannot inspect;
`inputs` on each run additionally records exactly what went into the prompt, so
"the AI ignored my document" is a checkable claim rather than a suspicion.
"""
import logging
import re
import threading
import time
from datetime import datetime, timezone

from . import config, depts, docs, jsonx, llm, memory, store

log = logging.getLogger("hub.pipeline")

# Room for a full deliverable plus its reasoning trace. Thai burns ~3x the
# tokens of English and the trace is not free; at the 2048 default the answer
# field is what gets cut.
MAX_TOKENS = 8192

# Split in two on purpose: the persona half carries {placeholders} and is
# formatted per seat, the schema half is full of JSON braces and must reach the
# model untouched. Running .format() over the schema would read `{"answer": ...}`
# as a field name and raise.
TASK_PERSONA = (
    "คุณคือ {name} ({role}) — เจ้าของงานสายนี้ในบริษัทของ CEO ไม่ใช่ผู้ช่วยที่รอสั่ง\n"
    "ขอบเขตของคุณ: {lane}\n"
    "กฎเหล็ก: {guard}\n"
    "\n"
    "งานนี้เป็น 'งานประจำ' ไม่ใช่คำถามครั้งเดียว — สิ่งที่คุณส่งต้องเอาไปใช้ต่อได้ทันที "
    "และต้องบอกได้ว่าคิดมาอย่างไร ไม่ใช่แค่สรุปผล\n"
    "\n"
    "กฎเรื่องความซื่อสัตย์ (สำคัญที่สุด):\n"
    "- อ้างได้เฉพาะสิ่งที่อยู่ในข้อมูลที่ให้มาเท่านั้น ถ้าไม่มีข้อมูลรองรับ ให้เขียนว่า (ไม่มีข้อมูล) "
    "แล้วบอกว่าต้องได้อะไรมาถึงจะตอบได้ — การเดาแล้วเขียนให้ดูน่าเชื่อถือว่าผิดร้ายแรงกว่าการบอกว่าไม่รู้\n"
    "- สิ่งที่คุณประมาณเอง ต้องอยู่ใน assumptions ห้ามปนไปกับข้อเท็จจริง\n"
    "- ถ้ามีคำสั่งแก้ไขจาก CEO ต้องทำตามให้ครบทุกข้อ และบอกใน changed_from_last "
    "ว่าแก้อะไรไปบ้าง ถ้าข้อไหนทำตามไม่ได้ ต้องบอกเหตุผลตรงๆ ห้ามเงียบ\n"
    "- ถ้า CEO ชี้ว่า **ขั้นตอนคิดขั้นไหนผิด** นั่นคือทางที่ถูกปิดแล้ว ห้ามเดินซ้ำ "
    "ต้องคิดจากจุดนั้นใหม่ตามที่เขาบอก แล้วรายงานใน fix_responses ทีละจุด — "
    "การตอบผลลัพธ์เดิมโดยเขียนใหม่ให้ดูต่าง ถือว่าไม่ได้แก้\n"
    "\n"
)

TASK_SCHEMA = (
    "ตอบเป็น JSON ล้วนเท่านั้น ห้ามมีข้อความอื่นนอก JSON:\n"
    "{\n"
    '  "understanding": "โจทย์ที่คุณเข้าใจ พูดใหม่ด้วยคำของคุณเอง 1-2 ประโยค",\n'
    '  "steps": [{"step": "ขั้นที่คิด", "why": "ทำไมต้องคิดขั้นนี้", "found": "ได้อะไรจากขั้นนี้"}],\n'
    '  "assumptions": ["สมมติฐานที่คุณตั้งเอง เพราะไม่มีข้อมูลจริงรองรับ"],\n'
    '  "evidence_used": ["อ้างอะไรบ้าง ระบุชื่อเอกสาร/มติเก่า/คอมเมนต์ ถ้าไม่ได้อ้างอะไรเลยให้ใส่ (ไม่มีหลักฐาน)"],\n'
    '  "unknowns": ["สิ่งที่ยังไม่รู้ และทำให้คำตอบนี้อาจผิด"],\n'
    '  "answer": "ผลงานจริงที่ส่งมอบ เขียนให้หยิบไปใช้ได้ทันที",\n'
    '  "next_actions": [{"action": "สิ่งที่ต้องทำต่อ", "owner": "ใครทำ", "due": "ภายในเมื่อไร"}],\n'
    '  "confidence": 70,\n'
    '  "self_check": "ถ้าคำตอบนี้ผิด จะผิดตรงไหนก่อน และจะรู้ได้อย่างไร",\n'
    '  "changed_from_last": "รอบนี้ต่างจากรอบก่อนตรงไหน (ถ้าเป็นรอบแรกให้ใส่ค่าว่าง)",\n'
    '  "fix_responses": [{"node": "รหัสจุดที่ CEO ชี้ว่าผิด ตามที่ให้มาเป๊ะๆ",\n'
    '                     "what_i_did": "คุณแก้ตามอย่างไร",\n'
    '                     "disagree": "ถ้าทำตามไม่ได้ ให้บอกเหตุผลตรงนี้ ถ้าทำตามได้ให้เว้นว่าง"}]\n'
    "}\n"
    "confidence เป็นตัวเลข 0-100 ห้ามใส่เครื่องหมาย %\n"
    "fix_responses ต้องมีครบทุกจุดที่ CEO ชี้ว่าผิด ถ้าไม่มีจุดไหนถูกชี้ ให้เป็นลิสต์ว่าง"
)

# ── addressing one node inside a reasoning trace ──────────────────────────
#
# A correction has to point at a *place*, not at the answer: "the second step is
# wrong" is steerable, "this is wrong" is not. These are the addressable places.
_LIST_NODES = {
    "steps": "ลำดับการคิด",
    "assumptions": "สมมติฐานที่ตั้งเอง",
    "evidence_used": "หลักฐานที่อ้าง",
    "unknowns": "สิ่งที่ยังไม่รู้",
    "next_actions": "สิ่งที่ต้องทำต่อ",
}
_SCALAR_NODES = {
    "understanding": "โจทย์ที่ AI เข้าใจ",
    "answer": "คำตอบที่ส่งมอบ",
    "self_check": "ถ้าผิด จะผิดตรงไหนก่อน",
}
_NODE_RE = re.compile(r"^([a-z_]+)(?:\[(\d+)\])?$")


def _clean_node(value) -> str:
    """Normalise a node id the model echoed back.

    The reply is matched to the correction by this string, so a stray space or a
    dropped `]` silently detaches the model's answer from the step it answers —
    the CEO then sees his correction sitting unanswered next to a run that did
    address it. Repair what is unambiguous; leave anything else alone so a
    genuinely wrong id still reads as wrong.
    """
    node = jsonx.as_str(value).strip().strip("[]. ")
    m = re.match(r"^([a-z_]+)\s*\[?\s*(\d+)\s*\]?$", node, re.I)
    if m:
        return f"{m.group(1).lower()}[{int(m.group(2))}]"
    m = re.match(r"^([a-z_]+)$", node, re.I)
    return m.group(1).lower() if m else node


def node_text(trace: dict, node: str) -> tuple[str, str] | None:
    """Resolve `steps[1]` / `understanding` to `(label, text)` in this trace.

    None when the node does not exist in it — a correction aimed at a step that
    was never written would be quoted back to the model as a fact it cannot
    place, which is worse than refusing the correction.
    """
    m = _NODE_RE.match(node or "")
    if not m or not isinstance(trace, dict):
        return None
    key, idx = m.group(1), m.group(2)
    if key in _SCALAR_NODES and idx is None:
        text = jsonx.as_str(trace.get(key))
        return (_SCALAR_NODES[key], text) if text else None
    if key in _LIST_NODES and idx is not None:
        items = trace.get(key) or []
        i = int(idx)
        if not 0 <= i < len(items):
            return None
        item = items[i]
        if isinstance(item, dict):        # steps / next_actions
            text = " · ".join(x for x in (jsonx.as_str(item.get("step")),
                                          jsonx.as_str(item.get("why")),
                                          jsonx.as_str(item.get("found")),
                                          jsonx.as_str(item.get("action")),
                                          jsonx.as_str(item.get("owner"))) if x)
        else:
            text = jsonx.as_str(item)
        return (f"{_LIST_NODES[key]} ข้อ {i + 1}", text) if text else None
    return None

_REQUIRED = ("understanding", "answer")

# ── the live registry: which runs are in flight *right now* ────────────────
#
# `status: "running"` in the store is not enough to answer "what is running?".
# It is written by the request that starts the run and only corrected when that
# same request finishes, so a poll from another tab sees "running" for a task
# whose process died an hour ago, and sees nothing at all for one that started a
# second ago in a request still in flight.
#
# This is the in-memory truth instead: registered the moment a run begins,
# removed in a `finally` whatever happens to it. It is deliberately not
# persisted — a restart means nothing is running, which is exactly true. The two
# sources disagreeing is itself the useful signal: stored "running" with no live
# entry is a *stalled* task, and the map says so rather than showing it as busy.
_LIVE: dict[str, dict] = {}
_LIVE_LOCK = threading.Lock()


def _live_key(routine_id: int, task_id: int) -> str:
    return f"{routine_id}.{task_id}"


def live() -> list:
    """Runs in flight, newest first, each with how long it has been going."""
    now = time.monotonic()
    with _LIVE_LOCK:
        entries = list(_LIVE.values())
    return sorted(
        ({k: v for k, v in e.items() if not k.startswith("_")}
         | {"elapsed_ms": int((now - e["_started"]) * 1000)} for e in entries),
        key=lambda e: e["elapsed_ms"])


def is_running(routine_id: int, task_id: int) -> bool:
    with _LIVE_LOCK:
        return _live_key(routine_id, task_id) in _LIVE


def _seat(routine: dict) -> tuple[str, dict]:
    """The seat this routine is assigned to, and its config. Falls back to the
    first seat rather than crashing when a routine outlives a renamed seat."""
    key = routine.get("dept")
    if key not in config.DEPTS:
        key = next(iter(config.DEPTS))
    return key, config.DEPTS[key]


def _block(inputs: list, kind: str, label: str, body: str) -> str:
    """Record what goes into the prompt as it goes in.

    The manifest is the point: without it, "the AI ignored my document" is a
    suspicion the CEO cannot check. With it, either the document is on the list
    or it is not.
    """
    body = (body or "").strip()
    if not body:
        return ""
    inputs.append({"kind": kind, "label": label, "chars": len(body)})
    return f"[{label}]\n{body}"


def _grounding(routine: dict, task: dict, directive: str | None) -> tuple[str, list]:
    """Everything the seat is allowed to know, plus the manifest of it."""
    inputs: list = []
    blocks = []

    who = f"ผู้รับผิดชอบงานนี้: {task.get('owner') or routine.get('owner') or '—'}"
    header = "\n".join(x for x in [
        f"routine: {routine.get('name', '')}",
        f"โปรเจค/ธุรกิจ: {routine.get('project') or '(ไม่ผูกกับโปรเจคใด)'}",
        f"เป้าหมายของ routine: {routine.get('goal') or '—'}",
        f"รอบการทำงาน: {routine.get('cadence') or '—'}",
        who,
    ] if x)
    blocks.append(_block(inputs, "routine", "งานประจำที่คุณดูแล", header))
    blocks.append(_block(inputs, "task", "งานที่ต้องส่งรอบนี้",
                         f"{task.get('title', '')}\n{task.get('brief', '')}"))

    library = docs.knowledge_context(project=routine.get("project"), max_chars=3000)
    blocks.append(_block(inputs, "docs", "คลังเอกสารของ CEO ที่เกี่ยวกับโปรเจคนี้", library))

    past = memory.recall(routine.get("project"), limit=4)
    blocks.append(_block(inputs, "memory", "มติเก่าของบอร์ดที่งานนี้ต้องเคารพ",
                         memory.as_prompt(past, max_chars=1200)))

    siblings = "\n".join(
        f"- {t['title']} [{t['status']}] {(_answer_of(t) or '')[:160]}"
        for t in routine.get("tasks", [])
        if t["id"] != task["id"] and t.get("runs"))
    blocks.append(_block(inputs, "siblings", "งานอื่นใน routine เดียวกัน (กันทำซ้ำ/ขัดกันเอง)",
                         siblings))

    # The last two answers, so a re-run improves on its own work instead of
    # starting over and quietly dropping what was already right.
    previous = "\n\n".join(
        f"— รอบที่ {r['n']} ({r.get('provider', '')}):\n{(_answer_of_run(r) or '')[:1200]}"
        for r in task.get("runs", [])[-2:])
    blocks.append(_block(inputs, "previous_runs", "คำตอบรอบก่อนของงานนี้", previous))

    unresolved = store.open_comments(task)
    if unresolved:
        body = "\n".join(f"{i}. {c['text']}" for i, c in enumerate(unresolved, 1))
        blocks.append(_block(
            inputs, "comments",
            "คำสั่งแก้ไขจาก CEO — ต้องทำตามให้ครบทุกข้อในรอบนี้", body))

    # The wrong turns, quoted at the exact place they were taken. This is the
    # difference between "that answer was wrong" and "you went wrong here" —
    # only the second one closes a road.
    fixes = store.open_corrections(task)
    if fixes:
        body = "\n\n".join(
            f"node = {c['node']}\n"
            f"  จุดนี้คือ: {c['label']} (จากรอบที่ {c['run_n']})\n"
            f"  คุณเคยคิดว่า: {c['was']}\n"
            f"  CEO บอกว่าต้องเป็น: {c['should']}"
            for c in fixes)
        blocks.append(_block(
            inputs, "fixes",
            "จุดที่ CEO ชี้ว่าคุณ 'คิดผิด' — ทางเหล่านี้ถูกปิดแล้ว ห้ามเดินซ้ำ "
            "และต้องตอบใน fix_responses ให้ครบทุก node", body))
    if directive:
        blocks.append(_block(inputs, "directive", "คำสั่งเพิ่มเติมสำหรับรอบนี้", directive))

    return "\n\n".join(b for b in blocks if b), inputs


def _answer_of_run(run: dict) -> str:
    trace = run.get("trace") or {}
    return jsonx.as_str(trace.get("answer")) or jsonx.as_str(run.get("text"))


def _answer_of(task: dict) -> str:
    runs = task.get("runs") or []
    return _answer_of_run(runs[-1]) if runs else ""


def _normalise(data: dict) -> dict:
    """Coerce the trace into the shape the UI renders.

    A model that answers `steps` as a paragraph, or `confidence` as "70%", has
    still done the work — dropping the trace over its punctuation would hide the
    reasoning this whole feature exists to show.
    """
    steps = []
    for item in jsonx.as_list(data.get("steps")):
        if isinstance(item, dict):
            steps.append({"step": jsonx.as_str(item.get("step")),
                          "why": jsonx.as_str(item.get("why")),
                          "found": jsonx.as_str(item.get("found"))})
        elif jsonx.as_str(item):
            steps.append({"step": jsonx.as_str(item), "why": "", "found": ""})

    actions = []
    for item in jsonx.as_list(data.get("next_actions")):
        if isinstance(item, dict):
            actions.append({"action": jsonx.as_str(item.get("action")),
                            "owner": jsonx.as_str(item.get("owner")),
                            "due": jsonx.as_str(item.get("due"))})
        elif jsonx.as_str(item):
            actions.append({"action": jsonx.as_str(item), "owner": "", "due": ""})

    replies = []
    for item in jsonx.as_list(data.get("fix_responses")):
        if isinstance(item, dict):
            replies.append({"node": _clean_node(item.get("node")),
                            "what_i_did": jsonx.as_str(item.get("what_i_did")),
                            "disagree": jsonx.as_str(item.get("disagree"))})

    confidence = jsonx.as_int(data.get("confidence"))
    if confidence is not None and not 0 <= confidence <= 100:
        confidence = None
    return {
        "understanding": jsonx.as_str(data.get("understanding")),
        "steps": steps,
        "assumptions": jsonx.as_str_list(data.get("assumptions")),
        "evidence_used": jsonx.as_str_list(data.get("evidence_used")),
        "unknowns": jsonx.as_str_list(data.get("unknowns")),
        "answer": jsonx.as_str(data.get("answer")),
        "next_actions": actions,
        "confidence": confidence,
        "self_check": jsonx.as_str(data.get("self_check")),
        "changed_from_last": jsonx.as_str(data.get("changed_from_last")),
        "fix_responses": replies,
    }


def run_task(routine_id: int, task_id: int, directive: str | None = None) -> dict:
    """Execute one task on its routine's seat and append the run.

    Never raises for a model that misbehaves: a failed run is recorded as a run,
    with the error on it, because a task that silently stays 'todo' after the CEO
    pressed the button is the worst of both worlds.
    """
    routine = store.get_tree(routine_id)
    if routine is None:
        raise ValueError("ไม่พบ routine นี้")
    task = next((t for t in routine["tasks"] if t["id"] == task_id), None)
    if task is None:
        raise ValueError("ไม่พบงานนี้ใน routine")

    dept, seat = _seat(routine)
    provider = store.get_providers().get(dept, "mock")
    lane, guard = depts.LANES.get(dept, ("ธุรกิจโดยรวม", "ตอบเฉพาะสิ่งที่มีหลักฐานรองรับ"))
    system = TASK_PERSONA.format(name=seat["name"], role=seat["role"],
                                 lane=lane, guard=guard) + TASK_SCHEMA
    user, inputs = _grounding(routine, task, directive)
    pending = store.open_comments(task)
    pending_fixes = store.open_corrections(task)

    if pending_fixes:
        trigger = "CEO แก้เส้นทางคิด " + ", ".join(f"@{c['node']}" for c in pending_fixes)
    elif pending:
        trigger = "คอมเมนต์ของ CEO " + ", ".join(f"#{c['id']}" for c in pending)
    else:
        trigger = "คำสั่งเพิ่มเติม" if directive else "สั่งรันเอง"

    store.update_task(routine_id, task_id, status="running")
    started = time.monotonic()
    key = _live_key(routine_id, task_id)
    with _LIVE_LOCK:
        _LIVE[key] = {
            "routine_id": routine_id, "task_id": task_id,
            "routine": routine.get("name", ""), "tree": routine.get("tree", ""),
            "task": task.get("title", ""),
            "owner": task.get("owner") or routine.get("owner", ""),
            "dept": dept, "seat": seat["name"], "provider": provider,
            "trigger": trigger, "run_n": len(task.get("runs", [])) + 1,
            "at": datetime.now(timezone.utc).isoformat(),
            "_started": started,
        }
    try:
        out = llm.chat_json(provider, system, user, max_tokens=MAX_TOKENS,
                            required=_REQUIRED)
    finally:
        # Whatever happens — a raise, a timeout, a provider dying — the map must
        # not keep claiming this task is busy.
        with _LIVE_LOCK:
            _LIVE.pop(key, None)
    elapsed = int((time.monotonic() - started) * 1000)

    trace = _normalise(out["data"]) if isinstance(out["data"], dict) else None
    if trace is None:
        log.warning("pipeline run failed: routine %s task %s (%s)",
                    routine_id, task_id, out["error"])
    run = {
        "ok": bool(trace and trace["answer"]),
        "provider": out["provider"], "model": out["model"],
        "dept": dept, "seat": seat["name"],
        "trace": trace,
        "text": out["text"] if trace is None else "",
        "error": out["error"],
        "truncated": out.get("truncated", False),
        "calls": out.get("calls", 1),
        "inputs": inputs,
        "prompt_chars": len(user),
        "duration_ms": elapsed,
        # Why this run happened at all — the difference between "the CEO pressed
        # run" and "the CEO rejected the last answer" is the point of the tree.
        "trigger": trigger,
        "answered_comments": [c["id"] for c in pending],
        "answered_fixes": [c["id"] for c in pending_fixes],
        "directive": directive or None,
    }
    updated = store.append_run(routine_id, task_id, run)
    # Hand back the *stored* run, not the local dict: the run number and
    # timestamp are assigned on append, and the UI keys its reasoning panel on
    # that number.
    return {"task": updated, "run": updated["runs"][-1]}


def explain_inputs(run: dict) -> str:
    """One line summarising what the model was allowed to see, for the UI."""
    if not run.get("inputs"):
        return "ไม่มีข้อมูลประกอบ"
    return " · ".join(f"{i['label']} ({i['chars']:,} ตัวอักษร)" for i in run["inputs"])
