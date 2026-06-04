# execution/models.py
from __future__ import annotations
from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class Bar:
    ts: datetime
    o: float
    h: float
    l: float
    c: float
    v: float

    @classmethod
    def from_questrade(cls, d: dict) -> "Bar":
        return cls(
            ts=datetime.fromisoformat(d["ts"]),
            o=float(d["o"]), h=float(d["h"]), l=float(d["l"]),
            c=float(d["c"]), v=float(d["v"]),
        )


@dataclass(frozen=True)
class Quote:
    bid: float
    ask: float
    bid_size: float
    ask_size: float

    @property
    def spread(self) -> float:
        return self.ask - self.bid

    @property
    def mid(self) -> float:
        return (self.ask + self.bid) / 2


@dataclass(frozen=True)
class Level:
    pdh: float
    pdl: float
    source_date: date
