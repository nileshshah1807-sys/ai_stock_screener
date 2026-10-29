import unittest

from sentiment.outlook import _EMPTY
from tools.rescore_transcript_outlooks import rescored, run


def extraction(**sections):
    base = {section: dict(empty) for section, empty in _EMPTY.items()}
    base.update(tailwinds=[], headwinds=[], points=[])
    base.update(sections)
    return base


PLANNED = extraction(capacity={"state": "planned", "commissioning": None, "quote": "A new plant is planned."})


class RescoreTests(unittest.TestCase):
    def test_a_reading_scored_under_older_weights_is_scored_again(self):
        # Planned capacity scored +1 before October 2026, and scores nothing now.
        row = {"id": 1, "call_date": "2026-08-10", "outlook_score": 51.0,
               "extraction": {**PLANNED, "points": [{"reason": "capacity planned", "points": 1.0}]}}
        score, updated = rescored(row)
        self.assertEqual(score, 50.0)
        self.assertEqual(updated["points"], [{"reason": "capacity planned", "points": 0.0}])
        self.assertEqual(updated["capacity"], PLANNED["capacity"])

    def test_a_reading_already_under_todays_weights_is_left_alone(self):
        row = {"id": 1, "call_date": "2026-08-10", "outlook_score": 50.0,
               "extraction": {**PLANNED, "points": [{"reason": "capacity planned", "points": 0.0}]}}
        self.assertIsNone(rescored(row))

    def test_an_extraction_of_another_shape_is_left_alone(self):
        self.assertIsNone(rescored({"id": 1, "outlook_score": 60, "extraction": {"guidance": None}}))
        self.assertIsNone(rescored({"id": 1, "outlook_score": 60, "extraction": None}))

    def test_a_dry_run_writes_nothing(self):
        class Repository:
            written = []

            def stored_outlooks(self, version):
                return [{"id": 7, "call_date": "2026-08-10", "outlook_score": 51.0, "extraction": PLANNED}]

            def update_outlook_score(self, *args):
                self.written.append(args)

        repository = Repository()
        self.assertEqual(run(repository, dry_run=True), {"stored": 1, "changed": 1, "written": 0})
        self.assertEqual(repository.written, [])
        self.assertEqual(run(repository), {"stored": 1, "changed": 1, "written": 1})
        self.assertEqual(repository.written[0][:2], (7, 50.0))
