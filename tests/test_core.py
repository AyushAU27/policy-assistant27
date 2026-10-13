"""Run with:  python -m unittest discover -s tests -v"""
import sys
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from policy_assistant import ask, verify
from policy_assistant.documents import UnknownClause, get_corpus
from policy_assistant.engine import add_working_days, inr
from policy_assistant.textparse import find_money, detect_tier


class RuleTable(unittest.TestCase):
    def test_rules_match_documents(self):
        verify()

    def test_cannot_cite_invented_clause(self):
        with self.assertRaises(UnknownClause):
            get_corpus().cite("policy_master_v1.md", "9.9")


class Arithmetic(unittest.TestCase):
    def test_large_4000(self):
        a = ask("Large merchant, Rs.4,000 UPI payment, what MDR and GST?", "2026-08-15")
        self.assertIn("₹20.00", a.answer); self.assertIn("₹3.60", a.answer)

    def test_cap_bites_for_large(self):
        a = ask("Large merchant, Rs.1,00,000 UPI payment, what MDR and GST?", "2026-08-15")
        self.assertIn("₹25.00", a.answer); self.assertIn("₹4.50", a.answer)

    def test_old_cap_before_august(self):
        a = ask("Large merchant, Rs.1,00,000 UPI payment, what MDR and GST?", "2026-07-20")
        self.assertIn("₹15.00", a.answer); self.assertIn("₹2.70", a.answer)

    def test_indian_grouping(self):
        self.assertEqual(inr(150000), "₹1,50,000")
        self.assertEqual(inr(Decimal("3.6"), 2), "₹3.60")


class DateDependence(unittest.TestCase):
    Q = "A merchant refunds a customer 3 hours after the sale. Do they get the MDR back?"

    def test_20_aug_yes(self):
        self.assertTrue(ask(self.Q, "2026-08-20").answer.startswith("Yes"))

    def test_31_aug_yes_1_sep_no(self):
        self.assertTrue(ask(self.Q, "2026-08-31").answer.startswith("Yes"))
        self.assertTrue(ask(self.Q, "2026-09-01").answer.startswith("No"))

    def test_before_policy_exists(self):
        self.assertEqual(ask("When does UPI settle?", "2025-12-31").status, "CANNOT_ANSWER")


class Parsing(unittest.TestCase):
    def test_cap_reference_is_not_an_amount(self):
        m = find_money("the Rs.15 MDR cap and a Rs.1,00,000 payment")
        self.assertEqual([x.role for x in m], ["reference", "amount"])

    def test_boundary_ten_lakh_is_small(self):
        m = find_money("volume of exactly Rs.10 lakh monthly")
        self.assertEqual(detect_tier("", m, {}), "small")

    def test_working_days_skip_sundays(self):
        self.assertEqual(add_working_days(date(2026, 8, 14), 10), date(2026, 8, 26))


class Honesty(unittest.TestCase):
    def test_card_mdr_not_guessed(self):
        self.assertEqual(ask("What is the MDR on card payments?").status, "CANNOT_ANSWER")

    def test_nonsense_not_guessed(self):
        self.assertEqual(ask("Who won the cricket match?").status, "CANNOT_ANSWER")


if __name__ == "__main__":
    unittest.main()
