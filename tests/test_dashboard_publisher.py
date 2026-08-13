import json
import re
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from workers.dashboard_publisher import (
    HISTORY_COLUMNS,
    SNAPSHOT_COLUMNS,
    CoercionReport,
    build_payload,
    build_run_row,
    coerce,
    coerce_bool,
    coerce_int,
    coerce_numeric,
    map_row,
    publish,
    resolve_run_date,
)


def minimal_frame(**overrides):
    row = {
        "Symbol": "INFY",
        "Company": "Infosys Limited",
        "Sector": "Technology",
        "Rating": "BUY",
        "Investment_Rank": 3,
        "Decision_Score": 64.25,
        "Final_Score": 64.25,
        "Current_Price": 1520.5,
        "Price_Bar_As_Of": "2026-08-11",
        "Analysis_As_Of": "2026-08-11T16:31:08+05:30",
    }
    row.update(overrides)
    return pd.DataFrame([row])


class CoercionTests(unittest.TestCase):
    def test_numeric_out_of_range_is_dropped_not_wrapped(self):
        # numeric(6,2) tops out below 10000; a larger value must become null
        # rather than silently reaching Postgres and failing the whole batch.
        self.assertIsNone(coerce_numeric(10000.0, 6, 2))
        self.assertEqual(coerce_numeric(9999.99, 6, 2), 9999.99)
        self.assertEqual(coerce_numeric(-64.257, 6, 2), -64.26)

    def test_integer_beyond_postgres_int4_is_dropped(self):
        self.assertIsNone(coerce_int(2_147_483_648))
        self.assertEqual(coerce_int(2_147_483_647), 2_147_483_647)

    def test_missing_markers_become_null(self):
        for marker in [None, float("nan"), "", "  ", "nan", "None", "-"]:
            self.assertIsNone(coerce_numeric(marker, 6, 2))
            self.assertIsNone(coerce_bool(marker))
            self.assertIsNone(coerce_int(marker))

    def test_infinity_is_not_written(self):
        self.assertIsNone(coerce_numeric(float("inf"), 12, 2))
        self.assertIsNone(coerce_numeric(float("-inf"), 12, 2))

    def test_bool_accepts_csv_string_forms(self):
        for truthy in ["True", "true", "TRUE", "yes", "1", True]:
            self.assertIs(coerce_bool(truthy), True)
        for falsy in ["False", "false", "no", "0", False]:
            self.assertIs(coerce_bool(falsy), False)

    def test_unrecognised_bool_is_reported_not_guessed(self):
        report = CoercionReport()
        self.assertIsNone(coerce(" maybe ", "bool", "Buy_Eligible", report))
        self.assertEqual(report.unparseable["Buy_Eligible"], 1)

    def test_dropped_values_are_counted_for_the_run_summary(self):
        report = CoercionReport()
        coerce(10**9, "num:6,2", "Decision_Score", report)
        coerce(10**9, "num:6,2", "Decision_Score", report)
        self.assertEqual(report.out_of_range["Decision_Score"], 2)
        self.assertIn("Decision_Score=2", report.summary())


class PayloadTests(unittest.TestCase):
    def test_payload_is_json_serialisable_without_nan(self):
        payload = build_payload({"a": float("nan"), "b": 1.5, "c": "x", "d": None})
        # json.dumps would happily emit bare NaN, which PostgREST rejects.
        self.assertNotIn("NaN", json.dumps(payload))
        self.assertIsNone(payload["a"])
        self.assertEqual(payload["b"], 1.5)

    def test_payload_preserves_unmapped_columns(self):
        # The long tail of audit columns reaches drill-down only via payload.
        payload = build_payload({"Symbol": "INFY", "Some_Future_Column": 42})
        self.assertEqual(payload["Some_Future_Column"], 42)

    def test_numpy_scalars_are_unwrapped(self):
        frame = pd.DataFrame([{"n": 5, "f": 1.25, "b": True}])
        payload = build_payload(frame.to_dict(orient="records")[0])
        json.dumps(payload)  # must not raise
        self.assertEqual(payload["n"], 5)


class MappingTests(unittest.TestCase):
    def test_absent_column_maps_to_null_rather_than_being_omitted(self):
        # Omitting the key would let a stale value survive a re-ingest of the
        # same date, because the upsert merges rather than replaces.
        columns = [("decision_score", "Decision_Score", "num:6,2")]
        mapped = map_row({"Symbol": "INFY"}, columns, CoercionReport())
        self.assertIn("decision_score", mapped)
        self.assertIsNone(mapped["decision_score"])


