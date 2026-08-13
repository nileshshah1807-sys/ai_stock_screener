"""Deterministic baseline-versus-candidate screener output comparison."""

from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


RATING_ORDER = ("STRONG BUY", "BUY", "HOLD", "REDUCE", "SELL", "UNKNOWN")
SCORE_COLUMNS = (
    "Fundamental_Score",
    "Technical_Score",
    "Combined_Score",
    "Core_Score",
    "DCF_Valuation_Score",
    "DCF_Evidence_Score",
    "DCF_Evidence_Contribution",
    "Score_After_DCF",
    "Transcript_Effective_Score",
    "Transcript_Evidence_Contribution",
    "Evidence_Score",
    "Decision_Score_Ceiling",
    "Decision_Score",
    "Final_Score",
)
GATE_COLUMNS = (
    "Evidence_Rating",
    "Decision_Rating",
    "Rating_Capped",
    "Rating_Cap_Reason",
    "Decision_Cap_Applied",
    "Decision_Cap_Reason",
    "Buy_Eligible",
    "Buy_Gate_Reason",
    "Buy_Gate_Failures",
    "Strong_Buy_Eligible",
    "Strong_Buy_Gate_Reason",
    "Strong_Buy_Gate_Failures",
    "Gate_Failures",
    "Trend_Confirmed",
    "DCF_Status",
    "DCF_Blend_Eligible",
    "DCF_Blend_Applied",
    "Transcript_Status",
    "Transcript_Blend_Eligible",
    "Transcript_Blend_Applied",
    "Transcript_Technical_Gate",
    "Transcript_Quality_Gate",
    "Portfolio_Actionable",
)

_TRUE_VALUES = {"1", "1.0", "true", "t", "yes", "y", "on"}
_FALSE_VALUES = {"0", "0.0", "false", "f", "no", "n", "off"}


def _validate_frame(frame: pd.DataFrame, label: str) -> pd.DataFrame:
    if "Symbol" not in frame:
        raise ValueError(f"{label} CSV has no Symbol column")
    source = frame.copy()
    source["Symbol"] = source["Symbol"].astype(str).str.strip().str.upper()
    if source["Symbol"].eq("").any():
        raise ValueError(f"{label} CSV contains a blank Symbol")
    duplicates = source.loc[source["Symbol"].duplicated(), "Symbol"].tolist()
    if duplicates:
        raise ValueError(f"{label} CSV contains duplicate symbols: {duplicates[:5]}")
    return source


def _select_rank_column(
    baseline: pd.DataFrame,
    candidate: pd.DataFrame,
    requested: str | None,
) -> str:
    if requested and requested.lower() != "auto":
        if requested not in baseline or requested not in candidate:
            raise ValueError(f"rank column {requested!r} is not present in both CSVs")
        return requested
    for column in ("Rank", "Actionable_Rank", "Investment_Rank"):
        if column in baseline and column in candidate:
            return column
    raise ValueError("no common Rank, Actionable_Rank, or Investment_Rank column")


def _ranked(frame: pd.DataFrame, rank_column: str) -> pd.DataFrame:
    source = frame.copy()
    source[rank_column] = pd.to_numeric(source[rank_column], errors="coerce")
    if source[rank_column].isna().any():
        raise ValueError(f"{rank_column} contains non-numeric or missing values")
    return source.sort_values([rank_column, "Symbol"], kind="mergesort").reset_index(drop=True)


def _number(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def _boolean(value: Any, *, column: str) -> bool:
    """Parse a CSV boolean without Python's truthy-string footgun."""
    if value is None or pd.isna(value):
        raise ValueError(f"candidate {column} contains a missing value")
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)) and value in (0, 1):
        return bool(value)
    if isinstance(value, (float, np.floating)) and math.isfinite(float(value)):
        if float(value) in (0.0, 1.0):
            return bool(value)
    text = str(value).strip().lower()
    if text in _TRUE_VALUES:
        return True
    if text in _FALSE_VALUES:
        return False
    raise ValueError(f"candidate {column} contains invalid boolean value {value!r}")


