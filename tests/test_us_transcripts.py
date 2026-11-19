"""US transcripts: EDGAR finds the call, the cover page names its quarter, a daily budget fetches it."""

import unittest
from datetime import date

from transcripts.alphavantage import Refused, transcript_text
from workers.market_events import transcript_events
from workers.us_transcripts import (
    MAX_ATTEMPTS,
    Periodic,
    fiscal_quarter,
    periodic_filings,
    results_releases,
    run,
)

TODAY = date(2026, 11, 19)
TURN = "We grew revenue and expect demand to stay strong next year. " * 30


def submissions(*rows, name="Acme Corp", fiscal_year_end="1231"):
    columns = ("form", "items", "filingDate", "accessionNumber", "reportDate", "acceptanceDateTime")
    return {"name": name, "fiscalYearEnd": fiscal_year_end,
            "filings": {"recent": {c: [r[i] for r in rows] for i, c in enumerate(columns)}}}


# Acme: calendar fiscal year. Q2 10-Q in August, Q3 results 8-K on 28 Oct, Q2 results in July.
ACME = submissions(
    ("8-K", "2.02,9.01", "2026-10-28", "0001-26-000003", "2026-10-28", "2026-10-28T16:05:00.000Z"),
    ("4", "", "2026-09-01", "0001-26-000099", "", ""),
    ("10-Q", "", "2026-08-05", "0001-26-000002", "2026-06-30", ""),
    ("8-K", "2.02", "2026-07-29", "0001-26-000001", "2026-07-29", ""),
    ("8-K", "5.02", "2026-07-01", "0001-26-000098", "2026-07-01", ""),
    ("10-Q", "", "2026-05-06", "0001-26-000000", "2026-03-31", ""),
)
ACME_CONCEPT = {"units": {"shares": [
    {"accn": "0001-26-000002", "form": "10-Q", "fy": 2026, "fp": "Q2", "filed": "2026-08-05"},
    {"accn": "0001-26-000002", "form": "10-Q", "fy": 2026, "fp": "Q2", "filed": "2026-08-05"},  # a second class
    {"accn": "0001-26-000000", "form": "10-Q", "fy": 2026, "fp": "Q1", "filed": "2026-05-06"},
    {"accn": "0001-26-000050", "form": "S-1", "fy": 2026, "fp": "Q1", "filed": "2026-05-07"},
]}}


def payload(text=TURN):
    return {"symbol": "ACME", "quarter": "2026Q3", "transcript": [
        {"speaker": "Operator", "title": "", "content": "Welcome to the call."},
        {"speaker": "Jane Roe", "title": "Chief Executive Officer", "content": text, "sentiment": "0.7"},
    ]}


class TextTests(unittest.TestCase):
    def test_turns_become_speaker_headings_the_segmenter_reads(self):
        from transcripts.segmenter import _speaker_from_line

        text = transcript_text(payload("Demand  was\nstrong."))
        self.assertEqual(text, "Operator:\nWelcome to the call.\n\nJane Roe (Chief Executive Officer):\nDemand was strong.")
        self.assertEqual(_speaker_from_line("Jane Roe (Chief Executive Officer):")[1], "management")

    def test_no_transcript_is_empty_and_a_refusal_raises(self):
        self.assertEqual(transcript_text({"symbol": "ACME", "transcript": []}), "")
        with self.assertRaises(Refused):
            transcript_text({"Information": "Our standard API rate limit is 25 requests per day."})


