#!/usr/bin/env python3
"""Daily stock-screener composition root and backwards-compatible API."""

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from scoring.transcript_enricher import (
    TranscriptSentimentEnricher,
    rank_actionable_recommendations,
)
from red_flags.enricher import RedFlagEnricher
from red_flags.shadow import RedFlagShadowSimulator
from screener.benchmark import BenchmarkProvider
from screener.data_collection import (
    StockDataCollector,
    align_valuation_to_completed_price_bar,
)
from screener.factors import FactorModel
from screener.statements import FinancialStatementCollector
from screener.liquidity import (
    LiquidityQualityEnricher,
    NSELiquidityProvider,
    filter_execution_universe,
)
from screener.market_data import AlternativeData, BacktestEngine, PriceCache, TechnicalEnhancer, fmt_cr, fmt_f, fmt_pct
from screener.reporting import EmailReporter, InteractiveDashboard, WhatsAppReporter
from screener.recommendation import finalize_recommendations
from screener.runtime import Config, IPv4SMTP, IPv4SMTP_SSL, configure_runtime_cache, load_local_config
from screener.scoring import StockScorer, fundamental_model_for_row, score_financial_services, score_fundamentals, score_real_estate, sector_relative_fund_scores, sort_by_recommendation
from screener.valuation import ReverseDCFModel
from validation.reproducibility import (
    build_run_manifest,
    canonical_config_hash,
    sha256_file,
    write_run_manifest,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("stock_screener_advanced.log", encoding="utf-8", errors="replace"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

load_local_config(Config, Path(__file__).with_name("config_local.py"))


def merge_research_universe(tech_df, fund_df):
    """Left-join fundamentals without deleting successfully collected symbols."""

    merged = pd.merge(
        tech_df,
        fund_df,
        on="Symbol",
        how="left",
        validate="one_to_one",
        indicator="_Fundamental_Merge",
    )
    merged["Fundamental_Record_Available"] = merged[
        "_Fundamental_Merge"
    ].eq("both")
    return merged.drop(columns="_Fundamental_Merge")


def run_daily_analysis():
    config = Config()
    analysis_now = datetime.now(
        ZoneInfo(getattr(config, "ANALYSIS_TIMEZONE", "Asia/Kolkata"))
    )
    logger.info("=" * 60)
    logger.info(
        "STARTING ADVANCED STOCK ANALYSIS (model %s)",
        getattr(config, "MODEL_VERSION", "unknown"),
    )
    logger.info("=" * 60)
    configure_runtime_cache(config)
    date_str = analysis_now.strftime("%d-%m-%Y")
    logger.info(f"Analysis date: {date_str}")

    collector = StockDataCollector(config)
    symbols = collector.get_comprehensive_stock_list()
    tech_df = collector.download_stock_data(symbols)
    if tech_df.empty:
        raise RuntimeError("No technical data was collected")

    # One cached bulk read adds the exchange's six-month liquidity group and
    # Rs1 lakh mean impact cost. This is primary execution evidence; OHLCV
    # turnover remains the fallback and supports custom position sizes.
    tech_df = NSELiquidityProvider(config).enrich(tech_df)

    # V4 keeps research conviction independent of execution liquidity. The
    # legacy prefilter remains an explicit emergency/runtime escape hatch, but
    # normal official runs score the full collected universe and add liquidity
    # only as an Actionable_Rank overlay later.
    if (
        config.LIQUIDITY_FILTER_ENABLED
        and config.SCAN_ALL_NSE
        and getattr(config, "PREFILTER_RESEARCH_UNIVERSE_BY_LIQUIDITY", False)
    ):
        before = len(tech_df)
        # Defensive fallback: if Avg_Turnover_INR is missing/NaN for any rows (e.g. a
        # stale cache written before this column existed slipped through), recompute
        # it from Avg_Volume * Current_Price instead of silently dropping every stock.
        if "Avg_Turnover_INR" not in tech_df.columns:
            tech_df["Avg_Turnover_INR"] = np.nan
        fallback_turnover = tech_df["Avg_Volume"] * tech_df["Current_Price"]
        missing_turnover = tech_df["Avg_Turnover_INR"].isna()
        if missing_turnover.any():
            logger.warning(
                f"Avg_Turnover_INR missing for {int(missing_turnover.sum())} row(s) "
                "(stale cache?) - recomputing from Avg_Volume * Current_Price."
            )
            tech_df.loc[missing_turnover, "Avg_Turnover_INR"] = fallback_turnover.loc[missing_turnover]
        if "Median_Turnover_20D_INR" not in tech_df.columns:
            tech_df["Median_Turnover_20D_INR"] = np.nan
        missing_median = tech_df["Median_Turnover_20D_INR"].isna()
        if missing_median.any():
            logger.warning(
                "Median_Turnover_20D_INR missing for %d row(s); using the "
                "legacy turnover measure for this run only.",
                int(missing_median.sum()),
            )
            tech_df.loc[missing_median, "Median_Turnover_20D_INR"] = tech_df.loc[
                missing_median, "Avg_Turnover_INR"
            ]
        nse_category = pd.to_numeric(
            tech_df.get("NSE_Liquidity_Category"), errors="coerce"
        )
        official_liquid = nse_category.eq(1)
        tech_df = filter_execution_universe(tech_df, config)
        logger.info(
            f"Liquidity filter: kept {len(tech_df)}/{before} "
            f"(dropped {before - len(tech_df)} names below Rs{config.MIN_PRICE_INR:.0f}, "
            "in NSE Group II/III, or below the turnover fallback when official "
            f"evidence was unavailable; Group I kept {int(official_liquid.sum())})"
        )
        if tech_df.empty:
            raise RuntimeError("Liquidity filter removed every stock")
    elif config.LIQUIDITY_FILTER_ENABLED and config.SCAN_ALL_NSE:
        logger.info(
            "Research-universe liquidity prefilter disabled; all %d collected "
            "symbols continue to fundamentals and liquidity remains an execution overlay",
            len(tech_df),
        )

    alt_data = AlternativeData.get_fii_dii_snapshot()
    logger.info(f"Alternative data (FII/DII): {alt_data}")

    fund_df = collector.get_fundamental_data(tech_df)
    if fund_df.empty:
        raise RuntimeError("No fundamental data was collected")

    # Preserve the entire successfully collected market universe. A transient
    # fundamental miss is evidence of zero coverage, not permission to delete
    # the symbol before ranking; the policy will cap it below BUY.
    merged_df = merge_research_universe(tech_df, fund_df)
    missing_fundamentals = int((~merged_df["Fundamental_Record_Available"]).sum())
    if missing_fundamentals:
        logger.warning(
            "Fundamental collection unavailable for %d symbol(s); retained with "
            "zero coverage so the decision policy can fail closed",
            missing_fundamentals,
        )
    # Quote metadata can be cached for days while the completed close changes
    # every session. Recompute price-dependent valuation ratios from the same
    # completed close used by every technical indicator whenever the required
    # raw denominator is available, preserving fetched values for audit.
    merged_df = align_valuation_to_completed_price_bar(merged_df)
    logger.info(f"Merged: {len(merged_df)} stocks")
    if merged_df.empty:
        raise RuntimeError("No symbols remain after merging technical and fundamental data")

    # Annual statements supply every input Yahoo's quote metadata cannot: total
    # assets, EBIT, gross profit, cash-flow history and multi-year series. They
    # restate quarterly at most, so a long cache TTL keeps the daily marginal
    # cost near zero. Only the factor model consumes them.
    factor_model_enabled = bool(getattr(config, "FACTOR_MODEL_ENABLED", False))
    if factor_model_enabled and getattr(config, "STATEMENT_COLLECTION_ENABLED", True):
        merged_df = FinancialStatementCollector(config).enrich(merged_df)

    scorer = StockScorer(config)
    scored_df = scorer.score_all_stocks(merged_df)
    if scored_df is None or len(scored_df) == 0:
        raise RuntimeError("Scoring produced no rows")

    if config.REVERSE_DCF_ENABLED:
        scored_df = ReverseDCFModel(config).enrich(scored_df)

    # Fresh, validated transcripts adjust conviction at the configured score
    # weight. Missing transcripts are neutral and availability is not a hidden
    # higher-order ranking tier.
    if config.TRANSCRIPT_SENTIMENT_ENABLED:
        try:
            scored_df = TranscriptSentimentEnricher(
                config, analysis_date=analysis_now.date()
            ).enrich(scored_df)
            available_transcripts = int((scored_df["Transcript_Status"] == "Available").sum())
            logger.info(f"Transcript sentiment available for {available_transcripts} stock(s)")
        except Exception as e:
            if getattr(config, "TRANSCRIPT_FAIL_ON_ERROR", True):
                raise RuntimeError("Transcript sentiment enrichment failed") from e
            logger.warning(f"Transcript sentiment enrichment skipped: {e}")

    # Model 5.0: replace the 70/30 core score with five separable factor blocks.
    # The 4.x scorer above still runs, because the policy needs its coverage,
    # anomaly and specialist-model routing as evidence -- it just no longer
    # produces the number the ranking is built on.
    market_context = {}
    if factor_model_enabled:
        market_context = BenchmarkProvider(config).market_context()
        logger.info(
            "Market regime: %s (%s); benchmark %s",
            market_context.get("Market_Regime"),
            market_context.get("Market_Regime_Reason"),
            market_context.get("Benchmark_Symbol"),
        )
        scored_df = FactorModel(config).score(scored_df, market_context)
        for key, value in market_context.items():
            scored_df[key] = value

    # Execution capacity is evidence the policy needs, not a post-decision
    # decoration: Model 5.0 can require liquidity for a published BUY. It
    # depends only on turnover/NSE columns, so computing it here is safe for
    # both models and leaves Actionable_Rank downstream of the final ordering.
    scored_df = LiquidityQualityEnricher(config).enrich(scored_df)
    actionable_count = int(scored_df["Portfolio_Actionable"].sum())
    logger.info(
        "Portfolio actionability: %s/%s stock(s) fit the configured Rs%0.f target",
        actionable_count,
        len(scored_df),
        config.PORTFOLIO_TARGET_POSITION_INR,
    )

    # Evidence stages never publish ratings. One versioned policy blends all
    # eligible evidence, applies every coverage/trend gate, and creates the
    # score-first research ranks. This prevents a later enrichment (such as
    # DCF) from resurrecting a recommendation that failed an earlier gate.
    scored_df = finalize_recommendations(scored_df, config)

    # Filing-derived governance/risk evidence is intentionally shadow-only.
    # It is precomputed by a separate worker, so this is a single cached lookup.
    if config.RED_FLAG_ENRICHMENT_ENABLED:
        try:
            scored_df = RedFlagEnricher(config).enrich(scored_df)
            scored_df = RedFlagShadowSimulator().simulate(scored_df)
            review_count = int(scored_df["Shadow_Red_Flag_Review_Required"].sum())
            logger.info(
                "Cached red-flag shadow evidence joined; %s stock(s) require evidence review",
                review_count,
            )
        except Exception as e:
            logger.warning(f"Red-flag enrichment skipped: {e}")

    # One final deterministic ordering after every rating gate. Transcript
    # confirmation is only a tie-break because its effect is already in score.
    scored_df = rank_actionable_recommendations(scored_df)
    scored_df["Model_Version"] = config.MODEL_VERSION
    scored_df["Recommendation_Policy_Version"] = config.RECOMMENDATION_POLICY_VERSION
    scored_df["Output_Schema_Version"] = config.OUTPUT_SCHEMA_VERSION
    scored_df["Model_Validation_Status"] = config.MODEL_VALIDATION_STATUS
    scored_df["Model_Config_SHA256"] = canonical_config_hash(config)

    # Freeze the exact research universe and collection losses. Network-driven
    # symbol failures otherwise make two runs with identical code/config look
    # reproducible while ranking different cross-sections.
    collection_diagnostics = dict(collector.collection_diagnostics)
    collection_diagnostics.update(
        {
            "analysis_as_of": analysis_now.isoformat(timespec="seconds"),
            "research_universe_after_optional_prefilter": sorted(
                tech_df["Symbol"].dropna().astype(str).str.upper().tolist()
            ),
            "fundamental_record_missing_after_merge": sorted(
                merged_df.loc[
                    ~merged_df["Fundamental_Record_Available"], "Symbol"
                ]
                .dropna()
                .astype(str)
                .str.upper()
                .tolist()
            ),
            "scored_symbols": sorted(
                scored_df["Symbol"].dropna().astype(str).str.upper().tolist()
            ),
        }
    )
    diagnostics_path = config.OUTPUT_DIR / (
        f"collection_diagnostics_{analysis_now.strftime('%Y%m%d')}.json"
    )
    write_run_manifest(diagnostics_path, collection_diagnostics)
    diagnostics_sha256 = sha256_file(diagnostics_path)
    technical_requested_count = len(
        collection_diagnostics.get("technical_requested_symbols", [])
    )
    technical_collected_count = len(
        collection_diagnostics.get("technical_collected_symbols", [])
    )
    technical_failed_count = len(
        collection_diagnostics.get("technical_failed_symbols", [])
    )
    fundamental_missing_count = len(
        collection_diagnostics.get("fundamental_missing_symbols", [])
    )
    scored_df["Run_Universe_Selected_Count"] = len(
        collection_diagnostics.get("universe_selected_symbols", [])
    )
    scored_df["Run_Technical_Requested_Count"] = technical_requested_count
    scored_df["Run_Technical_Collected_Count"] = technical_collected_count
    scored_df["Run_Technical_Failed_Count"] = technical_failed_count
    scored_df["Run_Fundamental_Missing_Count"] = fundamental_missing_count
    scored_df["Run_Universe_Source_SHA256"] = collection_diagnostics.get(
        "universe_source_sha256"
    )
    scored_df["Run_Collection_Diagnostics_SHA256"] = diagnostics_sha256
    scored_df["Run_Market_Calendar_Version"] = getattr(
        config, "NSE_MARKET_CALENDAR_VERSION", "unconfigured"
    )

    # News sentiment for the top N picks (post-scoring, so it's the *actual* top N)
    n = min(config.NEWS_SENTIMENT_TOP_N, len(scored_df))
    sentiment_map = {}
    for sym in scored_df["Symbol"].head(n):
        sentiment_map[sym] = AlternativeData.get_news_sentiment(sym)["sentiment"]
    scored_df["News_Sentiment"] = scored_df["Symbol"].map(
        lambda s: sentiment_map.get(s, "-")
    )
    logger.info(f"News sentiment fetched for top {len(sentiment_map)} symbols")

    audit_columns = [
        "Rank", "Investment_Rank", "Score_Rank", "Recommendation_Rank",
        "Actionable_Rank", "Symbol", "Rating", "Core_Score",
        "Evidence_Score", "Decision_Score", "Final_Score", "Transcript_Status",
        "NSE_Liquidity_Group", "NSE_Impact_Cost_Pct",
        "Median_Turnover_20D_INR", "Portfolio_Actionable",
        "Demand_Proxy_Status", "Demand_Proxy_Points", "Gate_Failures",
        "Shadow_Red_Flag_Review_Required",
        "Shadow_Red_Flag_Rating_If_Confirmed",
    ]
    audit_columns = [column for column in audit_columns if column in scored_df]
    logger.info(
        "Top-%d decision audit (demand is a scored technical confirmation; "
        "liquidity changes only Actionable_Rank):\n%s",
        min(config.TOP_STOCKS_COUNT, len(scored_df)),
        scored_df[audit_columns].head(config.TOP_STOCKS_COUNT).to_string(index=False),
    )

    input_files = [
        path
        for path in (
            config.OUTPUT_DIR / "price_cache.csv",
            config.OUTPUT_DIR / "fundamental_cache.csv",
            config.OUTPUT_DIR / "nse_liquidity_categories.csv",
        )
        if path.exists()
    ]
    manifest = build_run_manifest(
        config,
        input_files=input_files,
        generated_at=analysis_now.astimezone(timezone.utc),
        cwd=Path(__file__).parent,
        extra={
            "analysis_as_of": analysis_now.isoformat(timespec="seconds"),
            "row_count": len(scored_df),
            "collection_diagnostics": {
                "path": diagnostics_path.name,
                "sha256": diagnostics_sha256,
                "universe_selected_count": len(
                    collection_diagnostics.get("universe_selected_symbols", [])
                ),
                "technical_requested_count": technical_requested_count,
                "technical_collected_count": technical_collected_count,
                "technical_failed_count": technical_failed_count,
                "fundamental_missing_count": fundamental_missing_count,
            },
            "research_universe_prefiltered_by_liquidity": bool(
                config.LIQUIDITY_FILTER_ENABLED
                and config.SCAN_ALL_NSE
                and config.PREFILTER_RESEARCH_UNIVERSE_BY_LIQUIDITY
            ),
        },
    )
    scored_df["Run_Git_SHA"] = manifest["git_sha"]
    scored_df["Run_Git_Dirty"] = manifest["git_dirty"]
    scored_df["Run_Manifest_Schema_Version"] = manifest["schema_version"]

    csv_path = config.OUTPUT_DIR / f"advanced_analysis_{analysis_now.strftime('%Y%m%d')}.csv"
    scored_df.to_csv(csv_path, index=False)
    logger.info(f"Results saved: {csv_path}")

    if getattr(config, "RUN_MANIFEST_ENABLED", True):
        manifest["outputs"] = [
            {
                "path": csv_path.name,
                "sha256": sha256_file(csv_path),
                "size_bytes": csv_path.stat().st_size,
                "rows": len(scored_df),
            },
            {
                "path": diagnostics_path.name,
                "sha256": diagnostics_sha256,
                "size_bytes": diagnostics_path.stat().st_size,
                "kind": "collection_diagnostics",
            },
        ]
        manifest_path = csv_path.with_suffix(".manifest.json")
        write_run_manifest(manifest_path, manifest)
        logger.info("Run manifest saved: %s", manifest_path)

    # Backtest log
    if getattr(config, "BACKTEST_WRITES_ENABLED", True):
        backtest = BacktestEngine(config.OUTPUT_DIR, config.MODEL_VERSION)
        backtest.log_run(date_str, scored_df)
        perf = backtest.analyze_performance()
        if perf:
            logger.info(
                "Realized performance by rating for model %s: %s",
                config.MODEL_VERSION,
                perf,
            )
    else:
        logger.info("Backtest writes disabled for this isolated run")

    # Dashboard. Same depth as the emailed PDF/CSV so one run cannot publish
    # two different "top" lists.
    dashboard_path = InteractiveDashboard.generate(
        scored_df,
        date_str,
        config.OUTPUT_DIR,
        top_n=getattr(config, "TOP_STOCKS_COUNT", 20),
    )

    # Email (send_email handles its own retries and returns False on failure; no re-raise)
    if config.EMAIL_ENABLED:
        reporter = EmailReporter(config)
        html = reporter.create_html_report(scored_df, date_str)
        pdf_path = reporter.create_pdf_report(scored_df, date_str) if config.ATTACH_PDF else None
        email_sent = reporter.send_email(
            html,
            date_str,
            csv_path if config.ATTACH_CSV else None,
            pdf_path if config.ATTACH_PDF else None,
        )
        if not email_sent:
            raise RuntimeError("Report generation succeeded but email delivery failed")

    # WhatsApp
    if config.WHATSAPP_ENABLED:
        try:
            wrep = WhatsAppReporter(config)
            wrep.send_whatsapp(scored_df, date_str)
        except Exception as e:
            logger.error(f"WhatsApp failed: {e}")

    logger.info("=" * 60)


if __name__ == '__main__':
    try:
        run_daily_analysis()
    except Exception as exc:
        logger.error(f'Fatal error: {exc}')
        import traceback
        traceback.print_exc()
        sys.exit(1)
