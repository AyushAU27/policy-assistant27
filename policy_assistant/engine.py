"""The question-answering engine.

Plan (kept deliberately simple):
  1. Work out WHAT is being asked (a small hand-written router: refund? fee? limit? ...).
  2. Look up the rules that apply ON THE as_of_date (rules.py).
  3. Do any arithmetic with Decimal in code (never a language model).
  4. Build the answer text, cite only real clauses, and set the status.

Source ranking used when documents disagree (see DECISIONS.md):
  circular (once in force)  >  master policy  >  FAQ (never overrides a policy clause)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from . import documents as D
from . import rules
from .documents import Citation
from .textparse import (detect_tier, elapsed_hours, find_date, find_money,
                        relative_date, repeat_count)

ANSWERED = "ANSWERED"
CONFLICT_RESOLVED = "CONFLICT_RESOLVED"
CANNOT_ANSWER = "CANNOT_ANSWER"

DEFAULT_AS_OF = date(2026, 8, 15)
POLICY_START = date(2026, 1, 1)



def _group_indian(n: int) -> str:
    s = str(n)
    if len(s) <= 3:
        return s
    head, tail = s[:-3], s[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return ",".join(parts + [tail])


def inr(x, decimals: int | None = None) -> str:
    """₹1,50,000 / ₹3.60 -- Indian digit grouping."""
    x = Decimal(x)
    if decimals is None:
        decimals = 0 if x == x.to_integral_value() else 2
    q = x.quantize(Decimal(1) if decimals == 0 else Decimal("0.01"), ROUND_HALF_UP)
    whole, _, frac = f"{q:f}".partition(".")
    return "₹" + _group_indian(int(whole)) + (f".{frac}" if decimals else "")


def fdate(d: date, weekday: bool = False) -> str:
    s = f"{d.day} {d.strftime('%b %Y')}"
    return f"{d.strftime('%a')} {s}" if weekday else s


def _q2(x: Decimal) -> Decimal:
    return x.quantize(Decimal("0.01"), ROUND_HALF_UP)



@dataclass
class Answer:
    question: str
    as_of_date: date
    answer: str
    status: str
    citations: list[Citation] = field(default_factory=list)
    resolution: str | None = None
    context: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "question": self.question,
            "as_of_date": self.as_of_date.isoformat(),
            "answer": self.answer,
            "status": self.status,
            "resolution": self.resolution,
            "citations": [c.to_dict() for c in self.citations],
        }

    def __str__(self) -> str:
        out = [f"Status : {self.status}   (as of {fdate(self.as_of_date)})", "", self.answer]
        if self.resolution:
            out += ["", f"How the conflict was resolved: {self.resolution}"]
        if self.citations:
            out += ["", "Citations:"]
            out += [f"  - [{c.role}] {c.label()}" for c in self.citations]
        return "\n".join(out)



_RANK = {"applied": 0, "superseded": 1, "upcoming": 2, "context": 3}


class Trace:
    """Collects citations and conflict notes while we build one answer."""

    def __init__(self, as_of: date):
        self.as_of = as_of
        self.cites: dict[tuple[str, str], Citation] = {}
        self.notes: list[str] = []
        self.conflict = False
        self.carry: dict = {}

    def cite(self, doc: str, clause: str, role: str = "applied") -> None:
        c = D.get_corpus().cite(doc, clause, role)
        old = self.cites.get((doc, clause))
        if old is None or _RANK[role] < _RANK[old.role]:
            self.cites[(doc, clause)] = c

    def use(self, name: str) -> rules.Version:
        """Fetch the version of a rule in force on as_of, cite it, and record any change around it."""
        prev, cur, nxt = rules.locate(name, self.as_of)
        self.cite(cur.doc, cur.clause, "applied")
        if prev is not None and prev.value != cur.value:
            self.cite(prev.doc, prev.clause, "superseded")
            self.conflict = True
            self.notes.append(
                f"{prev.ref} ({prev.summary}) applied until {fdate(prev.end)}; "
                f"{cur.ref} ({cur.summary}) applies from {fdate(cur.start)}, so the newer text is used.")
        if nxt is not None and nxt.value != cur.value:
            self.cite(nxt.doc, nxt.clause, "upcoming")
            self.conflict = True
            self.notes.append(
                f"{nxt.ref} ({nxt.summary}) only takes effect on {fdate(nxt.start)}, "
                f"so on {fdate(self.as_of)} the current text ({cur.ref}) still applies.")
        return cur

    def finish(self, text: str, status: str | None = None, extra_resolution: str | None = None) -> Answer:
        status = status or (CONFLICT_RESOLVED if self.conflict else ANSWERED)
        notes = list(self.notes) + ([extra_resolution] if extra_resolution else [])
        order = sorted(self.cites.values(), key=lambda c: _RANK[c.role])
        return Answer("", self.as_of, text, status, order,
                      resolution=" ".join(notes) if status == CONFLICT_RESOLVED and notes else None,
                      context=self.carry)


def cannot(as_of: date, why: str, cites: list[Citation] | None = None) -> Answer:
    return Answer("", as_of, why, CANNOT_ANSWER, cites or [])



@dataclass
class Q:
    raw: str
    low: str
    as_of: date
    amounts: list
    tier: str | None
    context: dict



def _tier_label(tier: str, as_of: date) -> str:
    return ("a large merchant (monthly UPI volume above ₹10 lakh)" if tier == "large"
            else "a small merchant (monthly UPI volume up to ₹10 lakh)")


def calc_mdr(amount: Decimal, tier: str, t: Trace) -> str:
    rate = t.use("mdr_rate_small" if tier == "small" else "mdr_rate_large")
    cap = t.use("mdr_cap_small" if tier == "small" else "mdr_cap_large")
    gst = t.use("gst_percent")
    t.use("volume_threshold")
    raw = amount * rate.value / 100
    capped = raw > cap.value
    mdr = _q2(min(raw, cap.value))
    gst_amt = _q2(mdr * gst.value / 100)
    total = mdr + gst_amt
    if capped:
        mdr_line = (f"MDR: {rate.value:.2f}% of {inr(amount)} would be {inr(_q2(raw))}, but the MDR cap "
                    f"is {inr(cap.value)} per transaction, so MDR = {inr(mdr, 2)}.")
    elif raw == cap.value:
        mdr_line = (f"MDR: {rate.value:.2f}% of {inr(amount)} = {inr(mdr, 2)}, which is exactly the "
                    f"{inr(cap.value)} cap.")
    else:
        mdr_line = (f"MDR: {rate.value:.2f}% of {inr(amount)} = {inr(mdr, 2)} "
                    f"(under the {inr(cap.value)} cap, so the cap does not apply).")
    return (f"For {_tier_label(tier, t.as_of)} on a {inr(amount)} UPI payment:\n"
            f"  {mdr_line}\n"
            f"  GST: {gst.value:.0f}% of the MDR = {inr(gst_amt, 2)} (GST sits on top of the cap, clause 2.4).\n"
            f"  Total deducted: {inr(total, 2)}.")


def limit_note(amount: Decimal, t: Trace) -> str:
    one = t.use("per_txn_limit").value
    two = t.use("enhanced_txn_limit").value
    if amount <= one:
        return ""
    t.cite(D.MASTER, "4.4")
    if amount <= two:
        return (f"\n\nHeads-up: {inr(amount)} is above the {inr(one)} per-transaction UPI limit (clause 4.1). "
                f"Only Capital Markets or Insurance merchants who completed enhanced KYC can accept up to "
                f"{inr(two)} (clauses 4.2 and 4.4). For any other merchant this payment is not allowed, "
                f"and the fee above only applies if the payment is allowed.")
    return (f"\n\nHeads-up: {inr(amount)} is above even the {inr(two)} enhanced limit (clauses 4.1, 4.2), "
            f"so the payment itself would not be allowed. The fee above is only the arithmetic.")


def mdr_intent(q: Q, t: Trace) -> Answer:
    low = q.low
    if re.search(r"\bcards?\b|credit|debit|net ?banking|wallet|rupay|international|foreign", low) \
            and "upi" not in low:
        return cannot(q.as_of, "The documents only define MDR for UPI transactions (master clauses 2.1 to 2.4). "
                               "They say nothing about MDR or fees for card or other payment methods, "
                               "so I can't answer this without guessing.")
    prefix = ""
    cap_words = re.search(r"\b(cap|ceiling|upper limit)\b", low)
    if cap_words and re.search(r"removed|scrapped|abolish|eliminated|no longer|discontinued|withdrawn|"
                               r"\bno cap\b|doesn.?t exist|does not exist", low):
        cs, cl = t.use("mdr_cap_small"), t.use("mdr_cap_large")
        t.cite(D.MASTER, "2.3")
        if cs.value == cl.value:
            prefix = (f"Small correction first: the MDR cap has not been removed. Master clause 2.3 still caps "
                      f"MDR at {inr(cs.value)} per transaction on this date.\n\n")
        else:
            prefix = (f"Small correction first: the MDR cap has not been removed. Circular clause C changed it "
                      f"from {inr(15)} for everyone to {inr(cs.value)} for merchants up to ₹10 lakh a month and "
                      f"{inr(cl.value)} for merchants above ₹10 lakh.\n\n")
    tiers = [q.tier] if q.tier else ["small", "large"]
    if q.amounts:
        amount = q.amounts[0].value
        blocks = [calc_mdr(amount, tr, t) for tr in tiers]
        text = prefix + "\n\n".join(blocks)
        if not q.tier:
            text += ("\n\nThe question doesn't say whether the merchant is small or large, "
                     "so both are shown.")
        text += limit_note(amount, t)
    else:
        parts = []
        for tr in tiers:
            rate = t.use("mdr_rate_small" if tr == "small" else "mdr_rate_large")
            cap = t.use("mdr_cap_small" if tr == "small" else "mdr_cap_large")
            parts.append(f"{tr.capitalize()} merchants ({'up to' if tr == 'small' else 'above'} ₹10 lakh a month): "
                         f"MDR {rate.value:.2f}% of the transaction value, capped at {inr(cap.value)} per "
                         f"transaction, plus 18% GST on the MDR.")
        t.use("gst_percent")
        text = prefix + "\n".join(parts)
    if q.tier:
        t.carry["merchant_size"] = q.tier
    return t.finish(text)



def refund_intent(q: Q, t: Trace) -> Answer:
    low = q.low
    if re.search(r"how long|deadline|window|last date|time limit|by when|within how|how many days", low) \
            and not re.search(r"\bmdr\b|fee", low):
        v = t.use("refund_window_days")
        return t.finish(f"A refund can be initiated within {v.value:.0f} days of the original transaction (clause 3.1).")
    v = t.use("refund_reversal_hours")
    t.cite(D.MASTER, "3.2")
    elapsed = elapsed_hours(low)
    faq_q = "If a customer asks for a refund the same day, do I get my fee back?"
    if elapsed is not None and elapsed > 90 * 24:
        v90 = t.use("refund_window_days")
        return t.finish(f"A refund {elapsed / 24:.0f} days after the sale is outside the {v90.value:.0f}-day "
                        f"refund window (clause 3.1), so it can't be initiated at all.")
    if v.value is None:
        t.cite(D.FAQ, faq_q, "context")
        text = (f"No. Clause 3.3 (the 24-hour full reversal) was deleted by Circular clause D from "
                f"{fdate(rules.SEP1)}, and clause 3.2 now applies without exception: the MDR charged on a "
                f"refunded transaction is not returned, however quickly you refund.")
        if elapsed is not None:
            text += f" So a refund after {elapsed:g} hours gets no MDR back."
        text += (" The March 2026 FAQ still says the fee is reversed, but that answer is out of date from "
                 "that date.")
        return t.finish(text)
    window = v.value
    base = f"On {fdate(q.as_of)} clause 3.3 is still in force"
    if elapsed is None:
        text = (f"{base}: if you refund within {window:.0f} hours of the sale, the MDR is reversed in full. "
                f"After {window:.0f} hours it is not returned (clause 3.2). "
                f"Note: from {fdate(rules.SEP1)} clause 3.3 is deleted and the MDR is never returned.")
    elif elapsed <= window:
        text = (f"Yes. {base}, and a refund after {elapsed:g} hours is inside the {window:.0f}-hour window, "
                f"so the MDR is reversed in full (clause 3.3). "
                f"Be aware this only holds until {fdate(rules.AUG31)}; from {fdate(rules.SEP1)} the same "
                f"refund would get no MDR back.")
    else:
        text = (f"No. {base}, but a refund after {elapsed:g} hours is outside the {window:.0f}-hour window, "
                f"so the MDR is not returned (clause 3.2).")
    return t.finish(text)



def settlement_intent(q: Q, t: Trace) -> Answer:
    low = q.low
    has_card = bool(re.search(r"\bcards?\b|credit|debit", low))
    has_upi = "upi" in low
    same_day = bool(re.search(r"same.?day|instant|t\+0|immediately|today", low))
    parts = []
    if has_card or not has_upi:
        card = t.use("card_settlement")
        if same_day and has_card:
            t.cite(D.CIRCULAR, "A", "context")
            parts.append(f"No. The documents give card payments one settlement time: {card.value} "
                         f"(clause 1.2), with no same-day option. The T+0 'Instant Settlement' add-on in "
                         f"Circular clause A is written for UPI settlement only, so it does not extend to cards.")
        else:
            parts.append(f"Card payments settle {card.value} (clause 1.2).")
    if has_upi or not has_card:
        upi = t.use("upi_settlement")
        t.cite(D.MASTER, "1.3")
        d = upi.value
        if d["instant"]:
            s = (f"UPI payments settle T+1 (the next working day) by default. Merchants with an active "
                 f"'Instant Settlement' add-on get T+0: the same day, by 11:59 PM (Circular clause A, in force "
                 f"since {fdate(rules.AUG1)}).")
            t.cite(D.FAQ, "When will I get my UPI money?", "context")
        else:
            s = ("UPI payments settle T+1 (the next working day). Same-day T+0 settlement did not exist yet "
                 f"on {fdate(q.as_of)}: the Instant Settlement add-on starts on {fdate(rules.AUG1)}.")
        s += " If the settlement date is a bank holiday, it moves to the next working day (clause 1.3)."
        if q.tier:
            s += " Merchant size does not change settlement timing in these documents."
        parts.append(s)
    return t.finish("\n".join(parts))



def limit_intent(q: Q, t: Trace) -> Answer:
    low = q.low
    one = t.use("per_txn_limit").value
    daily_q = bool(re.search(r"daily|per day|a day|in one day|in a day|same day|twice|two times|thrice|"
                             r"\d+ times|three times", low))
    amounts = [m.value for m in q.amounts]
    if daily_q:
        dl = t.use("daily_limit").value
        cap = dl["cap"]
        bank = (" It can be lower: from 1 Aug 2026 it is the lower of this and the limit set by the "
                "customer's own bank, which the documents don't give me.") if dl["bank"] else ""
        if amounts:
            total = sum(amounts) * repeat_count(low)
            if total <= cap:
                text = (f"Yes, within the daily limit. The daily limit per customer account is {inr(cap)} "
                        f"across all UPI transactions (clause 4.3) and these payments total {inr(total)}.{bank}")
            elif len(amounts) == 1 and repeat_count(low) == 1:
                t.cite(D.MASTER, "4.2")
                text = (f"Not clearly. {inr(total)} is more than the {inr(cap)} daily limit per customer account "
                        f"(clause 4.3), which on its face blocks it. But clause 4.2 lets Capital Markets and "
                        f"Insurance merchants with enhanced KYC accept {inr(total)} in one transaction, and the "
                        f"documents never say whether those merchants are exempt from the daily cap. I can't "
                        f"settle that from the text.{bank}")
                return t.finish(text)
            else:
                text = (f"No. The daily limit per customer account is {inr(cap)} across ALL UPI transactions "
                        f"(clause 4.3). These payments total {inr(total)}, so the first {inr(cap)} payment uses "
                        f"up the whole day's limit and the next one would be declined. Each single payment is "
                        f"fine on its own (per-transaction limit {inr(one)}, clause 4.1); the daily cap is what "
                        f"stops it.{bank}")
        else:
            text = f"The daily limit per customer account is {inr(cap)} across all UPI transactions (clause 4.3).{bank}"
        return t.finish(text)

    two = t.use("enhanced_txn_limit").value
    if amounts:
        amount = amounts[0]
        t.cite(D.MASTER, "4.4")
        if amount <= one:
            text = f"Yes, {inr(amount)} is within the {inr(one)} per-transaction UPI limit (clause 4.1)."
        elif amount <= two:
            text = (f"Only for some merchants. {inr(amount)} is above the standard {inr(one)} per-transaction "
                    f"limit (clause 4.1). Merchants in Capital Markets or Insurance may accept up to {inr(two)} "
                    f"(clause 4.2), but only if they completed enhanced KYC (clause 4.4). Any other merchant "
                    f"cannot accept it.")
        else:
            text = (f"No. {inr(amount)} is above even the enhanced {inr(two)} limit (clause 4.2), "
                    f"so no merchant category in these documents can accept it.")
    else:
        text = (f"The per-transaction UPI limit is {inr(one)} (clause 4.1). Merchants in Capital Markets and "
                f"Insurance may accept up to {inr(two)} (clause 4.2) if they completed enhanced KYC (clause 4.4).")
    text += (f"\n\nOpen point: the enhanced {inr(two)} limit (clause 4.2) and the {inr(one)} daily limit per "
             f"customer account (clause 4.3) seem to clash, and the documents don't say whether enhanced "
             f"merchants are exempt from the daily cap. I can't resolve that from the text.")
    t.cite(D.MASTER, "4.3")
    return t.finish(text)



def add_working_days(start: date, n: int, holidays: frozenset = frozenset()) -> date:
    """Policy (clause 1.1) says working days exclude Sundays and bank holidays. No holiday list is
    provided, so by default only Sundays are skipped (Saturdays count)."""
    d, count = start, 0
    while count < n:
        d += timedelta(days=1)
        if d.weekday() == 6 or d in holidays:
            continue
        count += 1
    return d


def closure_intent(q: Q, t: Trace) -> Answer:
    notice = t.use("closure_notice_days").value
    days = int(t.use("closure_payout_working_days").value)
    t.cite(D.MASTER, "1.1", "context")
    closed_on = relative_date(q.low, q.as_of)
    only_notice = bool(re.search(r"\bnotice\b", q.low)) and not closed_on
    if only_notice:
        return t.finish(f"Closing the account needs {notice:.0f} days' written notice (clause 5.1). "
                        f"Pending settlements are then released within {days} working days of closure, "
                        f"after deducting outstanding dues (clause 5.2).")
    text = (f"Pending settlements are released within {days} working days of closure, after outstanding dues "
            f"are deducted (clause 5.2).")
    if closed_on:
        deadline = add_working_days(closed_on, days)
        text += (f"\n\nIf the account was closed on {fdate(closed_on, True)}, counting {days} working days "
                 f"(Sundays skipped; Saturdays counted because the policy only excludes Sundays and bank "
                 f"holidays), the deadline is {fdate(deadline, True)}. That is the date if no bank holiday "
                 f"falls in between. The documents don't include a holiday calendar, so every bank holiday "
                 f"in that stretch pushes the date back by one working day, and I can't give an exact day "
                 f"without that list.")
        text += (f"\n\nOne thing to check: clause 5.1 requires {notice:.0f} days' written notice. If "
                 f"yesterday was the day you GAVE notice, the account isn't closed yet, and the "
                 f"{days}-working-day clock only starts when it actually closes.")
    return t.finish(text)



def chargeback_intent(q: Q, t: Trace) -> Answer:
    v = t.use("chargeback_days")
    return t.finish(f"A chargeback dispute must be raised by the customer's bank within {v.value:.0f} days "
                    f"(clause 3.4). The documents don't say how long the merchant then has to respond.")



FAQ_Q = {
    "fee": "What do I pay on a UPI transaction?",
    "refund": "If a customer asks for a refund the same day, do I get my fee back?",
    "settlement": "When will I get my UPI money?",
    "limit": "What is the maximum amount a customer can pay at my shop?",
    "closure": "Can I close my account any time?",
}
FAQ_TOPICS = {
    "fee": r"\bmdr\b|\bfees?\b|\bcap\b|upper limit|ceiling|0\.30|0\.50|\bcharges?\b|pay on a upi",
    "refund": r"refund",
    "settlement": r"settle|\bt\+|when will i get|upi money",
    "limit": r"maximum amount|per.transaction|capital markets|insurance|1,00,000|2,00,000|customer can pay",
    "closure": r"\bclos",
}


def _audit(topic: str, t: Trace) -> tuple[str, str]:
    """Return (verdict, explanation) for one FAQ entry on t.as_of."""
    if topic == "fee":
        rs, cs, cl = t.use("mdr_rate_small"), t.use("mdr_cap_small"), t.use("mdr_cap_large")
        t.use("mdr_rate_large")
        t.cite(D.MASTER, "2.3")
        why = ("The FAQ says there is no upper limit on the fee. That is wrong: master clause 2.3 has capped "
               "MDR at ₹15 per transaction since 1 Jan 2026, which is before the FAQ was even written "
               "(12 Mar 2026).")
        if cs.value == cl.value:
            why += f" On {fdate(t.as_of)} the cap is {inr(cs.value)} for everyone."
        else:
            why += (f" On {fdate(t.as_of)} the cap is {inr(cs.value)} for merchants up to ₹10 lakh a month "
                    f"and {inr(cl.value)} above that (Circular clause C).")
        if rs.value != Decimal("0.30"):
            why += (f" Also, the 0.30% small-merchant rate in the FAQ is outdated: it is "
                    f"{rs.value:.2f}% from {fdate(rules.AUG1)} (Circular clause B). The 0.50% large-merchant "
                    f"rate is still right.")
        else:
            why += " The 0.30% and 0.50% rates are right on this date (but 0.30% drops to 0.25% on 1 Aug 2026)."
        return "WRONG", why
    if topic == "refund":
        v = t.use("refund_reversal_hours")
        t.cite(D.MASTER, "3.2")
        if v.value is None:
            return "OUTDATED", ("The FAQ says a refund within 24 hours gets the fee back. That stopped being true "
                                f"on {fdate(rules.SEP1)}, when Circular clause D deleted clause 3.3. Now clause "
                                "3.2 applies with no exception, so the fee is not returned.")
        return "CORRECT", (f"Right on {fdate(t.as_of)} (clause 3.3), but it expires after {fdate(rules.AUG31)}: "
                           f"from {fdate(rules.SEP1)} Circular clause D deletes the reversal.")
    if topic == "settlement":
        u = t.use("upi_settlement")
        t.use("card_settlement")
        if u.value["instant"]:
            return "INCOMPLETE", ("'Next working day' for UPI is still the default and card T+2 is right, but since "
                                  f"{fdate(rules.AUG1)} merchants with the Instant Settlement add-on get T+0 "
                                  "(Circular clause A), which the FAQ doesn't mention.")
        return "CORRECT", "UPI T+1 (clause 1.1) and card T+2 (clause 1.2) both match the policy on this date."
    if topic == "limit":
        t.use("per_txn_limit")
        t.use("enhanced_txn_limit")
        t.cite(D.MASTER, "4.4")
        return "INCOMPLETE", ("The amounts match clauses 4.1 and 4.2, but the FAQ leaves out that the ₹2,00,000 "
                              "limit needs enhanced KYC (clause 4.4). It also doesn't mention the daily limit per "
                              "customer account (clause 4.3).")
    t.use("closure_notice_days")
    t.use("closure_payout_working_days")
    return "INCOMPLETE", ("30 days' notice matches clause 5.1. But the FAQ says money comes 'within 10 days'; the "
                          "policy says 10 WORKING days, after outstanding dues are deducted (clause 5.2). And "
                          "'any time' still needs the 30 days' notice.")


def faq_intent(q: Q, t: Trace) -> Answer:
    topics = [k for k, pat in FAQ_TOPICS.items() if re.search(pat, q.low)]
    if "fee" in topics and "limit" in topics and re.search(r"upper limit|\bcap\b", q.low) \
            and not re.search(r"maximum amount|per.transaction|capital markets|insurance", q.low):
        topics.remove("limit")
    topics = topics or list(FAQ_Q)
    corpus = D.get_corpus()
    out, bad = [], False
    for k in topics:
        verdict, why = _audit(k, t)
        t.cite(D.FAQ, FAQ_Q[k], "context")
        bad |= verdict != "CORRECT"
        out.append(f'FAQ says: "{corpus.text(D.FAQ, FAQ_Q[k])}"\nIs it right on {fdate(t.as_of)}? {verdict}. {why}')
    t.conflict = bad or t.conflict
    resolution = ("The FAQ is a plain-language summary dated 12 Mar 2026; where it disagrees with the master "
                  "policy or the circular (by effective date), the policy documents win.")
    return t.finish("\n\n".join(out), extra_resolution=resolution)



def route(q: Q, t: Trace) -> Answer:
    low = q.low
    if re.search(r"\bfaq\b", low):
        return faq_intent(q, t)
    if re.search(r"annexure|\bkyc\b", low) and re.search(r"document|require|need|steps|how to|process|complete|apply", low):
        return cannot(q.as_of, "Clause 4.4 says enhanced KYC is 'Annexure C', but Annexure C is not part of the "
                               "documents I have, so I can't say what it requires.",
                      [D.get_corpus().cite(D.MASTER, "4.4", "context")])
    if re.search(r"\bclos(e|ed|ing|ure)\b", low):
        return closure_intent(q, t)
    if re.search(r"chargebacks?|\bdispute", low):
        return chargeback_intent(q, t)
    if "refund" in low:
        return refund_intent(q, t)
    if re.search(r"\bmdr\b|merchant discount|\bgst\b|\bfees?\b|\bcharges?\b|\bcost|\bcap\b|ceiling|"
                 r"what (do|does|will|would|did) (they|i|we|the merchant|a merchant) pay", low):
        return mdr_intent(q, t)
    if re.search(r"limit|maximum|\bmax\b|how much can|can (a|the) customer pay|twice|two times|\d+ times|"
                 r"per day|daily|in one day|in a day|allowed|accept up to", low):
        return limit_intent(q, t)
    if re.search(r"settle|receive|get paid|payout|credited|money|t\+[012]|same.?day", low):
        return settlement_intent(q, t)
    return cannot(q.as_of, "I couldn't match this to anything in the three documents (settlement, UPI MDR and "
                           "GST, refunds, chargebacks, transaction limits, account closure), so I won't guess.")


def ask(question: str, as_of_date=None, context: dict | None = None) -> Answer:
    """Answer `question` using the rules in force on `as_of_date`.

    as_of_date: a date, an ISO string, or None (then a date in the question is used,
    otherwise 15 Aug 2026 as the assignment specifies).
    context: facts from an earlier question, e.g. {"merchant_size": "large"} for "same merchant".
    """
    context = dict(context or {})
    if isinstance(as_of_date, str):
        as_of_date = date.fromisoformat(as_of_date)
    as_of = as_of_date or find_date(question) or DEFAULT_AS_OF
    low = question.lower()
    if as_of < POLICY_START:
        ans = cannot(as_of, f"The earliest document (master policy v1.0) takes effect on {fdate(POLICY_START)}. "
                            f"I have no policy text for {fdate(as_of)}, so I can't answer for that date.")
    else:
        money = find_money(question)
        q = Q(question, low, as_of, [m for m in money if m.role == "amount"],
              detect_tier(low, money, context), context)
        try:
            ans = route(q, Trace(as_of))
        except rules.NotInForce as e:
            ans = cannot(as_of, str(e))
    ans.question = question
    return ans


class Conversation:
    """Remembers small facts between questions, so 'same merchant' works."""

    def __init__(self):
        self.context: dict = {}

    def ask(self, question: str, as_of_date=None) -> Answer:
        ans = ask(question, as_of_date, self.context)
        self.context.update(ans.context)
        return ans