def validate_factor_statement_coverage(
    candidate: pd.DataFrame,
    min_coverage: float | None,
) -> float | None:
    """Fail closed when a factor candidate lacks representative statements.

    ``Statement_Universe_Coverage`` is run-level metadata repeated on every
    output row. Validating the complete column prevents a corrupt or
    concatenated CSV from passing merely because its first row looks healthy.
    The reported ratio is also reconciled with the per-row availability flags.

    Returns the validated coverage for a factor run, otherwise ``None``.
    A ``None`` threshold disables the guard for backward compatibility.
    """
    if min_coverage is None:
        return None
    threshold = _number(min_coverage)
    if threshold is None or not 0.0 <= threshold <= 1.0:
        raise ValueError("min_statement_coverage must be between 0 and 1")

    # Legacy/non-factor exports do not necessarily carry this column. When it
    # is present, every row must agree about which model produced the run.
    if "Factor_Model_Applied" not in candidate:
        return None
    if candidate.empty:
        raise ValueError("candidate CSV is empty; factor model status is unavailable")
    factor_flags = [
        _boolean(value, column="Factor_Model_Applied")
        for value in candidate["Factor_Model_Applied"]
    ]
    if len(set(factor_flags)) != 1:
        raise ValueError("candidate Factor_Model_Applied is inconsistent across rows")
    if not factor_flags[0]:
        return None

    coverage_column = "Statement_Universe_Coverage"
    if coverage_column not in candidate:
        raise ValueError(
            "factor candidate CSV has no Statement_Universe_Coverage column"
        )
    coverage = pd.to_numeric(candidate[coverage_column], errors="coerce")
    if coverage.isna().any() or not np.isfinite(coverage.to_numpy(dtype=float)).all():
        raise ValueError(
            "candidate Statement_Universe_Coverage contains non-numeric or missing values"
        )
    if ((coverage < 0.0) | (coverage > 1.0)).any():
        raise ValueError("candidate Statement_Universe_Coverage must be between 0 and 1")
    reported = float(coverage.iloc[0])
    if not np.isclose(
        coverage.to_numpy(dtype=float), reported, rtol=0.0, atol=1e-12
    ).all():
        raise ValueError(
            "candidate Statement_Universe_Coverage is inconsistent across rows"
        )

    availability_column = "Statement_Record_Available"
    if availability_column not in candidate:
        raise ValueError(f"factor candidate CSV has no {availability_column} column")
    available = [
        _boolean(value, column=availability_column)
        for value in candidate[availability_column]
    ]
    actual = sum(available) / len(available)
    # The collector publishes this ratio rounded to four decimal places.
    if not math.isclose(reported, actual, rel_tol=0.0, abs_tol=0.000050001):
        raise ValueError(
            "candidate Statement_Universe_Coverage does not match "
            f"Statement_Record_Available rows ({reported:.4f} reported, "
            f"{actual:.4f} actual)"
        )
    # Enforce the floor against the exact row count, not the four-decimal
    # published value, so rounding up cannot make a just-under-threshold run
    # pass the guard.
    if actual < threshold:
        raise ValueError(
            "factor candidate statement coverage is below the required minimum "
            f"({actual:.2%} < {threshold:.2%})"
        )
    return actual


def _delta(candidate: Any, baseline: Any) -> float | None:
    candidate_number = _number(candidate)
    baseline_number = _number(baseline)
    if candidate_number is None or baseline_number is None:
        return None
    return round(candidate_number - baseline_number, 6)


def _value(row: pd.Series | None, column: str) -> Any:
    if row is None or column not in row:
        return None
    value = row[column]
    if pd.isna(value):
        return None
    if isinstance(value, np.generic):
        return value.item()
    return value


def _rating(value: Any) -> str:
    text = str(value).strip().upper() if value is not None and not pd.isna(value) else ""
    return text if text in RATING_ORDER[:-1] else "UNKNOWN"


def _spearman(baseline_ranks: Iterable[float], candidate_ranks: Iterable[float]) -> float | None:
    baseline = pd.Series(list(baseline_ranks), dtype=float).rank(method="average").to_numpy()
    candidate = pd.Series(list(candidate_ranks), dtype=float).rank(method="average").to_numpy()
    if len(baseline) < 2 or np.std(baseline) == 0 or np.std(candidate) == 0:
        return None
    return round(float(np.corrcoef(baseline, candidate)[0, 1]), 6)


def _weighted_effect(
    baseline_row: pd.Series | None,
    candidate_row: pd.Series | None,
    score_column: str,
    weight_column: str,
    default_weight: float,
) -> float | None:
    if baseline_row is None or candidate_row is None:
        return None
    baseline_score = _number(_value(baseline_row, score_column))
    candidate_score = _number(_value(candidate_row, score_column))
    if baseline_score is None or candidate_score is None:
        return None
    baseline_weight = _number(_value(baseline_row, weight_column))
    candidate_weight = _number(_value(candidate_row, weight_column))
    baseline_weight = default_weight if baseline_weight is None else baseline_weight
    candidate_weight = default_weight if candidate_weight is None else candidate_weight
    return round(candidate_score * candidate_weight - baseline_score * baseline_weight, 6)


def _reason(parts: list[str]) -> str:
    return "; ".join(parts) if parts else "No scored or gated change"


