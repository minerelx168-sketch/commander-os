#!/usr/bin/env python3
"""Find calls in index.html to page functions that no longer exist.

A missing function throws at runtime, and a broad catch turns that into a
misleading "Hub Offline" — the exact failure this guards against. Static tests
never see it, because to them the page is just a string.
"""
import pathlib
import re
import sys

PAGE = pathlib.Path("/Users/boston/commander-os/hub/static/index.html")

BUILTINS = {
    # keywords that look like calls
    "if", "for", "while", "switch", "catch", "return", "typeof", "await", "new",
    "function", "else", "do", "throw", "delete", "in", "of", "case",
    # globals
    "fetch", "setTimeout", "setInterval", "clearInterval", "clearTimeout",
    "parseInt", "parseFloat", "isNaN", "confirm", "alert", "prompt",
    "encodeURIComponent", "decodeURIComponent", "structuredClone",
    "requestAnimationFrame", "queueMicrotask", "FormData", "AbortController",
    "String", "Number", "Boolean", "Object", "Array", "Date", "Promise",
    "Error", "TypeError", "Set", "Map", "JSON", "Math", "RegExp", "Intl",
    # `async (` / `var (` are syntax, and words inside template strings or
    # message text can look like bare calls to a regex.
    "async", "var", "let", "const", "failed", "session",
    # callback parameters invoked inside a helper, not page-level functions
    "fmt", "fn", "cb",
}


def code_only(script: str) -> str:
    """Drop comments — prose like "the unlock (…)" otherwise reads as a call."""
    script = re.sub(r"/\*.*?\*/", " ", script, flags=re.S)
    return re.sub(r"(?m)^\s*//.*$", " ", script)


def main() -> int:
    html = PAGE.read_text(encoding="utf-8")
    script = code_only(html[html.index("<script>"):])

    defined = set(re.findall(r"(?:async\s+)?function\s+(\w+)", script))
    defined |= set(re.findall(r"(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\(", script))
    defined |= set(re.findall(r"(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?function", script))
    defined |= set(re.findall(r"(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?\w+\s*=>", script))

    # Bare calls only: `foo(` but never `x.foo(` — methods belong to objects we
    # cannot resolve statically, and every page function is called bare.
    called = set(re.findall(r"(?<![\.\w$])([a-z]\w+)\s*\(", script))
    called |= set(re.findall(r'on\w+="([a-zA-Z]\w+)\(', html))

    missing = sorted(called - defined - BUILTINS)
    if missing:
        print("CALLED BUT NOT DEFINED:")
        for name in missing:
            src = "onclick" if re.search(rf'on\w+="{name}\(', html) else "js"
            print(f"  {name}  [{src}]")
        return 1
    print(f"ok — {len(defined)} page functions defined, every call resolves")
    return 0


if __name__ == "__main__":
    sys.exit(main())
