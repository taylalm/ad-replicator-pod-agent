"""Filesystem locations and the ma_client import (by path, so the repo layout stays as is)."""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent
UI_DIR = SERVER_DIR.parent
REPO = UI_DIR.parent
RUNS_DIR = REPO / "runs"
# UI_DATA_DIR: writable job cache (serverless: /tmp/...); jobs are rebuilt from the ModelArk sessions when it is empty
DATA_DIR = Path(os.environ.get("UI_DATA_DIR") or (UI_DIR / "data" / "jobs"))
TOOLS_DIR = REPO / "tools"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_ma_client = None


def ma_client():
    """tools/ma_client.py, loaded lazily (it only needs the API key when a Client is built)."""
    global _ma_client
    if _ma_client is None:
        _ma_client = load_module("ma_client", TOOLS_DIR / "ma_client.py")
    return _ma_client
