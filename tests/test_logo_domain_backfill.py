import unittest

from workers.logo_domain_backfill import (
    RequestPacer,
    backfill_logo_domains,
    normalize_domain,
)


class RecordingRepository:
    def __init__(self, candidates):
        self.candidates = candidates
        self.writes = []

    def latest_completed_run(self):
        return {"run_date": "2026-08-14", "row_count": len(self.candidates)}

    def snapshot_logo_candidates(self, run_date, *, only_missing):
        self.requested = (run_date, only_missing)
        return list(self.candidates)

    def upsert_snapshot_logo_domains(self, run_date, domains):
        self.writes.append((run_date, list(domains)))
        return len(domains)


class NormalizeDomainTests(unittest.TestCase):
    def test_normalizes_company_websites(self):
        self.assertEqual(normalize_domain("https://www.ril.com/about"), "ril.com")
        self.assertEqual(normalize_domain("infosys.com"), "infosys.com")

    def test_rejects_missing_or_malformed_websites(self):
        self.assertIsNone(normalize_domain(None))
        self.assertIsNone(normalize_domain(""))
        self.assertIsNone(normalize_domain("https:///missing-host"))


class BackfillTests(unittest.TestCase):
    def test_patches_only_successful_domains_in_checkpoint_batches(self):
        repository = RecordingRepository(
            [
                {"symbol": "INFY", "company": "Infosys", "logo_domain": None},
                {
                    "symbol": "RELIANCE",
                    "company": "Reliance",
                    "logo_domain": None,
                    "payload": {"Symbol": "RELIANCE"},
                },
                {"symbol": "MISSING", "company": "Missing", "logo_domain": None},
            ]
        )
        values = {
            "INFY": "https://www.infosys.com/about",
            "RELIANCE": "ril.com",
            "MISSING": None,
        }

        summary = backfill_logo_domains(
            repository,
            batch_size=1,
            resolver=values.get,
        )

        self.assertEqual(repository.requested, ("2026-08-14", True))
        self.assertEqual(summary.candidates, 3)
        self.assertEqual(summary.resolved, 2)
        self.assertEqual(summary.no_website, 1)
        self.assertEqual(summary.written, 2)
        self.assertEqual(
            repository.writes,
            [
                (
                    "2026-08-14",
                    [
                        {
                            "symbol": "INFY",
                            "logo_domain": "infosys.com",
                            "payload": {},
                        }
                    ],
                ),
                (
                    "2026-08-14",
                    [
                        {
                            "symbol": "RELIANCE",
                            "logo_domain": "ril.com",
                            "payload": {"Symbol": "RELIANCE"},
                        }
                    ],
                ),
            ],
        )

    def test_limit_makes_a_small_trial_run_possible(self):
        repository = RecordingRepository(
            [{"symbol": "INFY"}, {"symbol": "RELIANCE"}]
        )

        summary = backfill_logo_domains(
            repository,
            limit=1,
            resolver=lambda symbol: f"{symbol.lower()}.example",
        )

        self.assertEqual(summary.candidates, 1)
        self.assertEqual(summary.written, 1)

    def test_lookup_failure_does_not_discard_successful_progress(self):
        repository = RecordingRepository(
            [{"symbol": "BAD"}, {"symbol": "INFY"}]
        )

        def resolver(symbol):
            if symbol == "BAD":
                raise RuntimeError("temporary failure")
            return "infosys.com"

        summary = backfill_logo_domains(repository, resolver=resolver)

        self.assertEqual(summary.failed, 1)
        self.assertEqual(summary.written, 1)


class RequestPacerTests(unittest.TestCase):
    def test_spaces_requests_evenly(self):
        current = [10.0]
        sleeps = []

        def clock():
            return current[0]

        def sleep(seconds):
            sleeps.append(seconds)
            current[0] += seconds

        pacer = RequestPacer(30, clock=clock, sleep=sleep)
        pacer()
        pacer()

        self.assertEqual(sleeps, [2.0])


if __name__ == "__main__":
    unittest.main()
