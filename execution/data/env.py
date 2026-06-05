# execution/data/env.py
"""Minimal dependency-free .env loader.

The Questrade client reads QUESTRADE_REFRESH_TOKEN / QUESTRADE_TOKEN_CACHE from
os.environ. Entry points (the backfill CLI, the live smoke test) call load_dotenv()
first so a token placed in the project-root .env reaches the client. Existing
environment variables always win (setdefault), so a real shell export is never
overridden.
"""
from __future__ import annotations
import os
from pathlib import Path

_DEFAULT = Path(__file__).resolve().parents[2] / ".env"


def load_dotenv(path=None) -> None:
    path = Path(path) if path else _DEFAULT
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, val)
