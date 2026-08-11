"""Canonical, secret-free run manifests for reproducible model validation."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


MANIFEST_SCHEMA_VERSION = 1

# Explicit allow-list: adding a new score, data, ranking, or evaluation setting
# should be an intentional manifest change. Credentials and notification targets
# must never be added here.
DEFAULT_REPRODUCIBILITY_CONFIG_KEYS = (
    "MODEL_VERSION",
    "RECOMMENDATION_POLICY_VERSION",
    "OUTPUT_SCHEMA_VERSION",
    "MODEL_VALIDATION_STATUS",
    "SCAN_ALL_NSE",
    "CUSTOM_WATCHLIST",
    "TOP_STOCKS_COUNT",
    "NEWS_SENTIMENT_TOP_N",
    "PRICE_CACHE_MAX_AGE_HOURS",
    "FUND_CACHE_MAX_AGE_DAYS",
    "ANALYSIS_TIMEZONE",
    "MARKET_BAR_COMPLETE_AFTER_IST",
    "NSE_MARKET_HOLIDAYS",
    "NSE_MARKET_CALENDAR_VERSION",
    "ALLOW_PROVISIONAL_MARKET_BARS",
    "LIQUIDITY_FILTER_ENABLED",
    "PREFILTER_RESEARCH_UNIVERSE_BY_LIQUIDITY",
    "MIN_PRICE_INR",
    "MIN_AVG_TURNOVER_INR",
    "MIN_MEDIAN_TURNOVER_20D_INR",
    "NSE_LIQUIDITY_ENABLED",
    "NSE_LIQUIDITY_CACHE_MAX_AGE_DAYS",
    "PORTFOLIO_TARGET_POSITION_INR",
    "LIQUIDITY_POSITION_PARTICIPATION_RATE",
    "LIQUIDITY_MIN_TRADING_FREQUENCY",
    "LIQUIDITY_MAX_TURNOVER_TOP5_SHARE",
    "FUNDAMENTAL_MIN_COVERAGE_FOR_BUY",
    "FUNDAMENTAL_MIN_COVERAGE_FOR_STRONG_BUY",
    "TECHNICAL_MIN_COVERAGE_FOR_BUY",
    "TECHNICAL_MIN_COVERAGE_FOR_STRONG_BUY",
    "REQUIRE_UPTREND_FOR_BUY",
    "BUY_MIN_MA50_SLOPE",
    "BUY_MIN_3M_RETURN",
    "SPECIALIZED_FUNDAMENTAL_SECTORS",
    "STRONG_BUY_MIN_GROWTH",
    "STRONG_BUY_MIN_TECH_SCORE",
    "STRONG_BUY_MIN_ADX",
    "BORDERLINE_SCORE_BAND",
    "BORDERLINE_PRICE_MA50_PCT_BAND",
    "BORDERLINE_MA50_SLOPE_PCT_BAND",
    "BORDERLINE_3M_RETURN_PCT_BAND",
    "BORDERLINE_GROWTH_RATIO_BAND",
    "BORDERLINE_ADX_BAND",
    "BORDERLINE_DI_BAND",
    "BORDERLINE_TECH_SCORE_BAND",
    "BORDERLINE_COVERAGE_BAND",
    "SECTOR_RELATIVE_FUND_SCORING_ENABLED",
    "MIN_SECTOR_PEERS",
    "SECTOR_RELATIVE_FUND_WEIGHT",
    "REVERSE_DCF_ENABLED",
    "REVERSE_DCF_FORECAST_YEARS",
    "REVERSE_DCF_DISCOUNT_RATE",
    "REVERSE_DCF_TERMINAL_GROWTH",
    "REVERSE_DCF_FCF_MARGIN_FALLBACK",
    "REVERSE_DCF_MIN_GROWTH",
    "REVERSE_DCF_MAX_GROWTH",
    "REVERSE_DCF_MIN_TERMINAL_GROWTH",
    "REVERSE_DCF_MAX_TERMINAL_GROWTH",
    "REVERSE_DCF_MIN_VALID_FCF_YIELD",
    "REVERSE_DCF_RANKING_WEIGHT",
    "CAP_STRONG_BUY_ON_REPORTED_NEGATIVE_FCF",
    "REVERSE_DCF_SCORE_LOG_SCALE",
    "REVERSE_DCF_NEUTRAL_LOG_BAND",
    "TRANSCRIPT_SENTIMENT_ENABLED",
    "TRANSCRIPT_SENTIMENT_WEIGHT",
    "REQUIRE_TRANSCRIPT_FOR_STRONG_BUY",
    "TRANSCRIPT_MAX_EVIDENCE_AGE_DAYS",
    "TRANSCRIPT_MIN_PRIORITY_SCORE",
    "TRANSCRIPT_MAX_PRIORITY_RISK",
    "TRANSCRIPT_RECENCY_HALF_LIFE_DAYS",
    "TRANSCRIPT_CYCLE_TAPER_DAYS",
    "TRANSCRIPT_FAIL_ON_ERROR",
    "RED_FLAG_ENRICHMENT_ENABLED",
    "BACKTEST_HORIZON_DAYS",
    "BACKTEST_WRITES_ENABLED",
    "RUN_MANIFEST_ENABLED",
)

PACKAGE_NAMES = (
    "numpy",
    "pandas",
    "requests",
    "yfinance",
    "reportlab",
    "transformers",
    "torch",
)


def _canonicalize(value: Any) -> Any:
    """Convert common Python/config values into stable JSON-safe values."""
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return str(value)
        return value
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, Mapping):
        return {
            str(key): _canonicalize(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (set, frozenset)):
        normalized = [_canonicalize(item) for item in value]
        return sorted(normalized, key=lambda item: canonical_json(item))
    if isinstance(value, (list, tuple)):
        return [_canonicalize(item) for item in value]
    return str(value)


def canonical_json(value: Any) -> str:
    return json.dumps(
        _canonicalize(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def effective_non_secret_config(
    config: Any,
    keys: Iterable[str] = DEFAULT_REPRODUCIBILITY_CONFIG_KEYS,
) -> dict[str, Any]:
    """Return the effective allow-listed model configuration.

    Supabase credential *presence* affects transcript availability, so it is
    represented as a boolean without exposing either the URL or service key.
    """
    values = {
        key: _canonicalize(getattr(config, key))
        for key in sorted(set(keys))
        if hasattr(config, key)
    }
    values["SUPABASE_CONFIGURED"] = bool(
        getattr(config, "SUPABASE_URL", "")
        and getattr(config, "SUPABASE_SERVICE_ROLE_KEY", "")
    )
    return dict(sorted(values.items()))


def canonical_config_hash(
    config: Any,
    keys: Iterable[str] = DEFAULT_REPRODUCIBILITY_CONFIG_KEYS,
) -> str:
    return sha256_bytes(canonical_json(effective_non_secret_config(config, keys)).encode("utf-8"))


def _git_sha(cwd: str | Path | None = None) -> str:
    explicit = os.getenv("GITHUB_SHA", "").strip()
    if explicit:
        return explicit
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(cwd) if cwd else None,
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _git_worktree_provenance(cwd: str | Path | None = None) -> dict[str, Any]:
    """Report whether a local SHA is modified without embedding the diff."""

    try:
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=normal"],
            cwd=str(cwd) if cwd else None,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        diff = subprocess.run(
            ["git", "diff", "--binary", "HEAD"],
            cwd=str(cwd) if cwd else None,
            check=True,
            capture_output=True,
        ).stdout
        normalized_status = "\n".join(
            sorted(line.rstrip() for line in status.splitlines() if line.strip())
        )
        return {
            "dirty": bool(normalized_status),
            "status_sha256": (
                sha256_bytes(normalized_status.encode("utf-8"))
                if normalized_status
                else None
            ),
            "tracked_diff_sha256": sha256_bytes(diff) if diff else None,
        }
    except (OSError, subprocess.SubprocessError):
        return {
            "dirty": None,
            "status_sha256": None,
            "tracked_diff_sha256": None,
        }


def _package_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for name in PACKAGE_NAMES:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = "not-installed"
    return versions


def build_run_manifest(
    config: Any,
    *,
    input_files: Iterable[str | Path] = (),
    generated_at: datetime | None = None,
    git_sha: str | None = None,
    cwd: str | Path | None = None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    effective_config = effective_non_secret_config(config)
    inputs = []
    for file_path in sorted((Path(path) for path in input_files), key=lambda path: path.as_posix()):
        inputs.append({
            "path": file_path.as_posix(),
            "sha256": sha256_file(file_path),
            "size_bytes": file_path.stat().st_size,
        })

    timestamp = generated_at or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    timestamp = timestamp.astimezone(timezone.utc)

    git_worktree = _git_worktree_provenance(cwd)
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "generated_at_utc": timestamp.isoformat().replace("+00:00", "Z"),
        "git_sha": git_sha or _git_sha(cwd),
        "git_dirty": git_worktree["dirty"],
        "git_status_sha256": git_worktree["status_sha256"],
        "git_tracked_diff_sha256": git_worktree["tracked_diff_sha256"],
        "model_version": str(getattr(config, "MODEL_VERSION", "unknown")),
        "config_sha256": sha256_bytes(canonical_json(effective_config).encode("utf-8")),
        "effective_non_secret_config": effective_config,
        "inputs": inputs,
        "runtime": {
            "python": platform.python_version(),
            "python_implementation": platform.python_implementation(),
            "platform": platform.platform(),
            "byteorder": sys.byteorder,
            "packages": _package_versions(),
        },
        "extra": _canonicalize(extra or {}),
    }
    return _canonicalize(manifest)


def write_run_manifest(path: str | Path, manifest: Mapping[str, Any]) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(_canonicalize(manifest), ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return destination
