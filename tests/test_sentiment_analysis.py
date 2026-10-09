import unittest
from unittest.mock import patch

from sentiment.analyzer import aggregate_sentiments, analyze_transcript
from sentiment.local_analyzer import LocalSentimentAnalyzer
from sentiment.outlook import (
    SCHEMA,
    build_messages,
    outlook_points,
    outlook_score,
    parse_response,
    quote_found,
    verify_quotes,
)
from sentiment.schemas import ChunkSentiment
from transcripts.chunker import TranscriptChunk


def sample_payload(**overrides):
    payload = {
        "optimism": 80,
        "guidance_strength": 70,
        "management_confidence": 75,
        "risk_intensity": 20,
        "analyst_pressure": 35,
        "answer_quality": 85,
        "guidance_direction": "maintained",
        "revenue_outlook": "Growth continues.",
        "margin_outlook": "Margins stable.",
        "demand_outlook": "Demand healthy.",
        "catalysts": ["Capacity expansion"],
        "risks": ["Commodity costs"],
        "evidence": ["We maintain guidance."],
    }
    payload.update(overrides)
    return payload


class SentimentAnalysisTests(unittest.TestCase):
    def test_schema_rejects_out_of_range_scores(self):
        with self.assertRaises(ValueError):
            ChunkSentiment.from_payload(sample_payload(optimism=101))

    def test_aggregation_applies_documented_score_formula(self):
        analysis = ChunkSentiment.from_payload(sample_payload())
        result = aggregate_sentiments([analysis], [TranscriptChunk(0, "text", 100)])

        self.assertEqual(result["overall_score"], 77.75)
        self.assertEqual(result["confidence_score"], 75)
        self.assertEqual(result["guidance_direction"], "maintained")

    def test_aggregation_preserves_explicit_guidance_over_unclear_chunks(self):
        analyses = [
            ChunkSentiment.from_payload(sample_payload(guidance_direction="raised")),
            ChunkSentiment.from_payload(sample_payload(guidance_direction="unclear")),
            ChunkSentiment.from_payload(sample_payload(guidance_direction="unclear")),
        ]
        chunks = [
            TranscriptChunk(0, "guidance", 50),
            TranscriptChunk(1, "commentary", 500),
            TranscriptChunk(2, "questions", 500),
        ]

        result = aggregate_sentiments(analyses, chunks)

        self.assertEqual(result["guidance_direction"], "raised")

    def test_explicit_guidance_strength_is_not_diluted_by_unclear_chunks(self):
        analyses = [
            ChunkSentiment.from_payload(sample_payload(
                guidance_direction="raised", guidance_strength=85,
            )),
            ChunkSentiment.from_payload(sample_payload(
                guidance_direction="unclear", guidance_strength=35,
            )),
        ]
        chunks = [
            TranscriptChunk(0, "[prepared_remarks] CEO:\nWe will exceed guidance.", 50),
            TranscriptChunk(1, "[prepared_remarks] CEO:\nGeneral commentary.", 500),
        ]

        result = aggregate_sentiments(analyses, chunks)

        self.assertEqual(result["guidance_strength"], 85.0)

    def test_local_analyzer_detects_raised_guidance_and_positive_catalyst(self):
        result = LocalSentimentAnalyzer().analyze_chunk(
            "Demand remains strong and margins improved. We raised guidance after order growth accelerated."
        )

        self.assertEqual(result["guidance_direction"], "raised")
        self.assertGreater(result["optimism"], 50)
        self.assertGreater(result["guidance_strength"], 50)
        self.assertTrue(result["catalysts"])

    def test_local_analyzer_detects_lowered_guidance_and_risk(self):
        result = LocalSentimentAnalyzer().analyze_chunk(
            "We lowered guidance because demand weakness and margin pressure remain challenging."
        )

        self.assertEqual(result["guidance_direction"], "lowered")
        self.assertLess(result["guidance_strength"], 50)
        self.assertGreater(result["risk_intensity"], 50)
        self.assertTrue(result["risks"])

    def test_local_analyzer_detects_common_guidance_wording(self):
        analyzer = LocalSentimentAnalyzer()

        self.assertEqual(
            analyzer.analyze_chunk("WE UPGRADED OUR OUTLOOK following strong demand.")["guidance_direction"],
            "raised",
        )
        self.assertEqual(
            analyzer.analyze_chunk("We reaffirmed our forecast for the full year.")["guidance_direction"],
            "maintained",
        )
        self.assertEqual(
            analyzer.analyze_chunk("We reduced our expectations because of demand weakness.")["guidance_direction"],
            "lowered",
        )

    def test_local_analyzer_detects_exceeding_prior_guidance(self):
        result = LocalSentimentAnalyzer().analyze_chunk(
            "For the current year, we are on track to not only achieve what we have guided "
            "but exceed it, with 35% plus growth."
        )

        self.assertEqual(result["guidance_direction"], "raised")
        self.assertEqual(result["guidance_strength"], 85.0)

    def test_stockscans_style_transcript_preserves_syrma_raised_guidance(self):
        text = """Jasbir S. Gujral - Managing Director, Syrma SGS Technology Limited
We are well on track to not only achieving what we have guided but exceeding that achievement.
Nikhil Kandoi - Analyst, Axis Capital
Can you clarify the growth outlook?
Jasbir S. Gujral - Managing Director, Syrma SGS Technology Limited
It is 35% plus growth for the current year and 30% to 35% for the next three years.
"""

        result = analyze_transcript(text)

        self.assertEqual(result["guidance_direction"], "raised")
        self.assertEqual(result["guidance_strength"], 85.0)

    def test_local_analyzer_reports_financial_risk_and_baseline_features(self):
        result = LocalSentimentAnalyzer().analyze_chunk(
            "[management_answer] CFO: We may face commodity inflation and supply constraints."
        )

        self.assertEqual(result["section"], "management_answer")
        self.assertGreater(result["uncertainty_density"], 0)
        self.assertGreater(result["constraint_density"], 0)
        self.assertIn("textblob_polarity", result)
        self.assertIn("finbert_score", result)

    def test_required_finbert_inference_failure_is_not_silently_downgraded(self):
        def broken_classifier(*args, **kwargs):
            raise RuntimeError("model unavailable")

        with (
            patch.dict("os.environ", {"TRANSCRIPT_REQUIRE_FINBERT": "true"}),
            patch("sentiment.local_analyzer._finbert_pipeline", return_value=broken_classifier),
            self.assertRaisesRegex(RuntimeError, "FinBERT inference failed"),
        ):
            LocalSentimentAnalyzer().analyze_chunk("Demand remained strong.")

    def test_finbert_sentences_are_batched_across_chunks(self):
        calls = []

        def classifier(sentences, **kwargs):
            calls.append((list(sentences), kwargs))
            return [{"label": "positive", "score": 0.9} for _ in sentences]

        with patch("sentiment.local_analyzer._finbert_pipeline", return_value=classifier):
            results = LocalSentimentAnalyzer().analyze_chunks([
                "Revenue improved. Demand remains strong.",
                "Margins improved.",
            ])

        self.assertEqual(len(calls), 1)
        self.assertEqual(len(calls[0][0]), 3)
        self.assertEqual(calls[0][1]["batch_size"], 1)
        self.assertEqual([result["finbert_score"] for result in results], [0.9, 0.9])

    def test_finbert_input_is_capped_to_high_signal_sentences(self):
        calls = []

        def classifier(sentences, **kwargs):
            calls.append(list(sentences))
            return [{"label": "neutral", "score": 0.9} for _ in sentences]

        text = " ".join(
            f"Revenue growth improved by {index}% and demand remains strong."
            for index in range(40)
        )
        with patch("sentiment.local_analyzer._finbert_pipeline", return_value=classifier):
            LocalSentimentAnalyzer().analyze_chunks([text])

        self.assertEqual(len(calls), 1)
        self.assertEqual(len(calls[0]), 8)

    def test_aggregation_compares_prepared_remarks_with_management_qa(self):
        analyses = [
            ChunkSentiment.from_payload(sample_payload(optimism=80, management_confidence=85)),
            ChunkSentiment.from_payload(sample_payload(optimism=50, management_confidence=55)),
        ]
        chunks = [
            TranscriptChunk(0, "[prepared_remarks] CFO:\nDemand is strong.", 100),
            TranscriptChunk(1, "[management_answer] CFO:\nRisks remain.", 100),
        ]
        payloads = [
            {"textblob_polarity": 0.5, "finbert_score": 0.4, "uncertainty_density": 0.01},
            {"textblob_polarity": 0.0, "finbert_score": -0.2, "uncertainty_density": 0.05},
        ]

        result = aggregate_sentiments(analyses, chunks, payloads)

        self.assertEqual(result["prepared_vs_qa_tone_gap"], 30.0)
        self.assertEqual(result["qa_confidence_drop"], 30.0)
        self.assertTrue(result["review_flag"])

    def test_aggregation_does_not_blend_analyst_question_tone_into_management_score(self):
        analyses = [
            ChunkSentiment.from_payload(sample_payload(optimism=80, risk_intensity=20)),
            ChunkSentiment.from_payload(sample_payload(optimism=5, risk_intensity=95)),
        ]
        chunks = [
            TranscriptChunk(0, "[management_answer] CEO:\nDemand remains strong.", 100),
            TranscriptChunk(1, "[analyst_question] Analyst:\nWhy is demand collapsing?", 1000),
        ]

        result = aggregate_sentiments(analyses, chunks)

        self.assertEqual(result["optimism"], 80.0)
        self.assertEqual(result["risk_intensity"], 20.0)

    def test_lowered_guidance_is_not_outvoted_by_a_longer_maintained_chunk(self):
        analyses = [
            ChunkSentiment.from_payload(sample_payload(guidance_direction="lowered")),
            ChunkSentiment.from_payload(sample_payload(guidance_direction="maintained")),
        ]
        chunks = [
            TranscriptChunk(0, "[management_answer] CFO:\nWe lowered guidance.", 50),
            TranscriptChunk(1, "[prepared_remarks] CEO:\nPrior guidance discussion.", 1000),
        ]

        result = aggregate_sentiments(analyses, chunks)

        self.assertEqual(result["guidance_direction"], "lowered")


