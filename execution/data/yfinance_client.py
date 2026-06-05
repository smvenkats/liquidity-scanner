# execution/data/yfinance_client.py
"""yfinance backup source. 1h/1d ONLY — Yahoo caps intraday history (~60d for 5m),
so 5m is never sourced here (it would silently truncate the research series)."""
from __future__ import annotations
import warnings
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from execution.data.normalize import from_yf_record

ET = ZoneInfo("America/New_York")
_YF_INTERVAL = {"1h": "60m", "1d": "1d"}
_MAX_DAYS = {"1h": 725, "1d": None}  # Yahoo horizon caps (None = full history);
# 1h uses 725 not 730 — Yahoo rejects a range landing exactly on the 730-day edge.


def _raw_download(symbol: str, start: datetime, end: datetime, interval: str) -> list[dict]:
    """Real Yahoo download isolated for testability. Returns plain records
    {ts(iso, ET), Open, High, Low, Close, Volume}. Not unit-tested (see live smoke)."""
    import yfinance as yf
    df = yf.download(symbol, start=start.date().isoformat(), end=end.date().isoformat(),
                     interval=interval, auto_adjust=False, progress=False)
    if df is None or df.empty:
        return []
    if hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
        df = df.droplevel(axis=1, level=1)  # single-ticker MultiIndex -> flat
    out = []
    for idx, row in df.iterrows():
        ts = idx.to_pydatetime()
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=ET)
        out.append({"ts": ts.astimezone(ET).isoformat(),
                    "Open": row["Open"], "High": row["High"], "Low": row["Low"],
                    "Close": row["Close"], "Volume": row["Volume"]})
    return out


def fetch(symbol: str, tf: str, start: datetime, end: datetime) -> list[dict]:
    if tf not in _YF_INTERVAL:
        raise ValueError(f"yfinance backup supports only 1h/1d, got {tf!r}")
    cap = _MAX_DAYS[tf]
    if cap is not None:
        earliest = end - timedelta(days=cap)
        if start < earliest:
            warnings.warn(f"yfinance {tf}: clamping start {start.date()} -> {earliest.date()} "
                          f"(Yahoo {cap}-day horizon)")
            start = earliest
    raw = _raw_download(symbol, start, end, _YF_INTERVAL[tf])
    return [from_yf_record(r) for r in raw]
