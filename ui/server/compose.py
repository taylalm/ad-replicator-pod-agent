"""Compose the user message that starts a job. The agent parses the labelled lines."""
from __future__ import annotations

import re


def one_line(text: str) -> str:
    text = (text or "").strip()
    text = re.sub(r"\s*\n\s*", " / ", text)
    return re.sub(r"\s{2,}", " ", text)


def cap(value) -> str:
    try:
        v = int(value)
    except (TypeError, ValueError):
        v = 0
    return f"<= {v}" if v > 0 else "no cap"


def compose_message(sample_url: str, product_url: str, requirements: str, budget: dict, options: dict,
                    auto_approve: bool = False, step_approve: bool = False, references: list = None) -> str:
    length_s = int((options or {}).get("length_s") or 20)
    resolution = (options or {}).get("resolution") or "480p"
    if resolution not in ("480p", "720p"):
        resolution = "480p"
    captions = (options or {}).get("captions") or "full"
    if captions not in ("full", "cta_only", "none"):
        captions = "full"
    req = one_line(requirements)
    output_note = f"Output: about {length_s} s, {resolution}, 9:16 vertical."
    if "Output:" not in req:
        req = f"{req} / {output_note}" if req else output_note
    lines = [
        f"SAMPLE_VIDEO: {sample_url.strip()}",
        f"PRODUCT_URL: {product_url.strip()}",
        f"REQUIREMENTS: {req}",
        (f"BUDGET: Seedream images {cap(budget.get('seedream'))}, "
         f"Seedance tasks {cap(budget.get('seedance'))}, evaluator calls {cap(budget.get('evaluator'))}"),
        f"AUTO_APPROVE: {'yes' if auto_approve else 'no'}",
        f"STEP_APPROVE: {'yes' if step_approve else 'no'}",
        f"CAPTIONS: {captions}",
    ]
    for r in references or []:
        name = (r.get("mount_name") or r.get("filename") or "").strip()
        if name:
            lines.append(f"REFERENCES: /mnt/session/uploads/{name} ({one_line(r.get('note') or r.get('kind') or 'reference')})")
    return "\n".join(lines)
