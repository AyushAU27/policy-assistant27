"""Small, boring helpers that pull facts out of the question text:
amounts of money, dates, "3 hours", "twice", merchant size.

No AI here on purpose. Plain regular expressions are predictable and testable.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

LAKH, CRORE = Decimal(100000), Decimal(10000000)


@dataclass(frozen=True)
class Money:
    value: Decimal
    role: str                 # "amount" (a payment), "volume" (monthly volume) or "reference" (e.g. the Rs.15 cap)
    direction: str | None     # "gt" (above/over), "le" (up to/below) or None


# "Rs.4,000", "₹1,50,000", "1.5 lakh", "4000 rupees". A bare number like "3" is NOT money.
_MONEY = re.compile(
    r"(?:(?<![a-z])(?P<cur>₹|rs\.?|inr))?\s*(?P<num>\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<unit>lakhs?|lacs?|crores?)?(?:\s*(?P<rup>rupees|rs\b))?",
    re.I,
)


def find_money(text: str) -> list[Money]:
    found = []
    for m in _MONEY.finditer(text):
        cur, unit, rup = m.group("cur"), m.group("unit"), m.group("rup")
        if not (cur or unit or rup):
            continue
        value = Decimal(m.group("num").rstrip(",").replace(",", ""))
        if unit:
            value *= CRORE if unit.lower().startswith("crore") else LAKH
        before = text[max(0, m.start() - 22):m.start()].lower()
        after = text[m.end():m.end() + 25].lower()
        is_volume = bool(
            re.search(r"monthly|per month|a month|/month|volume|turnover", after)
            or re.search(r"(volume|turnover)( of)?\W*$", before)
        )
        direction = None
        if re.search(r"\b(above|over|more than|exceeding|greater than)\W*$", before):
            direction = "gt"
        elif re.search(r"\b(below|under|less than|up to|upto|at most)\W*$", before):
            direction = "le"
        # "the Rs.15 MDR cap" is a reference to the cap, not a payment amount
        is_cap_ref = bool(re.match(r"\s*(mdr |fee )?cap\b", after))
        role = "volume" if is_volume else ("reference" if is_cap_ref else "amount")
        found.append(Money(value, role, direction))
    return found


def detect_tier(low: str, money: list[Money], context: dict) -> str | None:
    """'small' (up to ₹10 lakh a month), 'large' (above), or None if the question doesn't say."""
    threshold = Decimal(1000000)
    for m in money:
        if m.role != "volume":
            continue
        if m.direction == "gt":
            if m.value >= threshold:
                return "large"
        elif m.direction == "le":
            if m.value <= threshold:
                return "small"
        else:
            return "large" if m.value > threshold else "small"   # exactly 10 lakh is "up to" => small
    if re.search(r"\b(large|big|bigger)\b", low):
        return "large"
    if re.search(r"\bsmall\b", low):
        return "small"
    return context.get("merchant_size")


_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_DATE_PATTERNS = [
    (re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([a-z]{3,9})\.?,?\s+(\d{4})\b", re.I), "dmy"),
    (re.compile(r"\b([a-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", re.I), "mdy"),
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"), "iso"),
]


def find_date(text: str) -> date | None:
    for pattern, kind in _DATE_PATTERNS:
        for m in pattern.finditer(text):
            try:
                if kind == "iso":
                    return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                day, mon, year = ((m.group(1), m.group(2), m.group(3)) if kind == "dmy"
                                  else (m.group(2), m.group(1), m.group(3)))
                month = _MONTHS.get(mon[:3].lower())
                if month:
                    return date(int(year), month, int(day))
            except ValueError:
                continue
    return None


_WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
          "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
_ELAPSED = re.compile(
    r"\b(\d+(?:\.\d+)?|an?|one|two|three|four|five|six|seven|eight|nine|ten)\s*"
    r"(hours?|hrs?|minutes?|mins?|days?)\b", re.I)


def elapsed_hours(low: str) -> Decimal | None:
    """'3 hours after the sale' -> 3. Returns None if no time gap is stated."""
    m = _ELAPSED.search(low)
    if not m:
        return None
    n = Decimal(m.group(1)) if m.group(1)[0].isdigit() else Decimal(_WORDS[m.group(1).lower()])
    unit = m.group(2).lower()
    if unit.startswith("min"):
        return n / 60
    if unit.startswith("day"):
        return n * 24
    return n


def repeat_count(low: str) -> int:
    """'twice' -> 2, 'three times' -> 3, otherwise 1."""
    if re.search(r"\btwice\b|\btwo times\b", low):
        return 2
    if re.search(r"\bthrice\b|\bthree times\b", low):
        return 3
    m = re.search(r"\b(\d+)\s*times\b", low)
    return int(m.group(1)) if m else 1


def relative_date(low: str, as_of: date) -> date | None:
    """'yesterday', 'today', '3 days ago' relative to the as-of date."""
    if "yesterday" in low:
        return as_of - timedelta(days=1)
    if re.search(r"\btoday\b", low):
        return as_of
    m = re.search(r"\b(\d+)\s+days?\s+ago\b", low)
    return as_of - timedelta(days=int(m.group(1))) if m else None