CALL = """Management: We are raising our revenue growth guidance for FY27 to 30%
from 25% earlier. Our order book stands at Rs 4,200 crore, which is 2.5 years of
revenue. The new Hosur plant started commercial production in July. Demand from
export customers remains very strong. We expect raw material costs to keep
margins under pressure for two more quarters."""


def extraction(**overrides):
    base = {
        "guidance": {
            "direction": "raised", "metric": "revenue growth", "growth_pct": 30,
            "quote": "We are raising our revenue growth guidance for FY27 to 30% from 25% earlier.",
        },
        "order_book": {
            "value_inr_crore": 4200, "revenue_cover_years": 2.5, "trend": "up",
            "quote": "Our order book stands at Rs 4,200 crore, which is 2.5 years of revenue.",
        },
        "capacity": {
            "state": "ramping", "commissioning": "2026-07",
            "quote": "The new Hosur plant started commercial production in July.",
        },
        "demand": {"tone": "strong", "quote": "Demand from export customers remains very strong."},
        "margin": {
            "trend": "down",
            "quote": "We expect raw material costs to keep margins under pressure for two more quarters.",
        },
        "tailwinds": [],
        "headwinds": [],
    }
    base.update(overrides)
    return base


class OutlookQuoteTests(unittest.TestCase):
    def test_a_quote_survives_line_breaks_and_case(self):
        verified, kept, dropped = verify_quotes(extraction(), CALL)
        # The guidance sentence wraps across two lines in the transcript.
        self.assertEqual(verified["guidance"]["direction"], "raised")
        self.assertEqual((kept, dropped), (5, 0))

    def test_an_invented_figure_is_cleared_and_counted(self):
        invented = extraction(
            order_book={
                "value_inr_crore": 9000, "revenue_cover_years": 5, "trend": "up",
                "quote": "Our order book has crossed Rs 9,000 crore, five years of revenue.",
            }
        )
        verified, kept, dropped = verify_quotes(invented, CALL)
        self.assertIsNone(verified["order_book"]["value_inr_crore"])
        self.assertEqual(verified["order_book"]["trend"], "unknown")
        self.assertEqual((kept, dropped), (4, 1))

    def test_a_claim_without_a_quote_is_not_kept(self):
        unquoted = extraction(demand={"tone": "strong", "quote": None})
        verified, _, dropped = verify_quotes(unquoted, CALL)
        self.assertEqual(verified["demand"]["tone"], "unknown")
        self.assertEqual(dropped, 1)

    def test_a_section_that_claims_nothing_is_neither_kept_nor_dropped(self):
        silent = extraction(capacity={"state": "none", "commissioning": None, "quote": None})
        _, kept, dropped = verify_quotes(silent, CALL)
        self.assertEqual((kept, dropped), (4, 0))

    def test_a_two_word_quote_proves_nothing(self):
        self.assertFalse(quote_found("very strong", "demand remains very strong"))

    def test_a_bare_agreement_is_not_a_margin_outlook(self):
        call = CALL + "\nAnalyst: So margins improve from here? Management: Yes, that is correct."
        agreed = extraction(margin={"trend": "up", "quote": "Yes, that is correct."})
        verified, kept, dropped = verify_quotes(agreed, call)
        self.assertEqual(verified["margin"]["trend"], "unknown")
        self.assertEqual((kept, dropped), (4, 1))
        # The same four words are still enough for any other section.
        self.assertTrue(quote_found("Yes, that is correct.", "management yes that is correct."))

    def test_a_scope_alone_claims_nothing(self):
        silent = extraction(guidance={
            "direction": "none", "scope": "company", "metric": None, "growth_pct": None, "quote": None,
        })
        verified, kept, dropped = verify_quotes(silent, CALL)
        self.assertEqual(verified["guidance"]["scope"], "none")
        self.assertEqual((kept, dropped), (4, 0))

    def test_list_items_are_checked_one_by_one(self):
        listed = extraction(
            tailwinds=[
                {"what": "new plant", "quote": "The new Hosur plant started commercial production in July."},
                {"what": "PLI approval", "quote": "We have received approval under the PLI scheme this quarter."},
            ]
        )
        verified, kept, dropped = verify_quotes(listed, CALL)
        self.assertEqual([item["what"] for item in verified["tailwinds"]], ["new plant"])
        self.assertEqual((kept, dropped), (6, 1))