class QuarterTests(unittest.TestCase):
    def periodic(self):
        return periodic_filings(ACME_CONCEPT, self.release())

    def release(self, index=ACME):
        return results_releases("ACME", 1, index, since=date(2026, 1, 1), until=TODAY)[0]

    def test_results_8ks_in_the_window_only(self):
        found = results_releases("ACME", 1, ACME, since=date(2026, 7, 15), until=TODAY)
        self.assertEqual([(r.accession, r.filed, r.company) for r in found], [
            ("0001-26-000003", date(2026, 10, 28), "Acme Corp"),
            ("0001-26-000001", date(2026, 7, 29), "Acme Corp"),
        ])

    def test_one_periodic_filing_per_accession_with_its_period_end(self):
        self.assertEqual(
            [(p.fp, p.period_end) for p in self.periodic()],
            [("Q1", date(2026, 3, 31)), ("Q2", date(2026, 6, 30))],
        )

    def test_the_quarter_after_the_last_10q(self):
        self.assertEqual(fiscal_quarter(self.periodic(), date(2026, 10, 28)), ("2026Q3", date(2026, 9, 30)))
        self.assertEqual(fiscal_quarter(self.periodic(), date(2026, 7, 29)), ("2026Q2", date(2026, 6, 30)))

    def test_filings_the_cover_page_facts_miss_are_labelled_from_the_fiscal_year_end(self):
        # Berkshire: the share-count concept stops in 2011, the filing index does not.
        stale = {"units": {"shares": [{"accn": "old", "form": "10-Q", "fy": 2011, "fp": "Q1", "filed": "2011-05-06"}]}}
        periodic = periodic_filings(stale, self.release())
        self.assertEqual(fiscal_quarter(periodic, date(2026, 10, 28)), ("2026Q3", date(2026, 9, 30)))

    def test_a_year_end_label_follows_a_52_53_week_year_and_a_january_year_end(self):
        apple = submissions(
            ("8-K", "2.02", "2026-10-30", "a3", "", ""),
            ("10-Q", "", "2026-08-01", "a2", "2026-06-27", ""),
            fiscal_year_end="0925",
        )
        self.assertEqual(fiscal_quarter(periodic_filings(None, self.release(apple)), date(2026, 10, 30)),
                         ("2026Q4", date(2026, 9, 26)))
        walmart = submissions(
            ("8-K", "2.02", "2026-11-19", "w3", "", ""),
            ("10-Q", "", "2026-09-01", "w2", "2026-07-31", ""),
            fiscal_year_end="0131",
        )
        release = results_releases("WMT", 1, walmart, since=date(2026, 1, 1), until=date(2026, 11, 30))[0]
        self.assertEqual(fiscal_quarter(periodic_filings(None, release), date(2026, 11, 19)),
                         ("2027Q3", date(2026, 10, 31)))

    def test_a_label_that_disagrees_with_the_companys_others_is_corrected(self):
        def quarter(index, concept, release_day):
            release = results_releases("X", 1, index, since=date(2020, 1, 1), until=TODAY)[0]
            return fiscal_quarter(periodic_filings(concept, release), release_day)[0]

        def concept(*rows):
            return {"units": {"shares": [
                {"accn": a, "form": f, "fy": fy, "fp": fp, "filed": d} for a, f, fy, fp, d in rows
            ]}}

        # Salesforce names a year by the year it ends, but its FY2026 10-K says 2025.
        salesforce = submissions(
            ("8-K", "2.02", "2026-05-27", "r", "", ""),
            ("10-K", "", "2026-03-02", "k", "2026-01-31", ""),
            ("10-Q", "", "2025-12-04", "q3", "2025-10-31", ""),
            ("10-Q", "", "2025-09-04", "q2", "2025-07-31", ""),
            fiscal_year_end="0131",
        )
        self.assertEqual(quarter(salesforce, concept(
            ("q2", "10-Q", 2026, "Q2", "2025-09-04"), ("q3", "10-Q", 2026, "Q3", "2025-12-04"),
            ("k", "10-K", 2025, "FY", "2026-03-02"),
        ), date(2026, 5, 27)), "2027Q1")
        # Target names a year by the year it starts, but its November 2022 10-Q says 2023;
        # the filings after it keep their own labels.
        target = submissions(
            ("8-K", "2.02", "2023-05-17", "r", "", ""),
            ("10-K", "", "2023-03-08", "k", "2023-01-28", ""),
            ("10-Q", "", "2022-11-23", "q3", "2022-10-29", ""),
            ("10-Q", "", "2022-08-26", "q2", "2022-07-30", ""),
            fiscal_year_end="0201",
        )
        self.assertEqual(quarter(target, concept(
            ("q2", "10-Q", 2022, "Q2", "2022-08-26"), ("q3", "10-Q", 2023, "Q3", "2022-11-23"),
            ("k", "10-K", 2022, "FY", "2023-03-08"),
        ), date(2023, 5, 17)), "2023Q1")

    def test_after_the_10k_comes_the_next_fiscal_years_first_quarter(self):
        # A retailer: fiscal 2026 ends 31 Jan 2027, its Q1 results come out in May.
        periodic = [Periodic("a", date(2027, 3, 20), 2026, "FY", date(2027, 1, 31))]
        self.assertEqual(fiscal_quarter(periodic, date(2027, 5, 20)), ("2027Q1", date(2027, 4, 30)))

    def test_a_52_53_week_year_moves_13_weeks(self):
        periodic = [Periodic("a", date(2026, 8, 1), 2026, "Q3", date(2026, 6, 27))]
        self.assertEqual(fiscal_quarter(periodic, date(2026, 10, 30)), ("2026Q4", date(2026, 9, 26)))

    def test_a_10q_filed_before_the_release_is_the_releases_quarter(self):
        periodic = [Periodic("a", date(2026, 10, 27), 2026, "Q3", date(2026, 9, 30))]
        self.assertEqual(fiscal_quarter(periodic, date(2026, 10, 28)), ("2026Q3", date(2026, 9, 30)))

    def test_no_earlier_periodic_filing_no_quarter(self):
        self.assertIsNone(fiscal_quarter(self.periodic(), date(2026, 5, 1)))


