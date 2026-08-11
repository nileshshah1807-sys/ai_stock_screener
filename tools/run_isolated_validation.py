#!/usr/bin/env python3
"""Run the live candidate collector in an isolated, notification-free sandbox."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))


ISOLATED_LOG_FILENAME = "stock_screener_advanced.log"
FALSE_SAFETY_SETTINGS = (
    "EMAIL_ENABLED",
    "WHATSAPP_ENABLED",
    "RED_FLAG_ENRICHMENT_ENABLED",
    "BACKTEST_LOG_ENABLED",
    "BACKTEST_WRITES_ENABLED",
)
EMPTY_SAFETY_SETTINGS = (
    "TWILIO_ACCOUNT_SID",
    "TWILIO_AUTH_TOKEN",
    "TWILIO_WHATSAPP_NUMBER",
    "WHATSAPP_RECEIVER",
    "CALLMEBOT_API_KEY",
    "CALLMEBOT_PHONE",
    "PYWHATKIT_PHONE",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--model-version", required=True)
    parser.add_argument(
        "--custom-watchlist",
        help="Comma-separated symbols. When omitted, honor SCAN_ALL_NSE from the environment.",
    )
    return parser.parse_args()


class _DisabledBacktestEngine:
    """API-compatible no-op used only by this isolated validation entry point."""

    def __init__(self, output_dir, model_version=None):
        self.output_dir = Path(output_dir)
        self.model_version = str(model_version or "validation")

    def log_run(self, date_str, scored_df):
        return None

    def analyze_performance(self):
        return None


def _environment_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _watchlist(value: str | None) -> list[str]:
    return [
        symbol.strip().upper()
        for symbol in str(value or "").split(",")
        if symbol.strip()
    ]


def _validate_output_dir(path: Path) -> Path:
    """Resolve and reject repository-root or production-tree destinations."""

    output_dir = path.resolve()
    repository_root = REPOSITORY_ROOT.resolve()
    production_output = (repository_root / "reports_advanced").resolve()
    if output_dir == repository_root:
        raise ValueError(
            "isolated validation output cannot be the repository root"
        )
    if output_dir.is_relative_to(production_output):
        raise ValueError(
            "isolated validation output cannot be inside the production output tree"
        )
    return output_dir


def _set_isolated_environment(
    *,
    output_dir: Path,
    model_version: str,
    scan_all_nse: bool,
    custom_watchlist: list[str],
) -> None:
    """Set process safeguards both before and after application import."""

    os.environ["OUTPUT_DIR"] = str(output_dir)
    os.environ["YFINANCE_CACHE_DIR"] = str(output_dir / "yfinance_cache")
    os.environ["MODEL_VERSION"] = model_version
    for setting in FALSE_SAFETY_SETTINGS:
        os.environ[setting] = "False"
    os.environ["RUN_MANIFEST_ENABLED"] = "True"
    for setting in EMPTY_SAFETY_SETTINGS:
        os.environ[setting] = ""
    # Transcript sentiment is read from Supabase so the candidate ranking is
    # comparable with production. Blanking the credentials instead made every
    # row "Not configured" and silently removed transcript evidence from the
    # comparison. Writes stay blocked at the transport layer.
    os.environ["SUPABASE_READ_ONLY"] = "True"
    os.environ["SCAN_ALL_NSE"] = "True" if scan_all_nse else "False"
    if custom_watchlist:
        os.environ["CUSTOM_WATCHLIST"] = ",".join(custom_watchlist)


def _reassert_isolated_config(
    config,
    *,
    output_dir: Path,
    model_version: str,
    scan_all_nse: bool,
    custom_watchlist: list[str],
) -> None:
    """Overwrite config_local values that could escape the validation sandbox."""

    config.OUTPUT_DIR = output_dir
    config.YFINANCE_CACHE_DIR = output_dir / "yfinance_cache"
    config.MODEL_VERSION = model_version
    for setting in FALSE_SAFETY_SETTINGS:
        setattr(config, setting, False)
    config.RUN_MANIFEST_ENABLED = True
    for setting in EMPTY_SAFETY_SETTINGS:
        setattr(config, setting, "")
    # Both surfaces matter: enrichers build the client from config, while
    # worker entry points use SupabaseRepository.from_environment().
    config.SUPABASE_READ_ONLY = True
    os.environ["SUPABASE_READ_ONLY"] = "True"
    config.SCAN_ALL_NSE = scan_all_nse
    if custom_watchlist:
        config.CUSTOM_WATCHLIST = list(custom_watchlist)


def _validate_isolated_config(
    config,
    *,
    output_dir: Path,
    model_version: str,
    scan_all_nse: bool,
    custom_watchlist: list[str],
) -> None:
    """Fail closed if application configuration is not exactly isolated."""

    violations: list[str] = []
    try:
        configured_output = Path(config.OUTPUT_DIR).resolve()
    except (AttributeError, OSError, TypeError, ValueError):
        configured_output = None
    if configured_output != output_dir:
        violations.append(f"OUTPUT_DIR={configured_output!s}")

    expected_cache = (output_dir / "yfinance_cache").resolve()
    try:
        configured_cache = Path(config.YFINANCE_CACHE_DIR).resolve()
    except (AttributeError, OSError, TypeError, ValueError):
        configured_cache = None
    if configured_cache != expected_cache:
        violations.append(f"YFINANCE_CACHE_DIR={configured_cache!s}")

    if str(getattr(config, "MODEL_VERSION", "")) != model_version:
        violations.append("MODEL_VERSION")
    for setting in FALSE_SAFETY_SETTINGS:
        if getattr(config, setting, None) is not False:
            violations.append(setting)
    if getattr(config, "RUN_MANIFEST_ENABLED", None) is not True:
        violations.append("RUN_MANIFEST_ENABLED")
    for setting in EMPTY_SAFETY_SETTINGS:
        if getattr(config, setting, None) != "":
            violations.append(setting)
    # Supabase credentials are deliberately present so transcripts load; the
    # read-only flag is what keeps this run from mutating shared state.
    if getattr(config, "SUPABASE_READ_ONLY", None) is not True:
        violations.append("SUPABASE_READ_ONLY")
    if str(os.environ.get("SUPABASE_READ_ONLY", "")).strip().lower() not in {
        "1", "true", "yes", "y",
    }:
        violations.append("SUPABASE_READ_ONLY(env)")
    if getattr(config, "SCAN_ALL_NSE", None) is not scan_all_nse:
        violations.append("SCAN_ALL_NSE")
    if custom_watchlist and list(getattr(config, "CUSTOM_WATCHLIST", [])) != custom_watchlist:
        violations.append("CUSTOM_WATCHLIST")

    if violations:
        raise RuntimeError(
            "isolated validation safety configuration failed: "
            + ", ".join(violations)
        )


def _configure_isolated_logging(output_dir: Path) -> Path:
    """Route every root log handler into the isolated output directory."""

    log_path = (output_dir / ISOLATED_LOG_FILENAME).resolve()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8", errors="replace"),
            logging.StreamHandler(),
        ],
        force=True,
    )
    unsafe_handlers = []
    for handler in logging.getLogger().handlers:
        if not isinstance(handler, logging.FileHandler):
            continue
        handler_path = Path(handler.baseFilename).resolve()
        if handler_path != log_path:
            unsafe_handlers.append(str(handler_path))
    if unsafe_handlers:
        raise RuntimeError(
            "isolated validation installed a file logger outside OUTPUT_DIR: "
            + ", ".join(unsafe_handlers)
        )
    return log_path


def main() -> int:
    args = parse_args()
    output_dir = _validate_output_dir(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.custom_watchlist:
        scan_all_nse = False
        custom_watchlist = _watchlist(args.custom_watchlist)
    else:
        scan_all_nse = _environment_bool("SCAN_ALL_NSE", True)
        custom_watchlist = _watchlist(os.getenv("CUSTOM_WATCHLIST"))
    if not scan_all_nse and not custom_watchlist:
        raise ValueError(
            "isolated validation requires a non-empty custom watchlist when SCAN_ALL_NSE is false"
        )

    # Enforce safeguards before importing Config/app, whose class attributes are
    # populated from the environment at import time.
    _set_isolated_environment(
        output_dir=output_dir,
        model_version=args.model_version,
        scan_all_nse=scan_all_nse,
        custom_watchlist=custom_watchlist,
    )
    # ``app`` configures a relative production log at import time. Installing a
    # root handler first makes that basicConfig call a no-op in this CLI process.
    isolated_log_path = _configure_isolated_logging(output_dir)

    import app
    from validation.reproducibility import build_run_manifest, sha256_file, write_run_manifest

    # config_local.py executes during the import above and may override class
    # attributes after environment parsing. Reassert and validate all isolation
    # invariants on the exact Config class app.run_daily_analysis will use.
    _set_isolated_environment(
        output_dir=output_dir,
        model_version=args.model_version,
        scan_all_nse=scan_all_nse,
        custom_watchlist=custom_watchlist,
    )
    _reassert_isolated_config(
        app.Config,
        output_dir=output_dir,
        model_version=args.model_version,
        scan_all_nse=scan_all_nse,
        custom_watchlist=custom_watchlist,
    )
    _validate_isolated_config(
        app.Config,
        output_dir=output_dir,
        model_version=args.model_version,
        scan_all_nse=scan_all_nse,
        custom_watchlist=custom_watchlist,
    )
    # Purge any handler a local override may have installed during import.
    isolated_log_path = _configure_isolated_logging(output_dir)

    if os.environ.get("BACKTEST_LOG_ENABLED", "").strip().lower() not in {
        "1", "true", "yes", "on"
    }:
        app.BacktestEngine = _DisabledBacktestEngine

    app.run_daily_analysis()
    csv_files = sorted(output_dir.glob("advanced_analysis_*.csv"))
    if not csv_files:
        raise RuntimeError(f"candidate run produced no analysis CSV in {output_dir}")
    candidate_csv = csv_files[-1]
    app_manifest_path = candidate_csv.with_suffix(".manifest.json")
    if app_manifest_path.exists():
        manifest = json.loads(app_manifest_path.read_text(encoding="utf-8"))
    else:
        input_files = [
            path
            for path in (
                output_dir / "price_cache.csv",
                output_dir / "fundamental_cache.csv",
                output_dir / "nse_liquidity_categories.csv",
            )
            if path.exists()
        ]
        manifest = build_run_manifest(
            app.Config,
            input_files=input_files,
            git_sha=os.getenv("GITHUB_SHA") or None,
            cwd=REPOSITORY_ROOT,
        )
        with candidate_csv.open(encoding="utf-8") as candidate_handle:
            candidate_rows = max(0, sum(1 for _ in candidate_handle) - 1)
        manifest["outputs"] = [{
            "path": candidate_csv.name,
            "sha256": sha256_file(candidate_csv),
            "size_bytes": candidate_csv.stat().st_size,
            "rows": candidate_rows,
        }]
    manifest.setdefault("extra", {}).update({
        "mode": "isolated_candidate_validation",
        "candidate_csv": candidate_csv.name,
        "candidate_csv_sha256": sha256_file(candidate_csv),
        "github_run_id": os.getenv("GITHUB_RUN_ID", ""),
        "github_run_attempt": os.getenv("GITHUB_RUN_ATTEMPT", ""),
        "github_ref": os.getenv("GITHUB_REF", ""),
        "isolated_log": isolated_log_path.name,
        "safeguards": {
            "email_enabled": False,
            "red_flag_enrichment_enabled": False,
            "supabase_configured": False,
            "backtest_persistence_enabled": False,
            "production_cache_restored_or_saved": False,
        },
    })
    manifest_path = write_run_manifest(output_dir / "run_manifest.json", manifest)
    print(json.dumps({
        "candidate_csv": str(candidate_csv),
        "manifest": str(manifest_path),
        "config_sha256": manifest["config_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