class OutlookScoreTests(unittest.TestCase):
    def score(self, **overrides):
        verified, _, _ = verify_quotes(extraction(**overrides), CALL)
        return outlook_score(verified), dict(outlook_points(verified))

    def test_a_call_that_says_nothing_is_neutral(self):
        verified, _, _ = verify_quotes({}, CALL)
        self.assertEqual(outlook_score(verified), 50.0)
        self.assertEqual(outlook_points(verified), [])

    def test_each_verified_item_moves_the_score_by_its_declared_points(self):
        score, points = self.score()
        self.assertEqual(points["guidance raised"], 15.0)
        self.assertEqual(points["guided revenue growth 25% or more"], 10.0)
        self.assertEqual(points["order book rising"], 8.0)
        self.assertEqual(points["order book covers two years or more of revenue"], 6.0)
        self.assertEqual(points["new capacity producing"], 6.0)
        self.assertEqual(points["demand outlook strong"], 8.0)
        self.assertEqual(points["margin outlook worsening"], -8.0)
        self.assertEqual(score, 95.0)

    def test_lowered_guidance_costs_more_than_raised_guidance_earns(self):
        lowered = {"direction": "lowered", "metric": None, "growth_pct": None,
                   "quote": "We are raising our revenue growth guidance for FY27 to 30% from 25% earlier."}
        _, points = self.score(guidance=lowered)
        self.assertEqual(points["guidance lowered"], -20.0)

    def test_growth_guided_for_a_segment_scores_as_the_companys(self):
        segment = {"direction": "maintained", "scope": "segment", "metric": "oncology revenue", "growth_pct": 100,
                   "quote": "We are raising our revenue growth guidance for FY27 to 30% from 25% earlier."}
        _, points = self.score(guidance=segment)
        self.assertEqual(points["guidance maintained"], 3.0)
        self.assertEqual(points["guided revenue growth 25% or more"], 10.0)

    def test_an_outlook_stored_before_scopes_scores_as_it_did(self):
        # The fixture carries no scope, as every outlook stored before 2026-10-09.
        _, points = self.score()
        self.assertEqual(points["guided revenue growth 25% or more"], 10.0)

    def test_planned_capacity_is_worth_almost_nothing(self):
        planned = {"state": "planned", "commissioning": None,
                   "quote": "The new Hosur plant started commercial production in July."}
        _, points = self.score(capacity=planned)
        self.assertEqual(points["capacity planned"], 1.0)

    def test_the_score_is_bounded(self):
        verified, _, _ = verify_quotes(extraction(), CALL)
        verified["tailwinds"] = [{"what": str(index), "quote": "q"} for index in range(3)]
        self.assertLessEqual(outlook_score(verified), 100.0)


