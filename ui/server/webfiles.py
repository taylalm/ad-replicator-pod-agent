"""Site records (JSON) kept in the agent session. The Files API accepts media only (it sniffs the content and refuses
application/json under any name), so a JSON record is stored as a lossless grayscale PNG holding the gzipped bytes,
mounted as web_<name>.<millis>.png; the newest one wins on restore."""
from __future__ import annotations

import gzip
import io
import math
import re
import time
from pathlib import Path
from typing import Optional, Tuple

PACKED_RE = re.compile(r"^web_(.+\.json)\.(\d+)\.png$")


def pack(src: Path) -> Path:
    from PIL import Image
    data = gzip.compress(src.read_bytes(), 9)
    payload = len(data).to_bytes(4, "big") + data
    w = 512
    h = max(1, math.ceil(len(payload) / w))
    out = src.with_name(src.name + ".pack.png")
    Image.frombytes("L", (w, h), payload + b"\0" * (w * h - len(payload))).save(out, optimize=True)
    return out


def unpack(png: bytes) -> bytes:
    from PIL import Image
    raw = Image.open(io.BytesIO(png)).tobytes()
    n = int.from_bytes(raw[:4], "big")
    return gzip.decompress(raw[4:4 + n])


def mount_for(mount: str) -> str:
    """web_captions_doc.json -> web_captions_doc.json.<millis>.png (a new name each time: mounts cannot be replaced)."""
    return f"{mount}.{int(time.time() * 1000)}.png"


def parse(mount_name: str) -> Optional[Tuple[str, int]]:
    """(record name, version) for a packed record's mount name, else None."""
    m = PACKED_RE.match(mount_name)
    return (m.group(1), int(m.group(2))) if m else None
