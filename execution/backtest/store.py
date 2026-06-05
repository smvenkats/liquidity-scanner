from __future__ import annotations
import json
from pathlib import Path
from datetime import date
from execution.models import Bar


class BarStore:
    """Loads cached OHLCV bar files named '{SYMBOL}_{tf}.json' from a directory.

    This is the single swap point for data sources: a bulk vendor only needs to
    produce the same files (or subclass and override `bars`).
    """

    def __init__(self, root):
        self.root = Path(root)
        self._cache: dict[tuple[str, str], list[Bar]] = {}

    def bars(self, symbol: str, tf: str) -> list[Bar]:
        if "/" in symbol or "\\" in symbol or symbol.startswith("."):
            return []   # reject path-traversal in the symbol (e.g. from the /bars endpoint)
        key = (symbol, tf)
        if key not in self._cache:
            path = self.root / f"{symbol}_{tf}.json"
            if not path.exists():
                self._cache[key] = []
            else:
                rows = json.loads(path.read_text())
                self._cache[key] = sorted((Bar.from_questrade(r) for r in rows), key=lambda b: b.ts)
        return self._cache[key]

    def sessions(self, symbol: str) -> list[date]:
        seen = sorted({b.ts.date() for b in self.bars(symbol, "5m")})
        return seen