class OutlookRequestTests(unittest.TestCase):
    def test_messages_carry_the_company_and_the_transcript(self):
        system, user = build_messages("Acme Ltd", "ACME", "2026-08-10", CALL)
        self.assertEqual(system["role"], "system")
        self.assertIn("Acme Ltd (ACME)", user["content"])
        self.assertIn("order book stands at", user["content"])

    def test_every_schema_section_is_required(self):
        self.assertEqual(
            set(SCHEMA["required"]),
            {"guidance", "order_book", "capacity", "demand", "margin", "tailwinds", "headwinds"},
        )

    def test_a_fenced_response_is_still_parsed(self):
        payload = {
            "choices": [{"message": {"content": "```json\n{\"demand\": {\"tone\": \"weak\", \"quote\": null}}\n```"}}],
            "usage": {"prompt_tokens": 12000, "completion_tokens": 300, "cost": 0.00096},
        }
        parsed, usage = parse_response(payload)
        self.assertEqual(parsed["demand"]["tone"], "weak")
        self.assertEqual(usage["prompt_tokens"], 12000)

    def test_a_response_without_json_is_an_error(self):
        with self.assertRaises(ValueError):
            parse_response({"choices": [{"message": {"content": "I cannot help with that."}}]})
        with self.assertRaises(ValueError):
            parse_response({"choices": []})

    def test_a_reply_cut_off_at_the_output_limit_is_an_error_that_keeps_its_cost(self):
        from sentiment.outlook import ExtractionError

        payload = {
            "choices": [{"finish_reason": "length", "message": {"content": "{\"demand\": {"}}],
            "usage": {"cost": 0.0053},
        }
        with self.assertRaises(ExtractionError) as raised:
            parse_response(payload)
        self.assertAlmostEqual(raised.exception.cost_usd, 0.0053)


