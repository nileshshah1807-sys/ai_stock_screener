"""Publish a screener CSV into the Supabase dashboard read model.

Run after a successful screener run:

    python -m workers.dashboard_publisher --csv reports_advanced/advanced_analysis_20260812.csv

The screener's column set grows as evidence stages add audit fields, so this
publisher is written to tolerate both directions of drift: a CSV missing a
mapped column writes null for it, and a CSV carrying unmapped columns still
reaches the dashboard through `payload`. Neither case fails the load, because a
schema mismatch should degrade the dashboard's filters, not block the day's
data entirely.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from storage.dashboard_repository import DashboardRepository

logger = logging.getLogger("dashboard_publisher")

RATING_COUNT_FIELDS = {
    "STRONG BUY": "strong_buy_count",
    "BUY": "buy_count",
    "HOLD": "hold_count",
    "REDUCE": "reduce_count",
    "SELL": "sell_count",
}

TRUE_TOKENS = {"true", "t", "yes", "y", "1"}
FALSE_TOKENS = {"false", "f", "no", "n", "0"}


# (db_column, csv_column, kind). `kind` is either a scalar type name or
# "num:precision,scale" matching the column definition in dashboard_schema.sql,
# so an out-of-range value is caught here instead of being rejected by Postgres
# mid-batch.
SNAPSHOT_COLUMNS: list[tuple[str, str, str]] = [
    ("symbol", "Symbol", "text"),
    ("company", "Company", "text"),
    ("sector", "Sector", "text"),
    ("industry", "Industry", "text"),

    ("investment_rank", "Investment_Rank", "int"),
    ("score_rank", "Score_Rank", "int"),
    ("recommendation_rank", "Recommendation_Rank", "int"),
    ("actionable_rank", "Actionable_Rank", "int"),

    ("fundamental_score", "Fundamental_Score", "num:6,2"),
    ("technical_score", "Technical_Score", "num:6,2"),
    ("combined_score", "Combined_Score", "num:6,2"),
    ("score_after_dcf", "Score_After_DCF", "num:6,2"),
    ("evidence_score", "Evidence_Score", "num:6,2"),
    ("decision_score_ceiling", "Decision_Score_Ceiling", "num:6,2"),
    ("decision_score", "Decision_Score", "num:6,2"),
    ("final_score", "Final_Score", "num:6,2"),

    ("rating", "Rating", "text"),
    ("investment_rating", "Investment_Rating", "text"),
    ("evidence_rating", "Evidence_Rating", "text"),
    ("decision_rating", "Decision_Rating", "text"),
    ("pre_dcf_rating", "Pre_DCF_Rating", "text"),

    ("buy_eligible", "Buy_Eligible", "bool"),
    ("strong_buy_eligible", "Strong_Buy_Eligible", "bool"),
    ("trend_confirmed", "Trend_Confirmed", "bool"),
    ("coverage_eligible", "Coverage_Eligible", "bool"),
    ("rating_capped", "Rating_Capped", "bool"),
    ("rating_cap_reason", "Rating_Cap_Reason", "text"),
    ("decision_cap_applied", "Decision_Cap_Applied", "bool"),
    ("decision_cap_reason", "Decision_Cap_Reason", "text"),
    ("gate_failure_count", "Gate_Failure_Count", "int"),
    ("gate_failures", "Gate_Failures", "text"),
    ("gate_borderline", "Gate_Borderline", "bool"),
    ("decision_stability_status", "Decision_Stability_Status", "text"),
    ("data_quality", "Data_Quality", "text"),

    ("fundamental_coverage", "Fundamental_Coverage", "num:6,4"),
    ("technical_coverage", "Technical_Coverage", "num:6,4"),
    ("fund_fields_present", "Fund_Fields_Present", "int"),
    ("fund_fields_expected", "Fund_Fields_Expected", "int"),
    ("fundamental_model", "Fundamental_Model", "text"),
    ("specialized_quality_eligible", "Specialized_Quality_Eligible", "bool"),
    ("fundamental_anomaly", "Fundamental_Anomaly", "bool"),

    ("current_price", "Current_Price", "num:14,2"),
    ("pct_change_1m", "Pct_Change_1M", "num:10,2"),
    ("pct_change_3m", "Pct_Change_3M", "num:10,2"),
    ("pct_change_6m", "Pct_Change_6M", "num:10,2"),
    ("rsi_14", "RSI_14", "num:8,2"),
    ("adx_14", "ADX_14", "num:8,2"),

    ("market_cap", "Market_Cap", "num:20,2"),
    ("pe_ratio", "PE_Ratio", "num:12,2"),
    ("pb_ratio", "PB_Ratio", "num:12,2"),
    ("roe", "ROE", "num:12,4"),
    ("debt_to_equity", "Debt_to_Equity", "num:12,2"),
    ("revenue_growth", "Revenue_Growth", "num:12,4"),
    ("earnings_growth", "Earnings_Growth", "num:12,4"),
    ("dividend_yield", "Dividend_Yield", "num:12,4"),

    ("dcf_status", "DCF_Status", "text"),
    ("dcf_valuation_score", "DCF_Valuation_Score", "num:6,2"),
    ("dcf_base_case_upside", "DCF_Base_Case_Upside", "num:12,4"),
    ("dcf_assessment", "DCF_Assessment", "text"),
    ("dcf_blend_eligible", "DCF_Blend_Eligible", "bool"),

    ("transcript_status", "Transcript_Status", "text"),
    ("transcript_score", "Transcript_Score", "num:6,2"),
    ("transcript_scoring_eligible", "Transcript_Scoring_Eligible", "bool"),
    ("transcript_guidance", "Transcript_Guidance", "text"),
    ("transcript_age_days", "Transcript_Age_Days", "int"),

    ("red_flag_status", "Red_Flag_Status", "text"),
    ("red_flag_severity", "Red_Flag_Severity", "int"),
    ("red_flag_issuer_severity", "Red_Flag_Issuer_Severity", "int"),
    ("red_flag_trading_severity", "Red_Flag_Trading_Severity", "int"),
    ("red_flag_count", "Red_Flag_Count", "int"),
    ("shadow_red_flag_would_change", "Shadow_Red_Flag_Would_Change", "bool"),

    ("liquidity_grade", "Liquidity_Grade", "text"),
    ("liquidity_status", "Liquidity_Status", "text"),
    ("portfolio_actionable", "Portfolio_Actionable", "bool"),
    ("median_turnover_20d_inr", "Median_Turnover_20D_INR", "num:20,2"),
    ("nse_impact_cost_pct", "NSE_Impact_Cost_Pct", "num:10,4"),
    ("portfolio_estimated_build_days", "Portfolio_Estimated_Build_Days", "num:12,2"),

    ("price_bar_as_of", "Price_Bar_As_Of", "date"),
    ("price_bar_aligned", "Price_Bar_Aligned", "bool"),
    ("fund_data_stale", "Fund_Data_Stale", "bool"),
    ("news_sentiment", "News_Sentiment", "text"),

    # Model 5.0 factor architecture. A 4.x CSV has none of these columns, and
    # map_row writes null for an absent column rather than omitting the key, so
    # publishing a 4.x run against this schema clears them correctly instead of
    # leaving yesterday's factor values behind on a re-ingest.
    ("factor_model_applied", "Factor_Model_Applied", "bool"),
    ("research_score", "Research_Score", "num:6,2"),
    ("research_score_raw", "Research_Score_Raw", "num:6,2"),
    ("research_score_basis", "Research_Score_Basis", "text"),

    ("quality_score", "Quality_Score", "num:6,2"),
    ("growth_score", "Growth_Score", "num:6,2"),
    ("value_score", "Value_Score", "num:6,2"),
    ("momentum_score", "Momentum_Score", "num:6,2"),
    ("risk_score", "Risk_Score", "num:6,2"),
    ("quality_percentile", "Quality_Percentile", "num:6,2"),
    ("growth_percentile", "Growth_Percentile", "num:6,2"),
    ("value_percentile", "Value_Percentile", "num:6,2"),
    ("momentum_percentile", "Momentum_Percentile", "num:6,2"),
    ("risk_percentile", "Risk_Percentile", "num:6,2"),
    ("quality_coverage", "Quality_Coverage", "num:6,4"),
    ("growth_coverage", "Growth_Coverage", "num:6,4"),
    ("value_coverage", "Value_Coverage", "num:6,4"),
    ("momentum_coverage", "Momentum_Coverage", "num:6,4"),
    ("risk_coverage", "Risk_Coverage", "num:6,4"),
    ("factor_coverage", "Factor_Coverage", "num:6,4"),
    ("value_score_uncapped", "Value_Score_Uncapped", "num:6,2"),
    ("value_quality_cap_applied", "Value_Quality_Cap_Applied", "bool"),

    ("research_rating", "Research_Rating", "text"),
    ("policy_eligible_rating", "Policy_Eligible_Rating", "text"),
    ("execution_status", "Execution_Status", "text"),
    ("eligibility_class", "Eligibility_Class", "int"),
    ("primary_gate", "Primary_Gate", "text"),
    ("gate_severity", "Gate_Severity", "int"),
    ("market_regime", "Market_Regime", "text"),

    ("ma200", "MA200", "num:14,2"),
    ("ma200_slope_pct", "MA200_Slope_Pct", "num:10,4"),
    ("price_to_ma200_pct", "Price_To_MA200_Pct", "num:10,3"),
    ("ma50_to_ma200_pct", "MA50_To_MA200_Pct", "num:10,3"),
    ("below_ma200_streak", "Below_MA200_Streak", "int"),
    ("momentum_12_1_pct", "Momentum_12_1_Pct", "num:10,2"),
    ("momentum_6_1_pct", "Momentum_6_1_Pct", "num:10,2"),
    ("pct_change_12m", "Pct_Change_12M", "num:10,2"),
    ("rs_market_6m_pct", "RS_Market_6M_Pct", "num:10,3"),
    ("rs_market_12m_pct", "RS_Market_12M_Pct", "num:10,3"),
    ("rs_sector_6m_pct", "RS_Sector_6M_Pct", "num:10,3"),
    ("trend_quality_r2", "Trend_Quality_R2", "num:8,4"),

    ("volatility_ann_pct", "Volatility_Ann_Pct", "num:10,3"),
    ("max_drawdown_1y_pct", "Max_Drawdown_1Y_Pct", "num:10,3"),
    ("downside_deviation_pct", "Downside_Deviation_Pct", "num:10,3"),
    ("roic", "ROIC", "num:12,4"),
]

HISTORY_COLUMNS: list[tuple[str, str, str]] = [
    ("symbol", "Symbol", "text"),
    ("company", "Company", "text"),
    ("sector", "Sector", "text"),
    ("investment_rank", "Investment_Rank", "int"),
    ("actionable_rank", "Actionable_Rank", "int"),
    ("decision_score", "Decision_Score", "num:6,2"),
    ("evidence_score", "Evidence_Score", "num:6,2"),
    ("final_score", "Final_Score", "num:6,2"),
    ("fundamental_score", "Fundamental_Score", "num:6,2"),
    ("technical_score", "Technical_Score", "num:6,2"),
    ("rating", "Rating", "text"),
    ("current_price", "Current_Price", "num:14,2"),
    ("buy_eligible", "Buy_Eligible", "bool"),
    ("strong_buy_eligible", "Strong_Buy_Eligible", "bool"),
    ("rating_capped", "Rating_Capped", "bool"),
    # Model 5.0: the slim history exists to answer "what moved and what changed
    # rating". Under the factor model the published rating is capped, so
    # research score and eligibility class are what actually move first.
    ("research_score", "Research_Score", "num:6,2"),
    ("eligibility_class", "Eligibility_Class", "int"),
    ("primary_gate", "Primary_Gate", "text"),
]


class CoercionReport:
    """Counts values dropped during coercion.

    Silent nulling would let a unit or precision regression reach the dashboard
    unnoticed, so every drop is counted and surfaced in the run summary.
    """

    def __init__(self) -> None:
        self.out_of_range: dict[str, int] = {}
        self.unparseable: dict[str, int] = {}

    def record_out_of_range(self, column: str) -> None:
        self.out_of_range[column] = self.out_of_range.get(column, 0) + 1

    def record_unparseable(self, column: str) -> None:
        self.unparseable[column] = self.unparseable.get(column, 0) + 1

    @property
    def total(self) -> int:
        return sum(self.out_of_range.values()) + sum(self.unparseable.values())

    def summary(self) -> str:
        if not self.total:
            return "no values dropped"
        parts = []
        if self.out_of_range:
            worst = sorted(self.out_of_range.items(), key=lambda kv: -kv[1])[:5]
            parts.append(
                "out of range: " + ", ".join(f"{col}={n}" for col, n in worst)
            )
        if self.unparseable:
            worst = sorted(self.unparseable.items(), key=lambda kv: -kv[1])[:5]
            parts.append(
                "unparseable: " + ", ".join(f"{col}={n}" for col, n in worst)
            )
        return "; ".join(parts)


def is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return True
    if isinstance(value, str) and value.strip() in {"", "nan", "NaN", "None", "-"}:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def coerce_text(value: Any) -> str | None:
    if is_missing(value):
        return None
    text = str(value).strip()
    return text or None


def coerce_bool(value: Any) -> bool | None:
    if is_missing(value):
        return None
    if isinstance(value, bool):
        return value
    token = str(value).strip().lower()
    if token in TRUE_TOKENS:
        return True
    if token in FALSE_TOKENS:
        return False
    return None


def coerce_int(value: Any) -> int | None:
    if is_missing(value):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    # Postgres `integer` is 32-bit; a larger value must be dropped rather than
    # wrapped, because a wrapped rank or count would be silently wrong.
    if not -2_147_483_648 <= number <= 2_147_483_647:
        return None
    return int(round(number))


def coerce_numeric(value: Any, precision: int, scale: int) -> float | None:
    if is_missing(value):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    limit = 10 ** (precision - scale)
    if abs(number) >= limit:
        return None
    return round(number, scale)


def coerce_date(value: Any) -> str | None:
    if is_missing(value):
        return None
    try:
        parsed = pd.to_datetime(value, errors="coerce", utc=False)
    except (TypeError, ValueError):
        return None
    if parsed is None or pd.isna(parsed):
        return None
    return parsed.date().isoformat()


def coerce_timestamp(value: Any) -> str | None:
    if is_missing(value):
        return None
    try:
        parsed = pd.to_datetime(value, errors="coerce", utc=True)
    except (TypeError, ValueError):
        return None
    if parsed is None or pd.isna(parsed):
        return None
    return parsed.isoformat()


def coerce(value: Any, kind: str, column: str, report: CoercionReport) -> Any:
    if kind == "text":
        return coerce_text(value)
    if kind == "bool":
        result = coerce_bool(value)
        if result is None and not is_missing(value):
            report.record_unparseable(column)
        return result
    if kind == "int":
        result = coerce_int(value)
        if result is None and not is_missing(value):
            report.record_out_of_range(column)
        return result
    if kind == "date":
        return coerce_date(value)
    if kind == "timestamp":
        return coerce_timestamp(value)
    if kind.startswith("num:"):
        precision, scale = (int(part) for part in kind[4:].split(","))
        result = coerce_numeric(value, precision, scale)
        if result is None and not is_missing(value):
            report.record_out_of_range(column)
        return result
    raise ValueError(f"Unknown coercion kind: {kind}")


def json_safe(value: Any) -> Any:
    """Convert one CSV cell into something `json.dumps` accepts.

    NaN is JSON-invalid but `json.dumps` emits it by default, producing a body
    PostgREST rejects. Normalising to null here keeps the payload parseable.
    """
    if is_missing(value):
        return None
    if isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return None if (math.isnan(value) or math.isinf(value)) else value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if hasattr(value, "item"):  # numpy scalar
        try:
            return json_safe(value.item())
        except (AttributeError, ValueError):
            pass
    return str(value)


def build_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {key: json_safe(value) for key, value in row.items()}


def map_row(
    row: dict[str, Any],
    columns: list[tuple[str, str, str]],
    report: CoercionReport,
) -> dict[str, Any]:
    mapped: dict[str, Any] = {}
    for db_column, csv_column, kind in columns:
        if csv_column not in row:
            # Absent column: write null rather than omitting the key, so a
            # re-ingest of the same date clears a value that used to be present.
            mapped[db_column] = None
            continue
        mapped[db_column] = coerce(row[csv_column], kind, csv_column, report)
    return mapped


def resolve_run_date(df: pd.DataFrame, csv_path: Path, override: str | None) -> str:
    """Determine the run date, preferring evidence inside the file.

    The filename is the last resort: a replayed or renamed export would then
    claim the wrong trading date and corrupt the movers view, which diffs
    strictly by date.
    """
    if override:
        return coerce_date(override) or override

    for column in ("Price_Bar_As_Of", "Analysis_As_Of"):
        if column in df.columns:
            values = df[column].dropna()
            if not values.empty:
                resolved = coerce_date(values.iloc[0])
                if resolved:
                    return resolved

    match = re.search(r"(\d{4})(\d{2})(\d{2})", csv_path.name)
    if match:
        return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"

    raise ValueError(
        f"Cannot determine run date for {csv_path.name}: no Price_Bar_As_Of, "
        "no Analysis_As_Of, and no YYYYMMDD in the filename. Pass --run-date."
    )


def build_run_row(
    df: pd.DataFrame,
    run_date: str,
    manifest: dict[str, Any] | None,
) -> dict[str, Any]:
    def first(column: str) -> Any:
        if column not in df.columns:
            return None
        values = df[column].dropna()
        return values.iloc[0] if not values.empty else None

    ratings = (
        df["Rating"].astype(str).str.strip().str.upper().value_counts()
        if "Rating" in df.columns
        else pd.Series(dtype=int)
    )

    generated_at = coerce_timestamp(first("Analysis_As_Of"))
    if not generated_at and manifest:
        generated_at = coerce_timestamp(manifest.get("generated_at_utc"))

    run: dict[str, Any] = {
        "run_date": run_date,
        "generated_at_utc": generated_at or datetime.now(timezone.utc).isoformat(),
        "model_version": coerce_text(first("Model_Version")),
        "recommendation_policy_version": coerce_text(
            first("Recommendation_Policy_Version")
        ),
        "output_schema_version": coerce_text(first("Output_Schema_Version")),
        "model_validation_status": coerce_text(first("Model_Validation_Status")),
        "config_sha256": coerce_text(first("Model_Config_SHA256")),
        "git_sha": coerce_text(first("Run_Git_SHA")),
        "git_dirty": coerce_bool(first("Run_Git_Dirty")),
        "market_calendar_version": coerce_text(first("Run_Market_Calendar_Version")),
        "price_bar_as_of": coerce_date(first("Price_Bar_As_Of")),
        "analysis_as_of": coerce_timestamp(first("Analysis_As_Of")),
        "row_count": int(len(df)),
        "universe_selected_count": coerce_int(first("Run_Universe_Selected_Count")),
        "technical_requested_count": coerce_int(first("Run_Technical_Requested_Count")),
        "technical_collected_count": coerce_int(first("Run_Technical_Collected_Count")),
        "technical_failed_count": coerce_int(first("Run_Technical_Failed_Count")),
        "fundamental_missing_count": coerce_int(first("Run_Fundamental_Missing_Count")),
        "manifest": manifest,
    }
    for rating, field in RATING_COUNT_FIELDS.items():
        run[field] = int(ratings.get(rating, 0))
    return run


def publish(
    csv_path: Path,
    manifest_path: Path | None = None,
    run_date_override: str | None = None,
    keep_runs: int = 2,
    chunk_size: int = 200,
    dry_run: bool = False,
) -> dict[str, Any]:
    df = pd.read_csv(csv_path, low_memory=False)
    if "Symbol" not in df.columns:
        raise ValueError(f"{csv_path.name} has no Symbol column; not a screener export")

    manifest: dict[str, Any] | None = None
    if manifest_path is None:
        candidate = csv_path.with_suffix(".manifest.json")
        manifest_path = candidate if candidate.exists() else None
    if manifest_path and manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    run_date = resolve_run_date(df, csv_path, run_date_override)
    run_row = build_run_row(df, run_date, manifest)

    report = CoercionReport()
    records = df.to_dict(orient="records")

    snapshot_rows: list[dict[str, Any]] = []
    history_rows: list[dict[str, Any]] = []
    seen_symbols: set[str] = set()
    duplicate_symbols: list[str] = []

    for record in records:
        symbol = coerce_text(record.get("Symbol"))
        if not symbol:
            continue
        if symbol in seen_symbols:
            # The primary key would silently collapse these. Report instead:
            # a duplicated symbol means the universe build produced two rows
            # for one company, which is a data bug worth seeing.
            duplicate_symbols.append(symbol)
            continue
        seen_symbols.add(symbol)

        snapshot = map_row(record, SNAPSHOT_COLUMNS, report)
        snapshot["run_date"] = run_date
        snapshot["payload"] = build_payload(record)
        snapshot_rows.append(snapshot)

        history = map_row(record, HISTORY_COLUMNS, report)
        history["observed_on"] = run_date
        history_rows.append(history)

    summary: dict[str, Any] = {
        "csv": str(csv_path),
        "run_date": run_date,
        "rows": len(snapshot_rows),
        "duplicate_symbols": duplicate_symbols,
        "coercion": report.summary(),
        "mapped_columns": len(SNAPSHOT_COLUMNS),
        "missing_columns": sorted(
            csv_column
            for _, csv_column, _ in SNAPSHOT_COLUMNS
            if csv_column not in df.columns
        ),
        "payload_columns": len(df.columns),
        "dry_run": dry_run,
    }

    if dry_run:
        return summary

    repository = DashboardRepository.from_environment()
    repository.upsert_run(run_row)
    written = repository.replace_snapshot_rows(run_date, snapshot_rows, chunk_size)
    repository.delete_stale_snapshot_rows(run_date, seen_symbols)
    history_written = repository.upsert_history_rows(history_rows)
    pruned = repository.prune_snapshots(keep_runs)

    summary.update(
        {
            "snapshot_rows_written": written,
            "history_rows_written": history_written,
            "runs_pruned": pruned,
        }
    )
    return summary


def load_env_file(path: Path) -> int:
    """Load KEY=VALUE lines from a local .env, without adding a dependency.

    GitHub Actions and Railway inject these as real environment variables, so
    this exists only so a local run can be driven from the gitignored .env the
    repository already documents -- rather than requiring the operator to export
    a service-role key by hand each session.

    Existing environment variables always win, so this can never silently
    override a value the CI runner set.
    """
    if not path.exists():
        return 0

    loaded = 0
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
            loaded += 1
    return loaded


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", required=True, type=Path, help="Screener CSV export")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="Run manifest JSON (defaults to <csv>.manifest.json when present)",
    )
    parser.add_argument(
        "--run-date",
        default=None,
        help="Override the resolved run date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--keep-runs",
        type=int,
        default=2,
        help="Full snapshots to retain after loading (default: 2)",
    )
    parser.add_argument("--chunk-size", type=int, default=200)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse, map, and report without contacting Supabase",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=Path(".env"),
        help="Local KEY=VALUE file for Supabase credentials (default: .env)",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    loaded = load_env_file(args.env_file)
    if loaded:
        logger.info("Loaded %d value(s) from %s", loaded, args.env_file)

    if not args.csv.exists():
        logger.error("CSV not found: %s", args.csv)
        return 2

    try:
        summary = publish(
            csv_path=args.csv,
            manifest_path=args.manifest,
            run_date_override=args.run_date,
            keep_runs=args.keep_runs,
            chunk_size=args.chunk_size,
            dry_run=args.dry_run,
        )
    except Exception as exc:  # noqa: BLE001 - surfaced as a job failure
        logger.error("Publish failed: %s", exc)
        return 1

    logger.info("Publish summary: %s", json.dumps(summary, indent=2, default=str))
    if summary["missing_columns"]:
        logger.warning(
            "%d mapped column(s) absent from this CSV (written as null): %s",
            len(summary["missing_columns"]),
            ", ".join(summary["missing_columns"]),
        )
    if summary["duplicate_symbols"]:
        logger.warning(
            "%d duplicate symbol(s) skipped: %s",
            len(summary["duplicate_symbols"]),
            ", ".join(summary["duplicate_symbols"][:10]),
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
