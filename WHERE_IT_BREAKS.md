# Where it breaks

I ran these after the eval was passing 18/18, to look for real failures.

## 1. A figure in the question is read as an event
**Question:** "Is the refund window 90 days and does MDR come back?" (as of 15 Aug 2026)
**What it does:** answers that "a refund after 2160 hours is outside the 24-hour window, so the MDR is not returned": **wrong**.
**Why:** the time parser takes the first "number + unit" it sees. Here "90 days" is the policy's window, not when the refund happened.
It can't tell the user's facts from the user's guesses about the policy. Same weakness for "within 24 hours" in a question.
**Trust level:** only when the question states one clear elapsed time.

## 2. Enhanced-KYC merchants: the documents contradict themselves
**Question:** "Can an insurance merchant accept Rs.2,00,000 from one customer in a day?"
**What it does:** says "Not clearly" and explains the clash (4.2 allows Rs.2,00,000 per transaction, 4.3 caps the day at Rs.1,00,000).
**Why it can't be trusted for a firm answer:** no clause says whether enhanced merchants are exempt from the daily cap. Honest uncertainty
is the best this system can do; a human has to ask the policy owner. Annexure C (the KYC rules) is also missing.

## 3. Amount questions phrased as "how much did I lose?", and multi-part questions
**Question:** "I refunded a Rs.6,000 UPI payment 2 hours after sale as a large merchant on 5 Sep. How much MDR did I lose?"
**What it does:** answers the yes/no ("No ... gets no MDR back") but never gives the amount (the figure would be Rs.25.00: 0.50% of Rs.6,000 is Rs.30, capped at Rs.25).
**Why:** the router picks one handler per question. Two-part questions get one part answered. Also, it never computes a settlement date from
a sale date ("sale on Saturday 15 Aug, when do I get paid?" returns the rule, not a date), and exact payout dates depend on a bank-holiday list that isn't in the documents.