class OutlookItemTests(unittest.TestCase):
    def test_each_scored_item_carries_the_sentence_it_came_from(self):
        from sentiment.outlook import _EMPTY, outlook_items

        verified = {section: dict(empty) for section, empty in _EMPTY.items()}
        verified["guidance"] = {"direction": "raised", "metric": "revenue", "growth_pct": 30, "quote": "G"}
        verified["demand"] = {"tone": "weak", "quote": "D"}
        verified["tailwinds"] = [{"what": "new approval", "quote": "T"}]
        verified["headwinds"] = []

        self.assertEqual(outlook_items(verified), [
            ("guidance raised", 15.0, "G"),
            ("guided revenue growth 25% or more", 10.0, "G"),
            ("demand outlook weak", -10.0, "D"),
            ("tailwind: new approval", 2.0, "T"),
        ])
        self.assertEqual(outlook_points(verified), [
            ("guidance raised", 15.0),
            ("guided revenue growth 25% or more", 10.0),
            ("demand outlook weak", -10.0),
            ("tailwind: new approval", 2.0),
        ])


class OutlookChangeTests(unittest.TestCase):
    def changes(self, previous, current):
        from sentiment.outlook import compare_outlooks

        return {item["item"]: (item["change"], item["text"]) for item in compare_outlooks(previous, current)}

    def test_guided_growth_is_compared_as_a_number_whatever_the_label(self):
        # "Maintained" on both calls, and five points lower: that is a cut.
        changes = self.changes(
            {"guidance": {"direction": "maintained", "growth_pct": 20}},
            {"guidance": {"direction": "maintained", "growth_pct": 15}},
        )
        self.assertEqual(changes["guidance"], ("worse", "guided growth cut 20% -> 15%"))

    def test_a_segments_growth_is_not_compared_with_the_companys(self):
        changes = self.changes(
            {"guidance": {"direction": "maintained", "scope": "company", "growth_pct": 40}},
            {"guidance": {"direction": "maintained", "scope": "segment", "growth_pct": 100}},
        )
        self.assertEqual(changes["guidance"], ("kept", "guidance maintained"))

    def test_guided_growth_within_a_point_is_kept(self):
        changes = self.changes(
            {"guidance": {"direction": "maintained", "growth_pct": 15}},
            {"guidance": {"direction": "maintained", "growth_pct": 15.5}},
        )
        self.assertEqual(changes["guidance"][0], "kept")

    def test_guidance_given_and_then_dropped_is_flagged_not_penalised(self):
        changes = self.changes(
            {"guidance": {"direction": "raised", "growth_pct": 20}},
            {"guidance": {"direction": "none", "growth_pct": None}},
        )
        self.assertEqual(changes["guidance"], ("not_restated", "guidance not restated"))

    def test_an_item_one_call_did_not_state_is_not_a_change(self):
        changes = self.changes(
            {"demand": {"tone": "unknown"}, "margin": {"trend": "up"}, "guidance": {"direction": "none"}},
            {"demand": {"tone": "weak"}, "margin": {"trend": "unknown"}, "guidance": {"direction": "raised"}},
        )
        self.assertEqual(changes, {})

    def test_demand_and_margin_move_along_their_scale(self):
        changes = self.changes(
            {"demand": {"tone": "strong"}, "margin": {"trend": "down"}},
            {"demand": {"tone": "stable"}, "margin": {"trend": "up"}},
        )
        self.assertEqual(changes["demand"], ("worse", "demand outlook strong -> stable"))
        self.assertEqual(changes["margin"], ("better", "margin outlook down -> up"))

    def test_order_book_moves_past_the_tolerance(self):
        changes = self.changes(
            {"order_book": {"value_inr_crore": 1000}}, {"order_book": {"value_inr_crore": 1300}}
        )
        self.assertEqual(changes["order_book"], ("better", "order book up 30%, 1,000 -> 1,300 crore"))
        steady = self.changes(
            {"order_book": {"value_inr_crore": 1000}}, {"order_book": {"value_inr_crore": 1020}}
        )
        self.assertEqual(steady["order_book"][0], "kept")

    def test_a_later_commissioning_date_is_a_slip(self):
        changes = self.changes(
            {"capacity": {"state": "under_construction", "commissioning": "2026-12"}},
            {"capacity": {"state": "under_construction", "commissioning": "2027-03"}},
        )
        self.assertEqual(changes["capacity"], ("worse", "commissioning slipped 2026-12 -> 2027-03"))

    def test_capacity_moving_on_a_stage_is_progress_and_back_a_stage_is_nothing(self):
        forward = self.changes(
            {"capacity": {"state": "under_construction"}}, {"capacity": {"state": "operational"}}
        )
        self.assertEqual(forward["capacity"], ("better", "capacity progressed under construction -> operational"))
        back = self.changes(
            {"capacity": {"state": "operational"}}, {"capacity": {"state": "planned"}}
        )
        self.assertNotIn("capacity", back)

    def test_summary_lists_what_moved_worst_first_and_counts_the_rest(self):
        from sentiment.outlook import summarise_changes

        summary = summarise_changes([
            {"item": "demand", "change": "kept", "text": "demand outlook still strong"},
            {"item": "margin", "change": "better", "text": "margin outlook down -> up"},
            {"item": "guidance", "change": "worse", "text": "guidance lowered"},
        ])
        self.assertEqual(summary, "guidance lowered; margin outlook down -> up; 1 item unchanged")
        self.assertEqual(summarise_changes([]), "")