class FactorModelMappingTests(unittest.TestCase):
    """Model 5.0 evidence has to survive the trip into the read model."""

    @staticmethod
    def mapped(row):
        return map_row(row, SNAPSHOT_COLUMNS, CoercionReport())

    def test_factor_columns_are_mapped(self):
        mapped = self.mapped(
            {
                "Symbol": "INFY",
                "Factor_Model_Applied": True,
                "Research_Score": 87.5,
                "Research_Score_Raw": 61.2,
                "Quality_Percentile": 92.31,
                "Momentum_Percentile": 74.0,
                "Eligibility_Class": 1,
                "Primary_Gate": "LOW_QUALITY",
                "Gate_Severity": 3,
                "Market_Regime": "RISK_ON",
                "Price_To_MA200_Pct": 12.345,
                "ROIC": 0.2841,
            }
        )
        self.assertIs(mapped["factor_model_applied"], True)
        self.assertEqual(mapped["research_score"], 87.5)
        self.assertEqual(mapped["research_score_raw"], 61.2)
        self.assertEqual(mapped["quality_percentile"], 92.31)
        self.assertEqual(mapped["eligibility_class"], 1)
        self.assertEqual(mapped["primary_gate"], "LOW_QUALITY")
        self.assertEqual(mapped["gate_severity"], 3)
        self.assertEqual(mapped["market_regime"], "RISK_ON")
        self.assertEqual(mapped["roic"], 0.2841)

    def test_four_x_row_clears_factor_columns_rather_than_omitting_them(self):
        # The upsert merges, so omitting these keys would leave a previous
        # factor run's values attached to a 4.x row for the same date.
        mapped = self.mapped({"Symbol": "INFY", "Decision_Score": 64.0})
        for column in (
            "factor_model_applied",
            "research_score",
            "quality_percentile",
            "eligibility_class",
            "primary_gate",
            "market_regime",
        ):
            self.assertIn(column, mapped)
            self.assertIsNone(mapped[column])

    def test_eligibility_class_zero_survives(self):
        # Class 0 is the BEST class, and a falsy-value bug here would silently
        # demote every fully-eligible row.
        mapped = self.mapped({"Symbol": "INFY", "Eligibility_Class": 0})
        self.assertEqual(mapped["eligibility_class"], 0)
        self.assertIsNotNone(mapped["eligibility_class"])

    def test_negative_drawdown_is_preserved(self):
        mapped = self.mapped({"Symbol": "INFY", "Max_Drawdown_1Y_Pct": -42.5})
        self.assertEqual(mapped["max_drawdown_1y_pct"], -42.5)

    def test_signed_trend_quality_is_preserved(self):
        # Trend quality is signed on [-1, 1]; a clean downtrend is -1, and
        # dropping the sign would make it the best possible reading.
        mapped = self.mapped({"Symbol": "INFY", "Trend_Quality_R2": -0.9812})
        self.assertEqual(mapped["trend_quality_r2"], -0.9812)

    def test_history_carries_the_model_five_movement_fields(self):
        mapped = map_row(
            {
                "Symbol": "INFY",
                "Research_Score": 88.0,
                "Eligibility_Class": 2,
                "Primary_Gate": "ILLIQUID",
            },
            HISTORY_COLUMNS,
            CoercionReport(),
        )
        self.assertEqual(mapped["research_score"], 88.0)
        self.assertEqual(mapped["eligibility_class"], 2)
        self.assertEqual(mapped["primary_gate"], "ILLIQUID")

    def test_snapshot_and_schema_column_names_agree(self):
        # A typo here writes a column PostgREST does not have and fails the
        # whole batch, so the mapping is checked against the DDL itself.
        schema = Path("storage/dashboard_schema.sql").read_text(encoding="utf-8")
        body = schema.split("create table if not exists screener_snapshot", 1)[1]
        body = body.split("primary key", 1)[0]
        declared = set(re.findall(r"^\s{4}([a-z0-9_]+)\s", body, re.MULTILINE))
        for db_column, _, _ in SNAPSHOT_COLUMNS:
            self.assertIn(
                db_column,
                declared,
                f"{db_column} is published but not declared in screener_snapshot",
            )


