import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


class AssignmentEvaluation(unittest.TestCase):
    def test_evaluation_meets_assignment_requirements(self):
        cases = json.loads((ROOT / "eval.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(cases), 12)
        self.assertGreaterEqual(sum(case["adversarial"] for case in cases), 4)
        for case in cases:
            self.assertIn("expected_answer", case)
            self.assertIn("expected_citations", case)
            self.assertIn("as_of_date", case)


if __name__ == "__main__":
    unittest.main()
