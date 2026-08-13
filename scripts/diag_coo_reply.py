#!/usr/bin/env python3
"""Diagnose: the CEO asked COO but someone else answered (or nobody did)."""
import os

import httpx

HUB = "https://pennsylvania-influences-strength-ebooks.trycloudflare.com"
ENV = os.path.expanduser("~/commander-os/hub/.env")


def env(key):
    for line in open(ENV, encoding="utf-8"):
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip()
    return ""


K, T = env("HERMES_API_KEY"), env("TELEGRAM_BOT_TOKEN")
h = {"X-Hermes-API-Key": K}

print("=== last 6 follow-ups (what the hub actually handled) ===")
for f in httpx.get(f"{HUB}/api/followups?limit=6", headers=h, timeout=40).json()["followups"]:
    print(f"  #{f['id']} {f['at'][:19]} seat={f['dept']:<9} run={f['run_id']} ok={f['ok']}")
    print(f"     Q: {f['question'][:100]}")
    print(f"     A: {(f['answer'] or '(empty)')[:100]}")

print("\n=== telegram webhook health ===")
w = httpx.get(f"{HUB}/api/telegram/status", headers=h, timeout=40).json()["webhook"]["result"]
for k in ("url", "pending_update_count", "last_error_date", "last_error_message"):
    print(f"  {k}: {w.get(k)}")

print("\n=== which seats exist and their keys ===")
st = httpx.get(f"{HUB}/api/state", headers=h, timeout=40).json()
for d in st["depts"]:
    print(f"  key={d['key']:<10} name={d['name']:<14} provider={d['provider']}")