class FakeEdgar:
    def __init__(self, indexes):
        self.indexes = indexes  # symbol -> (cik, submissions, concept)

    def cik_for(self, symbol):
        return self.indexes[symbol][0] if symbol in self.indexes else None

    def _by_cik(self, cik):
        return next(v for v in self.indexes.values() if v[0] == cik)

    def submissions(self, cik):
        return self._by_cik(cik)[1]

    def concept(self, cik, taxonomy, tag):
        return self._by_cik(cik)[2]


class FakeRepo:
    def __init__(self, filings=(), transcripts=()):
        self.filings = {f["seq_id"]: dict(f) for f in filings}
        self.transcripts = list(transcripts)
        self.documents = []

    def transcript_filings(self, exchange):
        assert exchange == "US"
        return list(self.filings.values())

    def has_transcript(self, symbol, quarter):
        return any(t["symbol"] == symbol and t["quarter"] == quarter for t in self.transcripts)

    def upsert_filing(self, filing):
        row = self.filings.setdefault(filing["seq_id"], {"id": filing["seq_id"], "status": "discovered", "attempt_count": 0})
        row.update(filing)
        return dict(row)

    def update_filing(self, filing_id, **fields):
        self.filings[filing_id].update(fields)

    def find_document_by_sha256(self, sha256):
        return None

    def create_document(self, document):
        self.documents.append(document)
        return {"id": f"doc{len(self.documents)}", **document}

    def upsert_transcript(self, transcript):
        self.transcripts.append(transcript)
        return transcript

    def link_filing_document(self, filing_id, document_id):
        self.filings[filing_id]["document_id"] = document_id


