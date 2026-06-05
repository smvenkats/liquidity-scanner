# execution/data/normalize.py
from __future__ import annotations


def from_questrade_candle(c: dict) -> dict:
    """Questrade candle {start,open,high,low,close,volume} -> BarStore row.

    `start` is kept verbatim — Questrade returns it as an exchange-tz ISO string,
    which is what session-grouping (ts.date()) expects.
    """
    return {"ts": c["start"], "o": float(c["open"]), "h": float(c["high"]),
            "l": float(c["low"]), "c": float(c["close"]), "v": float(c["volume"])}


def from_yf_record(rec: dict) -> dict:
    """yfinance record {ts, Open, High, Low, Close, Volume} -> BarStore row."""
    return {"ts": rec["ts"], "o": float(rec["Open"]), "h": float(rec["High"]),
            "l": float(rec["Low"]), "c": float(rec["Close"]), "v": float(rec["Volume"])}
