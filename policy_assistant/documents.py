"""Loads the three policy documents and makes sure we can only cite real clauses.

Why this file exists: the assignment says "never invent a clause number".
The simplest way to guarantee that is to make citing impossible unless the
clause was actually found in the file. `Corpus.cite()` raises if it wasn't.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "ai-2-data"

MASTER = "policy_master_v1.md"
CIRCULAR = "circular_2026_08_amendment.md"
FAQ = "merchant_faq_2026-03.md"


class UnknownClause(KeyError):
    """Raised when something tries to cite a clause that is not in the documents."""


@dataclass(frozen=True)
class Citation:
    doc: str
    clause: str
    quote: str
    # applied    = the clause that decides the answer
    # superseded = an older clause that was replaced (shown so the reader sees why)
    # upcoming   = a clause that is announced but not yet in force on the date
    # context    = background (e.g. what the FAQ said)
    role: str = "applied"

    def label(self) -> str:
        if self.doc == FAQ:
            return f'{self.doc} (FAQ entry: "{self.clause}")'
        return f"{self.doc} clause {self.clause}"

    def to_dict(self) -> dict:
        return {"document": self.doc, "clause": self.clause,
                "role": self.role, "quote": self.quote}


class Corpus:
    def __init__(self, data_dir: Path = DATA_DIR):
        self.clauses: dict[str, dict[str, str]] = {MASTER: {}, CIRCULAR: {}, FAQ: {}}
        self._load_master((data_dir / MASTER).read_text(encoding="utf-8"))
        self._load_circular((data_dir / CIRCULAR).read_text(encoding="utf-8"))
        self._load_faq((data_dir / FAQ).read_text(encoding="utf-8"))

    # -- parsing ---------------------------------------------------------
    def _load_master(self, text: str) -> None:
        # Lines look like "2.3 MDR on any single UPI transaction ..."
        for line in text.splitlines():
            m = re.match(r"^(\d+\.\d+)\s+(.*\S)\s*$", line)
            if m:
                self.clauses[MASTER][m.group(1)] = m.group(2)

    def _load_circular(self, text: str) -> None:
        # Lines look like "A. Clause 1.1 is replaced: ..."; an indented line
        # underneath continues the previous clause (e.g. the "Effective ..." line).
        current = None
        for line in text.splitlines():
            m = re.match(r"^([A-Z])\.\s+(.*\S)\s*$", line)
            if m:
                current = m.group(1)
                self.clauses[CIRCULAR][current] = m.group(2)
            elif current and line[:1] in (" ", "\t") and line.strip():
                self.clauses[CIRCULAR][current] += " " + line.strip()
            elif not line.strip():
                current = None

    def _load_faq(self, text: str) -> None:
        # The FAQ has no clause numbers, so the "clause id" is the question itself.
        question, answer = None, []
        for line in text.splitlines() + [""]:
            m = re.match(r"^\*\*(.+?)\*\*\s*$", line)
            if m:
                question, answer = m.group(1), []
            elif question and line.strip():
                answer.append(line.strip())
            elif question and answer:
                self.clauses[FAQ][question] = " ".join(answer)
                question, answer = None, []

    # -- public API ------------------------------------------------------
    def text(self, doc: str, clause: str) -> str:
        try:
            return self.clauses[doc][clause]
        except KeyError:
            raise UnknownClause(f"{doc} has no clause {clause!r}") from None

    def cite(self, doc: str, clause: str, role: str = "applied") -> Citation:
        return Citation(doc, clause, self.text(doc, clause), role)


@lru_cache(maxsize=1)
def get_corpus() -> Corpus:
    return Corpus()