def compare_frames(
    baseline_frame: pd.DataFrame,
    candidate_frame: pd.DataFrame,
    *,
    top_n: int = 20,
    rank_column: str | None = "auto",
    min_statement_coverage: float | None = None,
) -> tuple[dict[str, Any], pd.DataFrame]:
    if top_n <= 0:
        raise ValueError("top_n must be positive")
    baseline = _validate_frame(baseline_frame, "baseline")
    candidate = _validate_frame(candidate_frame, "candidate")
    statement_coverage = validate_factor_statement_coverage(
        candidate, min_statement_coverage
    )
    selected_rank = _select_rank_column(baseline, candidate, rank_column)
    baseline = _ranked(baseline, selected_rank)
    candidate = _ranked(candidate, selected_rank)

    baseline_by_symbol = baseline.set_index("Symbol", drop=False)
    candidate_by_symbol = candidate.set_index("Symbol", drop=False)
    baseline_symbols = set(baseline_by_symbol.index)
    candidate_symbols = set(candidate_by_symbol.index)
    common_symbols = baseline_symbols & candidate_symbols

    baseline_top = baseline.head(top_n)["Symbol"].tolist()
    candidate_top = candidate.head(top_n)["Symbol"].tolist()
    baseline_top_set = set(baseline_top)
    candidate_top_set = set(candidate_top)
    top_union = baseline_top_set | candidate_top_set
    top_overlap = baseline_top_set & candidate_top_set
    entrants = [symbol for symbol in candidate_top if symbol not in baseline_top_set]
    exits = [symbol for symbol in baseline_top if symbol not in candidate_top_set]

    common_order = sorted(common_symbols)
    baseline_common_ranks = [float(baseline_by_symbol.at[symbol, selected_rank]) for symbol in common_order]
    candidate_common_ranks = [float(candidate_by_symbol.at[symbol, selected_rank]) for symbol in common_order]

    transition_counts: dict[tuple[str, str], int] = {}
    for symbol in common_order:
        transition = (
            _rating(baseline_by_symbol.at[symbol, "Rating"] if "Rating" in baseline else None),
            _rating(candidate_by_symbol.at[symbol, "Rating"] if "Rating" in candidate else None),
        )
        transition_counts[transition] = transition_counts.get(transition, 0) + 1
    rating_transitions = [
        {"baseline_rating": old, "candidate_rating": new, "count": transition_counts.get((old, new), 0)}
        for old in RATING_ORDER
        for new in RATING_ORDER
        if transition_counts.get((old, new), 0)
    ]

    records: list[dict[str, Any]] = []
    all_symbols = baseline_symbols | candidate_symbols
    for symbol in all_symbols:
        baseline_row = baseline_by_symbol.loc[symbol] if symbol in baseline_symbols else None
        candidate_row = candidate_by_symbol.loc[symbol] if symbol in candidate_symbols else None
        baseline_rank = _number(_value(baseline_row, selected_rank))
        candidate_rank = _number(_value(candidate_row, selected_rank))
        rank_shift = (
            round(candidate_rank - baseline_rank, 6)
            if baseline_rank is not None and candidate_rank is not None
            else None
        )

        record: dict[str, Any] = {
            "Symbol": symbol,
            "Universe_Change": (
                "ADDED" if baseline_row is None else "REMOVED" if candidate_row is None else "COMMON"
            ),
            "Baseline_TopN": symbol in baseline_top_set,
            "Candidate_TopN": symbol in candidate_top_set,
            "Baseline_Rank": baseline_rank,
            "Candidate_Rank": candidate_rank,
            "Rank_Shift": rank_shift,
            "Baseline_Rating": _rating(_value(baseline_row, "Rating")),
            "Candidate_Rating": _rating(_value(candidate_row, "Rating")),
        }
        reasons: list[str] = []
        for column in SCORE_COLUMNS:
            record[f"Baseline_{column}"] = _number(_value(baseline_row, column))
            record[f"Candidate_{column}"] = _number(_value(candidate_row, column))
            change = _delta(_value(candidate_row, column), _value(baseline_row, column))
            record[f"Delta_{column}"] = change
            if change not in (None, 0.0):
                reasons.append(f"{column} {change:+.4f}")

        fundamental_effect = _weighted_effect(
            baseline_row, candidate_row, "Fundamental_Score", "Dynamic_Weight_Fund", 0.70
        )
        technical_effect = _weighted_effect(
            baseline_row, candidate_row, "Technical_Score", "Dynamic_Weight_Tech", 0.30
        )
        combined_delta = record.get("Delta_Combined_Score")
        core_residual = (
            round(combined_delta - fundamental_effect - technical_effect, 6)
            if combined_delta is not None
            and fundamental_effect is not None
            and technical_effect is not None
            else None
        )
        final_delta = record.get("Delta_Final_Score")
        post_core_effect = (
            round(final_delta - combined_delta, 6)
            if final_delta is not None and combined_delta is not None
            else None
        )
        record["Weighted_Fundamental_Effect"] = fundamental_effect
        record["Weighted_Technical_Effect"] = technical_effect
        record["Core_Rounding_Or_Other_Effect"] = core_residual
        record["Post_Core_DCF_Transcript_Effect"] = post_core_effect

        gate_changes: list[str] = []
        for column in GATE_COLUMNS:
            old = _value(baseline_row, column)
            new = _value(candidate_row, column)
            record[f"Baseline_{column}"] = old
            record[f"Candidate_{column}"] = new
            if old != new and not (old is None and new is None):
                gate_changes.append(f"{column}: {old!s} -> {new!s}")
        if record["Baseline_Rating"] != record["Candidate_Rating"]:
            gate_changes.append(
                f"Rating: {record['Baseline_Rating']} -> {record['Candidate_Rating']}"
            )
        reasons.extend(gate_changes)
        if record["Universe_Change"] != "COMMON":
            reasons.append(f"Universe {record['Universe_Change'].lower()}")
        record["Gate_Changes"] = " | ".join(gate_changes)
        record["Attribution"] = _reason(reasons)
        records.append(record)

    attribution = pd.DataFrame(records)
    attribution["_candidate_sort"] = pd.to_numeric(
        attribution["Candidate_Rank"], errors="coerce"
    ).fillna(float("inf"))
    attribution["_baseline_sort"] = pd.to_numeric(
        attribution["Baseline_Rank"], errors="coerce"
    ).fillna(float("inf"))
    attribution = attribution.sort_values(
        ["_candidate_sort", "_baseline_sort", "Symbol"], kind="mergesort"
    ).drop(columns=["_candidate_sort", "_baseline_sort"]).reset_index(drop=True)

    common_attribution = attribution[attribution["Universe_Change"].eq("COMMON")].copy()
    common_attribution["Abs_Rank_Shift"] = pd.to_numeric(
        common_attribution["Rank_Shift"], errors="coerce"
    ).abs()
    largest_shifts = (
        common_attribution.sort_values(
            ["Abs_Rank_Shift", "Symbol"], ascending=[False, True], kind="mergesort"
        )
        .head(20)[["Symbol", "Baseline_Rank", "Candidate_Rank", "Rank_Shift"]]
        .to_dict("records")
    )
    mean_abs_shift = common_attribution["Abs_Rank_Shift"].mean()
    max_abs_shift = common_attribution["Abs_Rank_Shift"].max()

    summary: dict[str, Any] = {
        "rank_column": selected_rank,
        "rank_shift_definition": "candidate_rank_minus_baseline_rank",
        "top_n": top_n,
        "baseline_rows": len(baseline),
        "candidate_rows": len(candidate),
        "common_symbols": len(common_symbols),
        "added_symbols": sorted(candidate_symbols - baseline_symbols),
        "removed_symbols": sorted(baseline_symbols - candidate_symbols),
        "baseline_top": baseline_top,
        "candidate_top": candidate_top,
        "top_overlap": [symbol for symbol in candidate_top if symbol in top_overlap],
        "top_overlap_count": len(top_overlap),
        "entrants": entrants,
        "exits": exits,
        "top_jaccard": round(len(top_overlap) / len(top_union), 6) if top_union else 1.0,
        "spearman_common_ranks": _spearman(baseline_common_ranks, candidate_common_ranks),
        "mean_absolute_rank_shift": (
            round(float(mean_abs_shift), 6) if pd.notna(mean_abs_shift) else None
        ),
        "max_absolute_rank_shift": (
            round(float(max_abs_shift), 6) if pd.notna(max_abs_shift) else None
        ),
        "largest_rank_shifts": largest_shifts,
        "rating_transitions": rating_transitions,
    }
    if statement_coverage is not None:
        summary["candidate_statement_coverage"] = statement_coverage
        summary["minimum_statement_coverage"] = float(min_statement_coverage)
    return summary, attribution


def compare_csv_files(
    baseline_path: str | Path,
    candidate_path: str | Path,
    *,
    top_n: int = 20,
    rank_column: str | None = "auto",
    min_statement_coverage: float | None = None,
) -> tuple[dict[str, Any], pd.DataFrame]:
    baseline_path = Path(baseline_path)
    candidate_path = Path(candidate_path)
    baseline = pd.read_csv(baseline_path)
    candidate = pd.read_csv(candidate_path)
    summary, attribution = compare_frames(
        baseline,
        candidate,
        top_n=top_n,
        rank_column=rank_column,
        min_statement_coverage=min_statement_coverage,
    )
    summary["baseline_csv_sha256"] = _file_sha256(baseline_path)
    summary["candidate_csv_sha256"] = _file_sha256(candidate_path)
    return summary, attribution


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