class OutlookRunTests(unittest.TestCase):
    """The extraction run, with the API and the database replaced by fakes."""

    def setUp(self):
        from tools import extract_transcript_outlook as tool

        self.tool = tool

    def repository(self, texts):
        saved = []

        class Repository:
            def restore_transcript_text(self, transcript):
                return texts.get(transcript["id"])

            def save_outlook(self, row):
                saved.append(row)

        return Repository(), saved

    def fake_analyse(self, cost):
        def analyse(session, api_key, transcript, text, *, model):
            return {
                "transcript_id": transcript["id"], "cost_usd": cost,
                "verified_fields": 3, "unverified_fields": 1,
            }

        return analyse

    def test_estimate_scales_with_transcript_length(self):
        rows = [{"token_count": 10_000}, {"token_count": 12_000}]
        estimate = self.tool.estimate_cost(rows, self.tool.DEFAULT_MODEL)
        prompt = (10_000 + 12_000) * 1.25 + 2 * 1000
        # Priced at the most a request may pay, so the estimate is a ceiling.
        self.assertAlmostEqual(estimate, (prompt * 0.10 + 2 * 800 * 1.20) / 1_000_000)
        self.assertIsNone(self.tool.estimate_cost(rows, "someone/unpriced-model"))

    def test_an_unusable_reply_still_counts_toward_the_budget(self):
        from sentiment.outlook import ExtractionError

        def analyse(session, api_key, transcript, text, *, model):
            raise ExtractionError("response carried no JSON object", cost_usd=0.004)

        repository, saved = self.repository({})
        budget = self.tool.Budget(1.0)
        with patch.object(self.tool, "analyse_transcript", analyse):
            summary = self.tool.run(
                repository, [{"id": "t1", "cleaned_text": "call text"}], "key",
                model="m", workers=1, budget=budget,
            )

        self.assertEqual(summary["failed"], 1)
        self.assertEqual(saved, [])
        self.assertAlmostEqual(budget.spent, 0.004)

    def test_latest_only_keeps_each_companys_newest_call(self):
        class Repository:
            def outlook_transcript_ids(self, model, version):
                return {"b2"}

            def transcripts_for_outlook(self):
                # Newest call first, as the repository returns them.
                return [
                    {"id": "a2", "symbol": "AAA", "call_date": "2026-08-10"},
                    {"id": "b2", "symbol": "BBB", "call_date": "2026-08-05"},
                    {"id": "a1", "symbol": "AAA", "call_date": "2026-05-12"},
                    {"id": "b1", "symbol": "BBB", "call_date": "2026-05-08"},
                ]

        everything = self.tool.pending_transcripts(Repository(), "m")
        latest = self.tool.pending_transcripts(Repository(), "m", latest_only=True)

        self.assertEqual([row["id"] for row in everything], ["a2", "a1", "b1"])
        # BBB's newest call is done; its older one is not picked up in its place.
        self.assertEqual([row["id"] for row in latest], ["a2"])

    def test_text_is_restored_from_storage_and_the_row_saved(self):
        repository, saved = self.repository({"t1": "archived call text"})
        with patch.object(self.tool, "analyse_transcript", self.fake_analyse(0.002)):
            summary = self.tool.run(
                repository, [{"id": "t1", "cleaned_text": ""}], "key",
                model="m", workers=1, budget=self.tool.Budget(1.0),
            )
        self.assertEqual(summary["extracted"], 1)
        self.assertEqual((summary["verified"], summary["unverified"]), (3, 1))
        self.assertEqual(saved[0]["transcript_id"], "t1")

    def test_a_transcript_without_text_fails_without_stopping_the_run(self):
        repository, saved = self.repository({"t2": "text"})
        with patch.object(self.tool, "analyse_transcript", self.fake_analyse(0.002)):
            summary = self.tool.run(
                repository,
                [{"id": "t1", "cleaned_text": ""}, {"id": "t2", "cleaned_text": ""}],
                "key", model="m", workers=1, budget=self.tool.Budget(1.0),
            )
        self.assertEqual((summary["extracted"], summary["failed"]), (1, 1))
        self.assertEqual([row["transcript_id"] for row in saved], ["t2"])

    def test_the_run_stops_submitting_once_the_budget_is_spent(self):
        repository, saved = self.repository({})
        transcripts = [{"id": f"t{index}", "cleaned_text": "text"} for index in range(5)]
        with patch.object(self.tool, "analyse_transcript", self.fake_analyse(0.5)):
            summary = self.tool.run(
                repository, transcripts, "key", model="m", workers=1,
                budget=self.tool.Budget(1.0),
            )
        self.assertEqual(summary["extracted"], 2)
        self.assertEqual(summary["skipped_budget"], 3)
        self.assertEqual(len(saved), 2)


if __name__ == "__main__":
    unittest.main()
