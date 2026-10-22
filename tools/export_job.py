#!/usr/bin/env python3
"""Export a Managed Agents session into a UI job folder (read-only API calls: events + files).

    python3 tools/export_job.py <session_id> <dest_dir> --title "Case A: socks" [--demo]

Writes <dest>/job.json, <dest>/events.json and <dest>/files/*. The folder format is the one the
UI backend (ui/server) serves for live, imported and demo jobs alike. The API key is read by
tools/ma_client.py from ARK_API_KEY (never printed).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ma_client  # noqa: E402

LABELS = ("SAMPLE_VIDEO", "PRODUCT_URL", "REQUIREMENTS", "BUDGET", "AUTO_APPROVE")


def parse_inputs(events: list) -> dict:
    """Recovers the inputs from the first user message (the labelled lines the agent parses)."""
    inputs = {}
    for e in events:
        if e.get("type") != "user.message":
            continue
        text = ma_client.text_of(e.get("content"))
        found = {}
        for line in text.splitlines():
            m = re.match(r"^\s*([A-Z_]+)\s*:\s*(.*)$", line)
            if m and m.group(1) in LABELS:
                found[m.group(1)] = m.group(2).strip()
        if found:
            inputs = {"sample_url": found.get("SAMPLE_VIDEO"), "product_url": found.get("PRODUCT_URL"),
                      "requirements": found.get("REQUIREMENTS"), "auto_approve": found.get("AUTO_APPROVE", "no").lower() == "yes",
                      "message": text}
            b = found.get("BUDGET", "")
            nums = {k: int(v) for k, v in re.findall(r"(Seedream|Seedance|evaluator)[^<]*<=\s*(\d+)", b, re.I)}
            inputs["budget"] = {"seedream": nums.get("Seedream", nums.get("seedream", 0)),
                                "seedance": nums.get("Seedance", nums.get("seedance", 0)),
                                "evaluator": nums.get("evaluator", nums.get("Evaluator", 0))}
            m = re.search(r"about\s+(\d+)\s*s.*?(480p|720p)", found.get("REQUIREMENTS", ""), re.I)
            inputs["options"] = {"length_s": int(m.group(1)) if m else None, "resolution": m.group(2) if m else None}
            break
    return inputs


def status_from(summary: dict) -> str:
    steps = summary.get("steps") or []
    if steps and steps[-1]["n"] == 11 and steps[-1]["status"] == "done":
        return "done"
    if steps and steps[-1]["status"] == "failed":
        return "failed"
    if summary.get("errors"):
        return "failed"
    return "stopped" if summary.get("last_stop_reason") else "running"


def export_job(client, session_id: str, dest: Path, title: str | None = None, demo: bool = False) -> dict:
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    events = client.all_events(session_id)
    (dest / "events.json").write_text(json.dumps({"events": events}, ensure_ascii=False))
    saved = client.download_session_files(session_id, dest / "files")
    index = {}
    for name, fid, size in saved:
        p = dest / "files" / name
        index[name] = {"id": fid, "bytes": p.stat().st_size if p.exists() else None}
    summary = ma_client.summarize(events)
    summary.pop("tools", None)
    created = events[0].get("processed_at") if events else time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    try:
        sess = client.get_session(session_id)
        title = title or sess.get("title")
    except Exception:
        sess = {}
    job = {
        "id": dest.name, "title": title or session_id, "created_at": created, "status": status_from(summary),
        "demo": bool(demo), "session_id": session_id, "inputs": parse_inputs(events), "summary": summary,
        "files_index": index, "imported_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    (dest / "job.json").write_text(json.dumps(job, indent=1, ensure_ascii=False))
    return job


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("session_id")
    ap.add_argument("dest_dir")
    ap.add_argument("--title")
    ap.add_argument("--demo", action="store_true", help="mark the job as a demo (shown in demo mode)")
    a = ap.parse_args(argv)
    client = ma_client.Client()
    job = export_job(client, a.session_id, Path(a.dest_dir), a.title, a.demo)
    n_files = len(list((Path(a.dest_dir) / "files").glob("*")))
    print(f"exported {a.session_id} -> {a.dest_dir}: {len(job['summary'].get('steps', []))} step events, "
          f"{n_files} files, status {job['status']}")


if __name__ == "__main__":
    main()