class RunDateTests(unittest.TestCase):
    def test_price_bar_as_of_wins_over_filename(self):
        frame = minimal_frame()
        resolved = resolve_run_date(frame, Path("advanced_analysis_20260101.csv"), None)
        self.assertEqual(resolved, "2026-08-11")

    def test_analysis_as_of_is_used_when_bar_date_absent(self):
        frame = minimal_frame().drop(columns=["Price_Bar_As_Of"])
        resolved = resolve_run_date(frame, Path("advanced_analysis_20260101.csv"), None)
        self.assertEqual(resolved, "2026-08-11")

    def test_filename_is_the_last_resort(self):
        frame = minimal_frame().drop(columns=["Price_Bar_As_Of", "Analysis_As_Of"])
        resolved = resolve_run_date(frame, Path("advanced_analysis_20260101.csv"), None)
        self.assertEqual(resolved, "2026-01-01")

    def test_undateable_export_raises_instead_of_guessing_today(self):
        frame = minimal_frame().drop(columns=["Price_Bar_As_Of", "Analysis_As_Of"])
        with self.assertRaises(ValueError):
            resolve_run_date(frame, Path("export.csv"), None)

    def test_override_wins(self):
        frame = minimal_frame()
        self.assertEqual(
            resolve_run_date(frame, Path("advanced_analysis_20260101.csv"), "2026-07-04"),
            "2026-07-04",
        )


class RunRowTests(unittest.TestCase):
    def test_rating_counts_are_precomputed(self):
        frame = pd.DataFrame(
            [
                {"Symbol": "A", "Rating": "STRONG BUY"},
                {"Symbol": "B", "Rating": "BUY"},
                {"Symbol": "C", "Rating": "buy"},
                {"Symbol": "D", "Rating": "HOLD"},
            ]
        )
        run = build_run_row(frame, "2026-08-11", None)
        self.assertEqual(run["strong_buy_count"], 1)
        self.assertEqual(run["buy_count"], 2)  # case-insensitive
        self.assertEqual(run["hold_count"], 1)
        self.assertEqual(run["sell_count"], 0)
        self.assertEqual(run["row_count"], 4)


class PublishTests(unittest.TestCase):
    def test_dry_run_reports_drift_without_failing(self):
        with TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "advanced_analysis_20260811.csv"
            minimal_frame().to_csv(csv_path, index=False)

            summary = publish(csv_path=csv_path, dry_run=True)

        self.assertEqual(summary["rows"], 1)
        self.assertEqual(summary["run_date"], "2026-08-11")
        # A narrow export is a reportable condition, not a load failure.
        self.assertIn("Gate_Failures", summary["missing_columns"])
        self.assertEqual(summary["coercion"], "no values dropped")

    def test_duplicate_symbols_are_skipped_and_reported(self):
        with TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "advanced_analysis_20260811.csv"
            pd.concat([minimal_frame(), minimal_frame()]).to_csv(csv_path, index=False)

            summary = publish(csv_path=csv_path, dry_run=True)

        self.assertEqual(summary["rows"], 1)
        self.assertEqual(summary["duplicate_symbols"], ["INFY"])

    def test_export_without_symbol_column_is_rejected(self):
        with TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "advanced_analysis_20260811.csv"
            pd.DataFrame([{"Company": "Infosys"}]).to_csv(csv_path, index=False)

            with self.assertRaises(ValueError):
                publish(csv_path=csv_path, dry_run=True)


if __name__ == "__main__":
    unittest.main()


class EnvFileTests(unittest.TestCase):
    def test_existing_environment_wins_over_file(self):
        import os

        from workers.dashboard_publisher import load_env_file

        with TemporaryDirectory() as tmp:
            env = Path(tmp) / ".env"
            env.write_text(
                "# comment\nSUPABASE_URL=https://from-file\nOTHER_KEY='quoted'\n\n",
                encoding="utf-8",
            )
            os.environ["SUPABASE_URL"] = "https://already-set"
            os.environ.pop("OTHER_KEY", None)
            try:
                load_env_file(env)
                # A CI-injected value must never be clobbered by a stray local file.
                self.assertEqual(os.environ["SUPABASE_URL"], "https://already-set")
                self.assertEqual(os.environ["OTHER_KEY"], "quoted")
            finally:
                os.environ.pop("SUPABASE_URL", None)
                os.environ.pop("OTHER_KEY", None)

    def test_missing_file_is_not_an_error(self):
        from workers.dashboard_publisher import load_env_file

        self.assertEqual(load_env_file(Path("does-not-exist.env")), 0)
