"""The policy as a timeline.

Each rule (e.g. "MDR cap for large merchants") is a list of versions. Every version
says: which value, from which date to which date, and which clause says so.
Answering "as of date X" is then just "pick the version whose dates contain X".

Every version also carries an `evidence` snippet. `verify()` checks that snippet really
appears in the clause text, so the numbers here can't silently drift from the documents.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from . import documents as D

JAN1 = date(2026, 1, 1)    # master v1 effective date
JUL31 = date(2026, 7, 31)
AUG1 = date(2026, 8, 1)    # circular effective date (default)
AUG31 = date(2026, 8, 31)
SEP1 = date(2026, 9, 1)    # circular clause D has its own, later, effective date


class NotInForce(Exception):
    """No version of this rule exists for the requested date."""


@dataclass(frozen=True)
class Version:
    value: object
    start: date
    end: date | None          # last day it applies (inclusive); None = still open
    doc: str
    clause: str
    evidence: str             # text that must appear in the clause
    summary: str              # human wording, used in explanations

    @property
    def ref(self) -> str:
        if self.doc == D.MASTER:
            return f"Master clause {self.clause}"
        return f"Circular MS/2026/17 clause {self.clause}"


def V(*a):  # tiny helper to keep the table below readable
    return Version(*a)


M, C = D.MASTER, D.CIRCULAR
_d = Decimal

RULES: dict[str, list[Version]] = {
    "upi_settlement": [
        V({"default": "T+1", "instant": None}, JAN1, JUL31, M, "1.1", "T+1",
          "UPI settles T+1 (next working day)"),
        V({"default": "T+1", "instant": "T+0"}, AUG1, None, C, "A", "T+0",
          "UPI settles T+0 (same day, by 11:59 PM) with the Instant Settlement add-on, T+1 otherwise"),
    ],
    "card_settlement": [
        V("T+2", JAN1, None, M, "1.2", "T+2", "cards settle T+2"),
    ],
    "volume_threshold": [
        V(_d(1000000), JAN1, None, M, "2.1", "₹10 lakh", "small/large split is ₹10 lakh monthly volume"),
    ],
    "mdr_rate_small": [
        V(_d("0.30"), JAN1, JUL31, M, "2.1", "0.30%", "0.30%"),
        V(_d("0.25"), AUG1, None, C, "B", "0.25%", "0.25%"),
    ],
    "mdr_rate_large": [
        V(_d("0.50"), JAN1, None, M, "2.2", "0.50%", "0.50%"),
    ],
    "mdr_cap_small": [
        V(_d(15), JAN1, JUL31, M, "2.3", "₹15", "₹15 per transaction"),
        V(_d(15), AUG1, None, C, "C", "₹15", "₹15 per transaction (kept for merchants up to ₹10 lakh)"),
    ],
    "mdr_cap_large": [
        V(_d(15), JAN1, JUL31, M, "2.3", "₹15", "₹15 per transaction"),
        V(_d(25), AUG1, None, C, "C", "₹25", "₹25 per transaction (merchants above ₹10 lakh)"),
    ],
    "gst_percent": [
        V(_d(18), JAN1, None, M, "2.4", "18%", "18% GST on the MDR amount"),
    ],
    "refund_reversal_hours": [
        V(_d(24), JAN1, AUG31, M, "3.3", "24 hours", "MDR reversed in full if refund is within 24 hours"),
        V(None, SEP1, None, C, "D", "3.3 is deleted", "clause 3.3 deleted; 3.2 applies with no exception"),
    ],
    "refund_window_days": [
        V(_d(90), JAN1, None, M, "3.1", "90 days", "refund within 90 days of the transaction"),
    ],
    "chargeback_days": [
        V(_d(120), JAN1, None, M, "3.4", "120 days", "customer's bank must raise a chargeback within 120 days"),
    ],
    "per_txn_limit": [
        V(_d(100000), JAN1, None, M, "4.1", "₹1,00,000", "₹1,00,000 per UPI transaction"),
    ],
    "enhanced_txn_limit": [
        V(_d(200000), JAN1, None, M, "4.2", "₹2,00,000", "₹2,00,000 for Capital Markets / Insurance with enhanced KYC"),
    ],
    "daily_limit": [
        V({"cap": _d(100000), "bank": False}, JAN1, JUL31, M, "4.3", "₹1,00,000",
          "₹1,00,000 per customer account per day"),
        V({"cap": _d(100000), "bank": True}, AUG1, None, C, "E", "own bank",
          "₹1,00,000 or the customer's own bank limit, whichever is lower"),
    ],
    "closure_notice_days": [
        V(_d(30), JAN1, None, M, "5.1", "30 days", "30 days written notice to close"),
    ],
    "closure_payout_working_days": [
        V(_d(10), JAN1, None, M, "5.2", "10 working days", "pending settlements released within 10 working days of closure"),
    ],
}


def locate(name: str, as_of: date):
    """Return (previous, current, next) versions of a rule for the given date."""
    versions = RULES[name]
    for i, v in enumerate(versions):
        if v.start <= as_of and (v.end is None or as_of <= v.end):
            prev = versions[i - 1] if i > 0 else None
            nxt = versions[i + 1] if i + 1 < len(versions) else None
            return prev, v, nxt
    raise NotInForce(f"No version of {name!r} applies on {as_of}")


def verify(corpus: D.Corpus | None = None) -> None:
    """Self-check: every rule points at a real clause that really contains its evidence,
    and versions of the same rule line up with no gaps or overlaps."""
    corpus = corpus or D.get_corpus()
    for name, versions in RULES.items():
        for v in versions:
            text = corpus.text(v.doc, v.clause)
            if v.evidence not in text:
                raise AssertionError(f"{name}: {v.doc} {v.clause} does not contain {v.evidence!r}")
        for a, b in zip(versions, versions[1:]):
            if a.end is None or a.end + timedelta(days=1) != b.start:
                raise AssertionError(f"{name}: versions do not join up ({a.end} -> {b.start})")
