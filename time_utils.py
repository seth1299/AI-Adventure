"""
Centralized game-time helpers.

Internal canonical representation:
- Day number is 1-based integer (Day 1, Day 2, ...)
- Time-of-day is minutes since midnight (0..1439)
- Absolute time is minutes since Day 1 12:00 AM:
    abs_minutes = (day-1)*1440 + minutes_since_midnight

Supports legacy "time buckets" like "Morning".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Tuple

# Legacy buckets (backwards compatibility)
LEGACY_TIME_TO_CLOCK = {
    "dawn": (6, 0, "AM"),
    "morning": (9, 0, "AM"),
    "noon": (12, 0, "PM"),
    "afternoon": (3, 0, "PM"),
    "evening": (6, 0, "PM"),
    "night": (9, 0, "PM"),
    "late night": (11, 0, "PM"),
    "midnight": (12, 0, "AM"),
}


@dataclass(frozen=True)
class GameTime:
    day: int
    hour: int
    minute: int
    ampm: str

    def as_time_string(self) -> str:
        return format_time(self.hour, self.minute, self.ampm)

    def as_day_string(self) -> str:
        return format_day(self.day)


def clamp_day(day: int) -> int:
    try:
        day = int(day)
    except Exception:
        day = 1
    return max(1, day)


def parse_day(day_str: str) -> int:
    if day_str is None:
        return 1
    s = str(day_str).strip()
    m = re.search(r"(\d+)", s)
    if not m:
        return 1
    return clamp_day(int(m.group(1)))


def format_day(day: int) -> str:
    return f"Day {clamp_day(day)}"


def _to_24h(hour12: int, ampm: str) -> int:
    a = (ampm or "").strip().upper()
    h = int(hour12)
    if a == "AM":
        return 0 if h == 12 else h
    return 12 if h == 12 else h + 12


def _from_24h(hour24: int) -> Tuple[int, str]:
    h = int(hour24) % 24
    if h == 0:
        return (12, "AM")
    if 1 <= h <= 11:
        return (h, "AM")
    if h == 12:
        return (12, "PM")
    return (h - 12, "PM")


def minutes_since_midnight(hour12: int, minute: int, ampm: str) -> int:
    h24 = _to_24h(hour12, ampm)
    m = max(0, min(59, int(minute)))
    return h24 * 60 + m


def clock_from_minutes(mins: int) -> Tuple[int, int, str]:
    mins = int(mins) % 1440
    h24 = mins // 60
    m = mins % 60
    h12, ap = _from_24h(h24)
    return h12, m, ap


def format_time(hour: int, minute: int, ampm: str) -> str:
    ap = (ampm or "AM").strip().upper()
    if ap not in ("AM", "PM"):
        ap = "AM"
    h = int(hour)
    if h < 1 or h > 12:
        h, ap = _from_24h(h)
    m = max(0, min(59, int(minute)))
    return f"{h}:{m:02d} {ap}"


def parse_time(time_str: str) -> Tuple[int, int, str]:
    if not time_str:
        return (12, 0, "AM")

    s = str(time_str).strip()
    s_low = s.lower()

    # legacy buckets
    for bucket, (h, m, ap) in LEGACY_TIME_TO_CLOCK.items():
        if bucket in s_low:
            return (h, m, ap)

    # HH:MM AM/PM
    m = re.match(r"^\s*(\d{1,2})\s*:\s*(\d{1,2})\s*([AaPp][Mm])\s*$", s)
    if m:
        h = max(1, min(12, int(m.group(1))))
        mi = max(0, min(59, int(m.group(2))))
        ap = m.group(3).upper()
        return (h, mi, ap)

    # H AM/PM
    m = re.match(r"^\s*(\d{1,2})\s*([AaPp][Mm])\s*$", s)
    if m:
        h = max(1, min(12, int(m.group(1))))
        ap = m.group(2).upper()
        return (h, 0, ap)

    # 24h like 15:30
    m = re.match(r"^\s*(\d{1,2})\s*:\s*(\d{1,2})\s*$", s)
    if m:
        h24 = int(m.group(1)) % 24
        mi = max(0, min(59, int(m.group(2))))
        h12, ap = _from_24h(h24)
        return (h12, mi, ap)

    return (12, 0, "AM")


def to_abs_minutes(day_str: str, time_str: str) -> int:
    day = parse_day(day_str)
    h, m, ap = parse_time(time_str)
    mins = minutes_since_midnight(h, m, ap)
    return (day - 1) * 1440 + mins


def from_abs_minutes(abs_minutes: int) -> GameTime:
    abs_minutes = max(0, int(abs_minutes))
    day = (abs_minutes // 1440) + 1
    mins = abs_minutes % 1440
    h, m, ap = clock_from_minutes(mins)
    return GameTime(day=day, hour=h, minute=m, ampm=ap)


def add_hours(day_str: str, time_str: str, delta_hours: float) -> GameTime:
    start = to_abs_minutes(day_str, time_str)
    delta_minutes = int(round(float(delta_hours) * 60))
    return from_abs_minutes(start + delta_minutes)


def normalize_day_time(day_str: str, time_str: str):
    d = parse_day(day_str)
    h, m, ap = parse_time(time_str)
    return (format_day(d), format_time(h, m, ap), h, m, ap)
