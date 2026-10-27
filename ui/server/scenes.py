"""Scene picker: which take each scene of the ad uses, and whether the scene is in the ad at all.

Choices live in <job>/web_scene_picks.json ({clip_id: {"file": take file, "include": bool}}), kept in the agent session
like the other site records. Every take of a scene can be chosen: the agent's current take (the one in its cut), its
earlier takes (clip_01_v2, ...) and takes made on the site (web_take_clip_01_1.mp4).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Optional

PICKS = "web_scene_picks.json"


def _read(p: Path):
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return None


def load_picks(d: Path) -> Dict[str, dict]:
    raw = _read(d / PICKS)
    return raw.get("scenes", {}) if isinstance(raw, dict) else {}


def save_picks(d: Path, picks: Dict[str, dict]) -> Path:
    clean = {}
    for clip, p in (picks or {}).items():
        if re.fullmatch(r"clip_\d+[A-Za-z0-9_-]*", str(clip)) and isinstance(p, dict):
            f = Path(str(p.get("file") or "")).name
            clean[clip] = {"file": f or None, "include": bool(p.get("include", True))}
    path = d / PICKS
    path.write_text(json.dumps({"scenes": clean}, indent=1))
    return path


def _check(files_dir: Path, stem: str) -> dict:
    c = _read(files_dir / f"check_{stem}.json") or {}
    return {"verdict": c.get("verdict"), "summary": (c.get("summary") or "")[:400] or None, "payoff_window": c.get("payoff_window")}


def options(d: Path, files_dir: Path, job: dict, web_takes: List[dict]) -> List[dict]:
    """One row per scene of the agent's clips: its takes (newest first after the one in the cut) and the saved choice."""
    picks = load_picks(d)
    cj = _read(files_dir / "clips.json")
    cj = cj.get("clips") if isinstance(cj, dict) and isinstance(cj.get("clips"), dict) else {}
    rows = []
    for i, c in enumerate(job.get("clips") or []):
        cid = c["id"]
        takes = []
        agent = [{"file": c["file"], "url": c["url"], "current": True}] + [{**t, "current": False} for t in c.get("takes") or []]
        rec = cj.get(cid) if isinstance(cj.get(cid), dict) else {}
        site_src = str(rec.get("source") or "")
        for n, t in enumerate(agent):
            stem = Path(t["file"]).stem
            v = re.search(r"_v(\d+)$", stem)
            label = "In the agent's cut" if t["current"] else (f"Agent take {v.group(1)}" if v else "Agent's first take")
            info = {**_check(files_dir, stem), "model": c.get("model") if t["current"] else None, "source": "agent"}
            if t["current"] and (rec.get("site_take") or "/uploads/web_" in site_src):
                # the agent copied a take made on the site over this name: its check is the site take's, not the old file's
                site_file = Path(site_src).name.replace("web_", "", 1) if site_src else None
                w = next((x for x in web_takes if x.get("file") == site_file), {})
                label = "Your site take, in the cut"
                info = {"verdict": (w.get("check") or {}).get("verdict"), "summary": None, "payoff_window": (w.get("check") or {}).get("payoff_window"),
                        "model": w.get("model"), "source": "site"}
            takes.append({"file": t["file"], "url": t["url"], "label": label, "current": t["current"], **info})
        for w in web_takes:
            if w.get("kind") == "clip" and w.get("clip") == cid and w.get("file"):
                if any(t["file"] == w["file"] for t in takes):
                    continue
                chk = w.get("check") or {}
                takes.append({"file": w["file"], "url": f"/api/jobs/{job['id']}/files/{w['file']}", "source": "site",
                              "label": f"Site take {w.get('n')}", "current": False, "verdict": chk.get("verdict"),
                              "summary": (chk.get("summary") or "")[:400] or None, "payoff_window": chk.get("payoff_window"),
                              "model": w.get("model")})
        pick = picks.get(cid) or {}
        accepted = next((w["file"] for w in web_takes if w.get("kind") == "clip" and w.get("clip") == cid and w.get("accepted")), None)
        chosen = pick.get("file") if any(t["file"] == pick.get("file") for t in takes) else (accepted or c["file"])
        rows.append({"id": cid, "n": i + 1, "takes": takes, "chosen": chosen, "include": pick.get("include", True),
                     "in_cut": c["file"]})
    return rows


def agent_message(rows: List[dict], picks: Dict[str, dict]) -> Optional[str]:
    """What to tell the agent when the ad is not assembled yet; None when nothing differs from its own choice."""
    lines = []
    for r in rows:
        p = picks.get(r["id"]) or {}
        if p.get("include") is False:
            lines.append(f"- {r['id']}: leave this scene OUT of the ad (keep the other scenes' order and timing).")
            continue
        f = p.get("file")
        if not f or f == r["in_cut"]:
            continue
        take = next((t for t in r["takes"] if t["file"] == f), None)
        if not take:
            continue
        where = f"/mnt/session/uploads/web_{f}" if take["source"] == "site" else f"your own take {f}"
        lines.append(f"- {r['id']}: use {where} as the current take (copy it into your clips folder; keep the others as _vN).")
    if not lines:
        return None
    return ("USE TAKES: the user picked the takes for the ad on the site:\n" + "\n".join(lines) +
            "\nRecord this in clips.json, do not regenerate these scenes, and continue the workflow where you left off. "
            "Write every message and STEP line in English.")
