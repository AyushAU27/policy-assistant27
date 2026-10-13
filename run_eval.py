"""Runs the assistant on eval.json and prints a score table.

A question PASSES only if all three checks pass:
  status   - the returned status equals the expected one
  facts    - every `must_contain` phrase appears in the answer text
  cites    - every expected (document, clause) appears among the returned citations
Every returned citation is also checked to exist in the documents (no invented clauses).
"""
import json
import sys
from pathlib import Path

from policy_assistant import ask, verify
from policy_assistant.documents import get_corpus

ROOT = Path(__file__).resolve().parent


def main() -> int:
    verify()
    corpus = get_corpus()
    cases = json.loads((ROOT / "eval.json").read_text(encoding="utf-8"))
    rows, failed = [], []
    for c in cases:
        a = ask(c["question"], c["as_of_date"], c.get("context"))
        got = {(x.doc, x.clause) for x in a.citations}
        status_ok = a.status == c["expected_status"]
        facts_missing = [p for p in c["must_contain"] if p.lower() not in a.answer.lower()]
        cites_missing = [e for e in c["expected_citations"] if tuple(e) not in got]
        real = all(corpus.text(d, cl) for d, cl in got)       # raises if a citation is invented
        ok = status_ok and not facts_missing and not cites_missing and real
        rows.append((c["id"], "adv" if c["adversarial"] else "", a.status, status_ok,
                     not facts_missing, not cites_missing, ok))
        if not ok:
            failed.append((c["id"], a.status, facts_missing, cites_missing))
    mark = lambda b: "ok" if b else "FAIL"
    print(f"{'id':<5} {'type':<5} {'status returned':<18} {'status':<7} {'facts':<7} {'cites':<7} result")
    print("-" * 66)
    for r in rows:
        print(f"{r[0]:<5} {r[1]:<5} {r[2]:<18} {mark(r[3]):<7} {mark(r[4]):<7} {mark(r[5]):<7} {'PASS' if r[6] else 'FAIL'}")
    print("-" * 66)
    passed = sum(r[6] for r in rows)
    adv = [r for r in rows if r[1]]
    print(f"Passed {passed}/{len(rows)}   (adversarial: {sum(r[6] for r in adv)}/{len(adv)})")
    for f in failed:
        print("  FAILED", f)
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