class RunTests(unittest.TestCase):
    def setUp(self):
        self.asked, self.slept = [], []

    def fetch(self, answers):
        def fetch(symbol, quarter, key):
            self.asked.append((symbol, quarter))
            answer = answers.get((symbol, quarter), payload())
            if isinstance(answer, Exception):
                raise answer
            return answer
        return fetch

    def go(self, repo, answers=None, **kwargs):
        edgar = FakeEdgar({"ACME": (1, ACME, ACME_CONCEPT), "NOPE": (2, {}, None)})
        return run(repo, edgar, ["ACME", "NOPE", "UNLISTED"], key="SECRET", today=TODAY,
                   fetch=self.fetch(answers or {}), sleep=self.slept.append, **kwargs)

    def test_newest_call_first_within_the_budget(self):
        repo = FakeRepo()
        counts = self.go(repo, budget=1)
        self.assertEqual(self.asked, [("ACME", "2026Q3")])
        self.assertEqual((counts["releases"], counts["pending"], counts["stored"]), (2, 2, 1))
        (transcript,) = repo.transcripts
        self.assertEqual((transcript["quarter"], transcript["call_date"]), ("2026-09-30", "2026-10-28"))
        self.assertEqual(repo.documents[0]["extraction_method"], "api:alphavantage")
        self.assertEqual(repo.filings["0001-26-000003"]["status"], "document_ready")
        self.assertEqual(repo.filings["0001-26-000003"]["exchange"], "US")

    def test_leftover_budget_fills_in_the_earlier_quarter(self):
        repo = FakeRepo()
        self.go(repo)
        self.assertEqual(self.asked, [("ACME", "2026Q3"), ("ACME", "2026Q2")])
        self.assertEqual(self.slept, [1.5])  # spaced: the free key refuses a second request within a second

    def test_done_and_given_up_filings_are_not_asked_again(self):
        repo = FakeRepo(filings=[
            {"id": "x", "seq_id": "0001-26-000003", "status": "document_ready", "attempt_count": 0},
            {"id": "y", "seq_id": "0001-26-000001", "status": "failed", "attempt_count": MAX_ATTEMPTS},
        ])
        self.assertEqual(self.go(repo)["requests"], 0)

    def test_not_there_yet_counts_an_attempt(self):
        repo = FakeRepo()
        counts = self.go(repo, {("ACME", "2026Q3"): {"transcript": []}}, budget=1)
        self.assertEqual(counts["not_yet"], 1)
        self.assertEqual(repo.filings["0001-26-000003"]["attempt_count"], 1)
        self.assertEqual(repo.filings["0001-26-000003"]["status"], "failed")

    def test_a_refusal_stops_the_run_and_marks_nothing(self):
        repo = FakeRepo()
        counts = self.go(repo, {("ACME", "2026Q3"): {"Note": "limit reached"}})
        self.assertEqual(self.asked, [("ACME", "2026Q3")])
        self.assertEqual((counts["refused"], counts["requests"]), (1, 0))
        self.assertEqual(repo.filings["0001-26-000003"]["attempt_count"], 0)

    def test_an_http_error_is_recorded_without_the_key(self):
        repo = FakeRepo()
        self.go(repo, {("ACME", "2026Q3"): RuntimeError("500 for url ...&apikey=SECRET")}, budget=1)
        self.assertNotIn("SECRET", repo.filings["0001-26-000003"]["last_error"])

    def test_a_second_8k_for_a_stored_quarter_spends_nothing(self):
        repo = FakeRepo(transcripts=[{"symbol": "ACME", "quarter": "2026-09-30"}])
        counts = self.go(repo, budget=1)
        self.assertEqual(counts["same_quarter"], 1)
        self.assertEqual(repo.filings["0001-26-000003"]["status"], "rejected")
        self.assertEqual(self.asked, [("ACME", "2026Q2")])

    def test_two_8ks_for_one_quarter_are_asked_once_a_run(self):
        index = submissions(
            ("8-K", "2.02", "2026-10-28", "0001-26-000004", "", ""),
            ("8-K", "2.02", "2026-10-28", "0001-26-000003", "", ""),
            ("10-Q", "", "2026-08-05", "0001-26-000002", "2026-06-30", ""),
        )
        edgar = FakeEdgar({"ACME": (1, index, ACME_CONCEPT)})
        counts = run(FakeRepo(), edgar, ["ACME"], key="k", today=TODAY, sleep=self.slept.append,
                     fetch=self.fetch({("ACME", "2026Q3"): {"transcript": []}}))
        self.assertEqual((self.asked, counts["same_quarter"]), ([("ACME", "2026Q3")], 1))

    def test_a_dry_run_fetches_and_writes_nothing(self):
        repo = FakeRepo()
        counts = self.go(repo, dry_run=True)
        self.assertEqual(counts["stored"], 2)
        self.assertEqual((repo.filings, repo.transcripts), ({}, []))


class BellTests(unittest.TestCase):
    def test_a_call_filled_in_long_after_it_was_held_is_not_news(self):
        events = transcript_events(
            [
                {"symbol": "ACME", "quarter": "2026-06-30", "call_date": "2026-07-29",
                 "created_at": "2026-11-19T03:05:00+00:00"},
                {"symbol": "ACME", "quarter": "2026-09-30", "call_date": "2026-10-28",
                 "created_at": "2026-11-19T03:05:00+00:00"},
            ],
            {"ACME": "Acme"},
        )
        self.assertEqual([e["event_key"] for e in events], ["2026-10-28"])


if __name__ == "__main__":
    unittest.main()
