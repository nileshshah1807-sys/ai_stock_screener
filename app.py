#!/usr/bin/env python3
"""Daily stock-screener composition root and backwards-compatible API."""

import logging
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from scoring.transcript_enricher import (
    TranscriptSentimentEnricher,
    rank_actionable_recommendations,
)
from red_flags.enricher import RedFlagEnricher
from red_flags.shadow import RedFlagShadowSimulator
from screener.data_collection import StockDataCollector
from screener.liquidity import LiquidityQualityEnricher
from screener.market_data import AlternativeData, BacktestEngine, PriceCache, TechnicalEnhancer, fmt_cr, fmt_f, fmt_pct
from screener.reporting import EmailReporter, InteractiveDashboard, WhatsAppReporter
from screener.runtime import Config, IPv4SMTP, IPv4SMTP_SSL, configure_runtime_cache, load_local_config
from screener.scoring import StockScorer, fundamental_model_for_row, score_financial_services, score_fundamentals, score_real_estate, sector_relative_fund_scores, sort_by_recommendation
from screener.valuation import ReverseDCFModel

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

def run_daily_analysis():
    logger.info("=" * 60)
    logger.info("STARTING ADVANCED STOCK ANALYSIS (v2.2)")
    logger.info("=" * 60)
    config = Config()
    configure_runtime_cache(config)
    date_str = datetime.now().strftime("%d-%m-%Y")
    logger.info(f"Analysis date: {date_str}")

    collector = StockDataCollector(config)
    symbols = collector.get_comprehensive_stock_list()
    tech_df = collector.download_stock_data(symbols)
    if tech_df.empty:
        raise RuntimeError("No technical data was collected")

    # P3: liquidity pre-filter before the slow per-ticker fundamentals stage
    if config.LIQUIDITY_FILTER_ENABLED and config.SCAN_ALL_NSE:
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
        tech_df = tech_df[
            (tech_df["Current_Price"] >= config.MIN_PRICE_INR)
            & (tech_df["Avg_Turnover_INR"] >= config.MIN_AVG_TURNOVER_INR)
            & (
                tech_df["Median_Turnover_20D_INR"]
                >= config.MIN_MEDIAN_TURNOVER_20D_INR
            )
        ].reset_index(drop=True)
        logger.info(
            f"Liquidity filter: kept {len(tech_df)}/{before} "
            f"(dropped {before - len(tech_df)} names below Rs{config.MIN_PRICE_INR:.0f} "
            f"or Rs{config.MIN_AVG_TURNOVER_INR:,.0f} mean / "
            f"Rs{config.MIN_MEDIAN_TURNOVER_20D_INR:,.0f} 20D median turnover)"
        )
        if tech_df.empty:
            raise RuntimeError("Liquidity filter removed every stock")

    alt_data = AlternativeData.get_fii_dii_snapshot()
    logger.info(f"Alternative data (FII/DII): {alt_data}")

    fund_df = collector.get_fundamental_data(tech_df)
    if fund_df.empty:
        raise RuntimeError("No fundamental data was collected")

    merged_df = pd.merge(tech_df, fund_df, on="Symbol", how="inner")
    logger.info(f"Merged: {len(merged_df)} stocks")
    if merged_df.empty:
        raise RuntimeError("No symbols remain after merging technical and fundamental data")

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
            scored_df = TranscriptSentimentEnricher(config).enrich(scored_df)
            available_transcripts = int((scored_df["Transcript_Status"] == "Available").sum())
            logger.info(f"Transcript sentiment available for {available_transcripts} stock(s)")
        except Exception as e:
            if getattr(config, "TRANSCRIPT_FAIL_ON_ERROR", True):
                raise RuntimeError("Transcript sentiment enrichment failed") from e
            logger.warning(f"Transcript sentiment enrichment skipped: {e}")

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

    # Keep research coverage broad, but require persistent traded value for the
    # highest-conviction label. This leaves Final_Score unchanged and exposes
    # the exact liquidity evidence and cap reason in the report.
    scored_df = LiquidityQualityEnricher(config).enrich(scored_df)
    liquidity_caps = int(scored_df["Liquidity_Rating_Capped"].sum())
    logger.info("Liquidity conviction gate capped %s STRONG BUY label(s)", liquidity_caps)

    # One final deterministic ordering after every rating gate. Transcript
    # confirmation is only a tie-break because its effect is already in score.
    scored_df = rank_actionable_recommendations(scored_df)

    # News sentiment for the top N picks (post-scoring, so it's the *actual* top N)
    n = min(config.NEWS_SENTIMENT_TOP_N, len(scored_df))
    sentiment_map = {}
    for sym in scored_df["Symbol"].head(n):
        sentiment_map[sym] = AlternativeData.get_news_sentiment(sym)["sentiment"]
    scored_df["News_Sentiment"] = scored_df["Symbol"].map(
        lambda s: sentiment_map.get(s, "-")
    )
    logger.info(f"News sentiment fetched for top {len(sentiment_map)} symbols")

    csv_path = config.OUTPUT_DIR / f"advanced_analysis_{datetime.now().strftime('%Y%m%d')}.csv"
    scored_df.to_csv(csv_path, index=False)
    logger.info(f"Results saved: {csv_path}")

    # Backtest log
    backtest = BacktestEngine(config.OUTPUT_DIR)
    backtest.log_run(date_str, scored_df)
    perf = backtest.analyze_performance()
    if perf:
        logger.info(f"Avg combined score by rating (all runs): {perf}")

    # Dashboard
    dashboard_path = InteractiveDashboard.generate(scored_df, date_str, config.OUTPUT_DIR)

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
