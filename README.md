# Policy Assistant: "The Policy That Changed"

A small question-answering assistant over three merchant-policy documents that don't agree with each
other (`ai-2-data/`). It answers **as of a date**, cites real clauses, does its arithmetic in code,
and says `CANNOT_ANSWER` instead of guessing.

## Run it (Python 3.10+, no packages, no API key, no network)

```bash
python -m policy_assistant "A merchant refunds a customer 3 hours after the sale. Do they get the MDR back?" --date 2026-09-05
python -m policy_assistant            # interactive; remembers merchant size so "same merchant" works
python run_eval.py                    # score table over eval.json
python -m unittest discover -s tests  # unit tests
```

From Python:

```python
from policy_assistant import ask
a = ask("Does a refund after 3 hours return the MDR?", "2026-08-20")
a.answer, a.status, a.citations      # status: ANSWERED | CONFLICT_RESOLVED | CANNOT_ANSWER
```

## How it works (short version)

1. **`documents.py`** loads the three files and indexes every clause. A citation can only be created for a
   clause that exists, so a clause number can't be invented.
2. **`rules.py`** is the policy as a timeline: each rule has dated versions
   (e.g. large-merchant MDR cap: Rs.15 until 31 Jul 2026, Rs.25 from 1 Aug 2026). Each version carries a snippet
   that `verify()` checks against the real clause text.
3. **`engine.py`** routes the question to a handler (fees, refunds, limits, settlement, closure, FAQ audit),
   picks the rule versions in force on `as_of_date`, calculates with `Decimal`, writes the answer, and sets the status.
4. **`textparse.py`** pulls amounts, dates, "3 hours", "twice" and merchant size out of the question with regexes.

No LLM is used, so answers are identical on every run.

## What works

- All 8 required questions, including both dates for Q4 (20 Aug: yes, 5 Sep: no).
- Superseded clauses, effective dates (circular D starts 1 Sep, the rest 1 Aug), stale-FAQ detection,
  false premises ("the cap was scrapped"), dates before the policy exists, missing information (card MDR, Annexure C).
- `eval.json`: 18 questions (12 adversarial); `python run_eval.py` currently passes 18/18.
  Passing my own test set does **not** mean it is robust, see `WHERE_IT_BREAKS.md`.

## What doesn't

- It understands questions through hand-written patterns, so unusual phrasing or multi-part questions can be
  misrouted or only half answered.
- Bank holidays aren't in the documents, so exact payout dates (account closure) are given as "deadline if no bank holiday".
- It never computes a settlement date from a sale date.
- Details in `DECISIONS.md` and `WHERE_IT_BREAKS.md`.

## Files

`DECISIONS.md` (every ambiguity and my choice) / `WHERE_IT_BREAKS.md` / `eval.json` / `run_eval.py`
