"""Dates and numbers a story needs, computed from today so the world is always recent."""

from __future__ import annotations

import datetime as dt
import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from investigator.devseed.cast import World


@dataclass
class Ctx:
    now: datetime
    rng: random.Random
    w: World

    @property
    def today(self) -> dt.date:
        return self.now.date()

    def date(self, ago: int) -> dt.date:
        """The date `ago` days before today; a weekend rolls back to Friday."""
        d = self.today - timedelta(days=ago)
        while d.weekday() >= 5:
            d -= timedelta(days=1)
        return d

    def ahead(self, days: int) -> dt.date:
        d = self.today + timedelta(days=days)
        while d.weekday() >= 5:
            d += timedelta(days=1)
        return d

    @staticmethod
    def f(d: dt.date) -> str:
        return f"{d:%b} {d.day}"

    @staticmethod
    def fw(d: dt.date) -> str:
        return f"{d:%A} {d:%b} {d.day}"

    def money(self, lo: int, hi: int, step: int = 1000) -> int:
        return self.rng.randrange(lo, hi, step)

    @staticmethod
    def usd(n: float) -> str:
        return f"${n:,.0f}" if float(n).is_integer() else f"${n:,.2f}"

    def when(self, ago: float, hour: float = 9.0) -> datetime:
        base = datetime.combine(self.today, datetime.min.time(), UTC) - timedelta(
            days=ago
        )
        return base + timedelta(hours=hour + self.rng.uniform(-0.4, 1.2))
