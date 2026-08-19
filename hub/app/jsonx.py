"""One hardened reader for everything an LLM hands back.

Three near-identical `_parse_json` copies used to live in depts/memory/report,
each with a different idea of how forgiving to be: only the report's could
salvage a truncated reply, so the same overrun that cost the CEO a section of a
PDF cost him the *entire* framing stage. Worse, all three located the object with
`find("{") .. rfind("}")`, which is not JSON extraction — it is a guess that
breaks the moment the model writes a brace in its preamble or appends a "hope
this helps" that contains one.

What lives here:

* `extract()`   — find the JSON in a reply and parse it, repairing the failure
                  modes real providers actually produce (fences, prose wrappers,
                  trailing commas, `//` comments, Python literals, raw newlines
                  inside strings, curly quotes) and salvaging a reply that was
                  cut off mid-object.
* `number()`    — read a *value* the way a Thai CFO writes one: "1,250 บาท",
                  "1.2 ล้าน", "(3,000)", "3%", "50k", "100-200". A model that
                  answers `3` where the schema asked for `0.03` is the single
                  most expensive misread in the hub, so percent-typed fields say
                  so and are normalised on the way in.
* coercers      — `as_list`/`as_dict`/`as_str`/`as_int`, because a schema slot
                  that asked for a list comes back as a bare string often enough
                  that treating it as a hard failure throws away a good answer.
* `missing()`   — which required keys a parsed object still lacks, so a caller
                  can ask for a repair instead of quietly rendering a hole.

Everything fails closed: a reply that cannot be read returns None, never a
plausible-looking object that nobody wrote.
"""
import json
import logging
import re

log = logging.getLogger("hub.jsonx")

__all__ = ["extract", "salvage", "number", "number_detail", "missing",
           "as_list", "as_dict", "as_str", "as_str_list", "as_int"]

# ── locating the object ────────────────────────────────────────────────────

_FENCED = re.compile(r"```[ \t]*(?:json|JSON|jsonc|json5)?[ \t]*\r?\n(.*?)```", re.S)
_LOOSE_FENCE = re.compile(r"^[ \t]*```[a-zA-Z0-9_+-]*[ \t]*$", re.M)


def _spans(text: str):
    """Every position where a JSON object plausibly starts, best first."""
    out, start = [], text.find("{")
    while start >= 0 and len(out) < 5:
        out.append(start)
        start = text.find("{", start + 1)
    return out


def _balanced(text: str, start: int) -> str | None:
    """The substring from `start` to the brace that closes it, or None if the
    reply ran out first (a truncated object — `salvage` handles those)."""
    depth, in_str, esc = 0, False, False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


# ── repairing what providers actually emit ─────────────────────────────────

_TRAILING_COMMA = re.compile(r",(\s*[}\]])")
_LINE_COMMENT = re.compile(r"(?<![:\"'\\])//[^\n\r]*")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_PY_LITERAL = re.compile(r"\b(True|False|None)\b")
_NOT_A_NUMBER = re.compile(r"\b(NaN|-?Infinity)\b")
_CURLY = str.maketrans({"\u201c": '"', "\u201d": '"', "\u201e": '"', "\u201f": '"',
                        "\u2018": "'", "\u2019": "'", "\u00ab": '"', "\u00bb": '"'})


def _escape_raw_newlines(s: str) -> str:
    """A model that writes a multi-line Thai paragraph straight into a string
    produces a control character JSON rejects. Escape it rather than lose the
    whole document over a line break."""
    out, in_str, esc = [], False, False
    for ch in s:
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            if ch == "\n":
                out.append("\\n")
                continue
            if ch == "\r":
                out.append("\\r")
                continue
            if ch == "\t":
                out.append("\\t")
                continue
        elif ch == '"':
            in_str = True
        out.append(ch)
    return "".join(out)


def _repair(s: str) -> str:
    s = _escape_raw_newlines(s)
    s = _BLOCK_COMMENT.sub("", s)
    s = _LINE_COMMENT.sub("", s)
    s = _PY_LITERAL.sub(lambda m: {"True": "true", "False": "false",
                                   "None": "null"}[m.group(1)], s)
    s = _NOT_A_NUMBER.sub("null", s)
    return _TRAILING_COMMA.sub(r"\1", s)


