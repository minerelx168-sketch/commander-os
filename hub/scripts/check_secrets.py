#!/usr/bin/env python3
"""Refuse to commit runtime state that carries credentials.

Eleven ingest keys reached GitHub before `hub/memory/sources.json` was
gitignored. They were dead by then, but only by luck: the connectors had been
deleted. Nothing stopped the next such file from being added, so this does.

Run as a pre-commit hook and in the suite.
"""
import json
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]

# Files that must never be tracked, whatever .gitignore currently says.
FORBIDDEN_PATHS = {
    "hub/.env",
    "hub/memory/sources.json",
    "hub/memory/hub_store.json",
}

# Credential shapes this project actually mints or holds.
SECRET_RE = re.compile(
    r"cx_[A-Za-z0-9_-]{20,}"          # per-connector ingest keys
    r"|ghp_[A-Za-z0-9]{30,}"          # GitHub PATs
    r"|sk-ant-[A-Za-z0-9_-]{20,}"     # Anthropic
    r"|[0-9]{9,10}:AA[A-Za-z0-9_-]{30,}"   # Telegram bot tokens
)


# Files whose job is to *name* the credential shapes: the checker, its tests,
# the tester that plants fakes to prove the checker bites, and the env example.
# They are not waved through wholesale — a real key pasted into one of them must
# still be caught — so only obvious placeholders are tolerated.
NAMES_THE_SHAPES = {
    "hub/scripts/check_secrets.py",
    "hub/tests/test_secrets.py",
    "scripts/check_guard_works.sh",
    "hub/.env.example",
}
PLACEHOLDER_RE = re.compile(r"^(?:[A-Za-z0-9_-]*?)(AAAA|XXXX|1234567890:)")


def is_placeholder(value: str) -> bool:
    """A run of A/X or the documented 1234567890: prefix — never a live key."""
    return bool(PLACEHOLDER_RE.search(value)) or "A" * 8 in value


def tracked() -> set[str]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT,
                         capture_output=True, text=True, check=True)
    return set(out.stdout.split())


def main() -> int:
    bad = []

    files = tracked()
    for path in sorted(FORBIDDEN_PATHS & files):
        bad.append(f"tracked but must not be: {path}")

    for rel in sorted(files):
        p = ROOT / rel
        if not p.is_file() or p.suffix in {".png", ".jpg", ".pdf", ".xlsx"}:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for m in SECRET_RE.finditer(text):
            if rel in NAMES_THE_SHAPES and is_placeholder(m.group()):
                continue
            bad.append(f"credential in {rel}: {m.group()[:14]}…")

    if bad:
        print("SECRETS WOULD BE COMMITTED:")
        for b in bad:
            print("  " + b)
        print("\nMove the value into hub/.env (untracked) and reference it there.")
        return 1

    print(f"ok — {len(files)} tracked files, no credentials, no runtime state")
    return 0


if __name__ == "__main__":
    sys.exit(main())
