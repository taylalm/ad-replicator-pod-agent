#!/usr/bin/env python3
"""Compact status of the latest Managed Agent sessions: status, STEP lines, last tool call, last message.

Usage: python3 tools/status.py [--limit 4] [--session ID ...] [--full]
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ma_client import Client, summarize, text_of  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=4)
    ap.add_argument("--session", action="append", default=[])
    ap.add_argument("--full", action="store_true")
    a = ap.parse_args()
    c = Client()
    ids = a.session or [s["id"] for s in c.get("/sessions", limit=a.limit).get("data", [])]
    for sid in ids:
        sess = c.get_session(sid)
        ev = c.all_events(sid)
        s = summarize(ev)
        print(f"== {sid} [{sess['status']}] {sess.get('title')} agent v{sess['agent'].get('version')} "
              f"events={len(ev)} tools={s['tool_calls']} tool_errors={s['tool_errors']} usage={s['usage']['input_tokens'] // 1000}k/{s['usage']['output_tokens'] // 1000}k")
        if s["steps"]:
            last = {}
            for st in s["steps"]:
                last[st["n"]] = st
            print("   steps:", ", ".join(f"{n}:{st['status']}" for n, st in sorted(last.items())))
        for t in s["tools"][-(6 if a.full else 2):]:
            print(f"   {'ERR ' if t['is_error'] else 'ok  '}{t['name']:<8} {t['input'][:150].replace(chr(10), ' | ')}")
        msgs = [e for e in ev if e["type"] == "agent.message"]
        if msgs:
            print("   last msg:", text_of(msgs[-1]["content"])[: (1200 if a.full else 300)].replace("\n", " | "))
        if s["errors"]:
            print("   errors:", str(s["errors"])[:300])


if __name__ == "__main__":
    main()