def _repair_hard(s: str) -> str:
    """Last resort: a model that delimited its JSON with typographic quotes.
    Applied only after the gentler passes failed, because it also rewrites
    curly quotes that legitimately sit inside Thai prose."""
    return _repair(s.translate(_CURLY))


def _loads(fragment: str) -> dict | None:
    for candidate in (fragment, _repair(fragment), _repair_hard(fragment)):
        try:
            parsed = json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


# ── salvaging a reply that was cut off ─────────────────────────────────────

def salvage(fragment: str) -> dict | None:
    """A reply that hit the token ceiling stops mid-object, which used to throw
    away every complete section the advisor had already written. Walk the
    fragment, drop the half-written tail, and shut the remaining containers so
    the finished sections survive. Returns None when nothing coherent is left —
    a partial document is useful, a fabricated one is not.
    """
    depth, in_str, esc, last_good = 0, False, False, None
    for i, ch in enumerate(fragment):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
        elif ch == "," and depth <= 2:
            last_good = i          # a safe place to truncate: end of an entry
    if last_good is None:
        return None

    head = fragment[:last_good]
    # re-count what is still open after truncating, then close it in order
    stack, in_str, esc = [], False, False
    for ch in head:
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append(ch)
        elif ch in "}]" and stack:
            stack.pop()
    repaired = head + "".join("}" if c == "{" else "]" for c in reversed(stack))
    return _loads(repaired)


# ── the public reader ──────────────────────────────────────────────────────

def extract(text: str) -> dict | None:
    """Dig the JSON object out of an LLM reply. None when there isn't one."""
    if not text or not str(text).strip():
        return None
    raw = str(text).strip()

    # A fenced block is the model telling us where the JSON is — believe it
    # first, then fall back to the reply as a whole with fences stripped.
    candidates = [m.group(1) for m in _FENCED.finditer(raw)]
    candidates.append(_LOOSE_FENCE.sub("", raw))
    candidates.append(raw)

    for cand in candidates:
        # Outermost brace first: an object that never closes is a reply that ran
        # out of budget, and salvaging it beats returning some nested fragment
        # that happens to parse on its own.
        for start in _spans(cand):
            whole = _balanced(cand, start)
            if whole is not None:
                parsed = _loads(whole)
                if parsed is not None:
                    return parsed
                continue
            rescued = salvage(cand[start:])
            if rescued is not None:
                log.warning("salvaged a truncated JSON reply (%s chars)",
                            len(cand) - start)
                return rescued
    return None


def missing(data, required) -> list:
    """Required keys the object does not carry (empty values count as absent —
    a schema slot filled with `""` is a hole the CEO would read as an answer)."""
    if not isinstance(data, dict):
        return list(required)
    return [k for k in required
            if k not in data or data[k] is None or data[k] == "" or data[k] == []]


# ── coercers: the shape asked for, not the shape that arrived ──────────────

def as_str(value, default: str = "") -> str:
    if value is None or isinstance(value, (dict, list, bool)):
        return default
    return str(value).strip()


def as_list(value) -> list:
    """A slot that asked for a list and got a string is still an answer."""
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [v for v in value if v not in (None, "")]
    if isinstance(value, dict):
        return [v for v in value.values() if v not in (None, "")]
    if isinstance(value, str):
        # A slot the schema declared as a list came back as prose. Models bullet
        # these, semicolon them and comma them about as often as they array them,
        # and "cfo, coo" has to convene the same board as ["cfo", "coo"].
        parts = [p.strip(" \t-•*·") for p in re.split(r"[\n;,]+", value)]
        return [p for p in parts if p]
    return [value]


def as_str_list(value) -> list:
    return [as_str(v) for v in as_list(value) if as_str(v)]


def as_dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def as_int(value, default=None):
    """Ids and counts arrive as `1`, `"1"`, `"#1"` or `"memory 1"` alike."""
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    m = re.search(r"-?\d+", str(value or ""))
    return int(m.group()) if m else default


# ── numbers ────────────────────────────────────────────────────────────────

