# Decisions: every ambiguity I hit, what I chose, and why

## A. Which document wins?
1. **Ranking: circular (once in force) > master policy > FAQ.** The circular says it amends the master; the FAQ is a
   plain-language summary dated 12 Mar 2026 and has no clause numbers. The FAQ never overrides a policy clause.
2. **The FAQ was wrong even on the day it was written.** It says the fee has "no upper limit", but master 2.3 has capped
   MDR at Rs.15 since 1 Jan 2026. So "stale" isn't the whole story for that entry; it is simply incorrect.

## B. Dates
3. **`as_of_date` = the date the thing happens** (the refund, the payment, the question). For refunds I apply the rule in
   force on the *refund* date, not the sale date. So a sale on 31 Aug refunded on 1 Sep gets no MDR back.
   The circular doesn't say which date counts; this is my reading.
4. **Circular D starts 1 Sep 2026; the other clauses start 1 Aug.** The header says "1 August unless stated otherwise" and D states 1 Sep.
   Both ends are inclusive in code (3.3 applies through 31 Aug).
5. **Default date 15 Aug 2026** (as the assignment says) when no date is passed; a date written in the question is used if no argument is given.
6. **Dates before 1 Jan 2026 -> CANNOT_ANSWER**: no document is in force.

## C. Arithmetic
7. **10 lakh boundary:** "up to Rs.10 lakh" is inclusive, so exactly Rs.10 lakh = small; "above" is strictly more.
8. **Order:** MDR = rate x amount, then capped, then GST 18% on the capped MDR (2.4 says GST is not part of the cap).
   Rounded half-up to the paisa. All with `Decimal`, never floats or a model.
9. **Q3 (Rs.1,50,000):** the fee maths is shown (MDR capped at Rs.25, GST Rs.4.50), but I also flag that Rs.1,50,000 is above the
   Rs.1,00,000 per-transaction limit (4.1); only Capital Markets / Insurance merchants with enhanced KYC may accept it (4.2, 4.4).
   A fee answer that ignores that would be technically right and practically misleading.
10. **"Same merchant" (Q3):** the engine is stateless; follow-ups pass a `context` (the interactive CLI/`Conversation` does it automatically).
    With no context the merchant size is unknown, so both small and large are shown.

## D. Limits
11. **Q6 -> No.** 4.3 is a daily limit per customer account across all UPI transactions, so a second Rs.1,00,000 is declined.
    Circular E adds "or the customer's own bank limit, whichever is lower"; I don't know that limit, so I say it may be lower.
12. **4.2 vs 4.3 clash (unresolved):** enhanced merchants may accept Rs.2,00,000 per transaction, yet the daily limit is Rs.1,00,000
    and nothing exempts them. I don't pick a side; the assistant says the documents don't settle it.

## E. Settlement, closure
13. **Circular A "replaces clause 1.1"**, and the definition "working days exclude Sundays and bank holidays" lived in 1.1.
    Read literally, the definition was replaced too. I treat it as still valid (clause 1.3 and 5.2 still depend on it).
14. **Working days:** only Sundays are skipped (Saturdays count), since that's all the text says. No bank-holiday list exists,
    so I give the deadline "if no bank holiday" and say each holiday pushes it later. Closure day is day 0.
15. **Q7 "closed yesterday":** 5.1 needs 30 days' written notice, so "closed" could mean "gave notice". I answer for an
    actual closure and flag the notice case.
16. **Q8:** the documents give cards only T+2 and the add-on is described for UPI, so the answer is "No (per these documents)".
    I can't prove no other arrangement exists, only that none is described.

## F. Output conventions
17. **FAQ "clause numbers":** the FAQ has none, so I cite the question text as the identifier rather than invent a number.
18. **Status meaning:** `CONFLICT_RESOLVED` = two documents or two dated versions speak to this and the date (or ranking)
    decided which wins; that includes a clause that is announced but not yet in force. `ANSWERED` = one clear source.
    `CANNOT_ANSWER` = not in the documents (card MDR, Annexure C, dates before 2026) or not understood.
19. **Citation roles:** `applied`, `superseded`, `upcoming`, `context`, so the reader sees what decided it and what was replaced.
20. **No LLM:** the questions are narrow and arithmetic must be exact. Hand-written routing is predictable and runs offline, at
    the price of weaker handling of unusual wording (see `WHERE_IT_BREAKS.md`).