# Longest first: "พันล้าน" must win over "พัน", "ล้านล้าน" over "ล้าน".
_MAGNITUDES = [
    ("ล้านล้าน", 1e12), ("พันล้าน", 1e9), ("ร้อยล้าน", 1e8), ("สิบล้าน", 1e7),
    ("ล้าน", 1e6), ("แสน", 1e5), ("หมื่น", 1e4), ("พัน", 1e3), ("ร้อย", 1e2),
    ("trillion", 1e12), ("billion", 1e9), ("million", 1e6), ("thousand", 1e3),
]
# Bare letter suffixes only count when they are the *whole* trailing word —
# otherwise "3 months" reads as three million.
_SUFFIXES = {"k": 1e3, "m": 1e6, "mm": 1e6, "mn": 1e6, "bn": 1e9, "b": 1e9, "t": 1e12}

_NUMBER = re.compile(r"[-+]?\d[\d,\u066c]*(?:\.\d+)?")
_RANGE = re.compile(r"\d\s*(?:-|–|—|~|ถึง|to)\s*[-+]?\d")
_PERCENT_WORDS = ("%", "เปอร์เซ็นต์", "ร้อยละ", "percent", "pct")
_CURRENCY_NOISE = re.compile(r"(บาท|thb|฿|usd|\$|ต่อเดือน|/เดือน|per month|เดือน|หน่วย|units?)",
                             re.I)


def _magnitude(tail: str) -> float:
    """The multiplier written after a number, if any."""
    tail = _CURRENCY_NOISE.sub(" ", tail).strip().lower()
    for word, mult in _MAGNITUDES:
        if tail.startswith(word.lower()):
            return mult
    head = tail.split()[0] if tail.split() else ""
    return _SUFFIXES.get(head.strip(".,"), 1.0)


def number_detail(entry, kind: str | None = None, default: float = 0.0):
    """Read a value the way it was written. Returns `(value, note)` where the
    note is empty unless the text had to be reinterpreted — the CEO is told
    when "3" was read as 3%, because a silent unit fix is a wrong number he
    cannot trace.

    `kind` is what the schema promised: "pct" (a rate stored as 0.03),
    "mult" (a scenario multiplier around 1.0), or None/"money"/"count".
    """
    if isinstance(entry, dict):
        entry = entry.get("value", entry.get("amount", entry.get("number")))
    if isinstance(entry, bool) or entry is None:
        return default, ""

    note = ""
    if isinstance(entry, (int, float)):
        value, had_percent_sign = float(entry), False
    else:
        txt = str(entry).strip()
        if not txt:
            return default, ""
        negate = txt.startswith("(") and txt.endswith(")")   # accounting negative
        if negate:
            txt = txt[1:-1]
        low = txt.lower()
        had_percent_sign = any(w in low for w in _PERCENT_WORDS)

        found = list(_NUMBER.finditer(txt))
        if not found:
            return default, ""
        if len(found) >= 2 and _RANGE.search(txt[found[0].start():found[1].end()]):
            # "100-200" is a range, not a subtraction: the dash belongs to the
            # range, so the upper bound keeps its own sign only if it repeats one
            lo, hi = _one(found[0], txt), abs(_one(found[1], txt))
            value = (lo + hi) / 2
            note = f"ช่วง {_trim(lo)}–{_trim(hi)} → ใช้ค่ากลาง {_trim(value)}"
        else:
            value = _one(found[0], txt)
        if negate:
            value = -value
        if had_percent_sign:
            value /= 100

    if kind == "pct" and not had_percent_sign and 1 < abs(value) <= 100:
        # the schema asked for 0.03 and the model answered 3
        note = (note + " · " if note else "") + f"อ่าน {_trim(value)} เป็น {_trim(value)}%"
        value /= 100
    elif kind == "mult" and abs(value) > 10:
        # a scenario multiplier written as a percentage (125 for 1.25)
        note = (note + " · " if note else "") + f"อ่าน {_trim(value)} เป็นตัวคูณ {_trim(value / 100)}"
        value /= 100
    return value, note


def _one(match, txt: str) -> float:
    raw = match.group().replace(",", "").replace("\u066c", "")
    try:
        value = float(raw)
    except ValueError:
        return 0.0
    return value * _magnitude(txt[match.end():match.end() + 24])


def _trim(value: float) -> str:
    return f"{value:g}"


def number(entry, kind: str | None = None, default: float = 0.0) -> float:
    return number_detail(entry, kind, default)[0]
