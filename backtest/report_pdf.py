"""PDF rendering of the P0 walk-forward report.

The JSON report is the machine artefact; this is the one a human reads and
circulates. It is written to a tracked path rather than the gitignored output
directory precisely so it can be committed and compared across runs.

Two things this document must never do, and the layout enforces both:

* **Present a price-only ablation as a validation of Model 5.0.** Quality, growth
  and value carry 70% of the production score and none of them are exercised
  here. The limitations panel is on page one, above any result.
* **Report a number without the assumption behind it.** The delisting policy, the
  cost model and the universe rule each change the headline, so each is printed
  next to it.

Palette matches ``screener.reporting`` so the two documents read as one family.
"""

from __future__ import annotations

from datetime import datetime
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

INK = "#102A43"
TEAL = "#22A6A1"
DEEP_TEAL = "#0E6473"
ROW_TINT = "#F2F6F7"
RULE = "#D8E2E8"
CREAM = "#F7F5EF"
WARN = "#B54708"
WARN_TINT = "#FEF6EE"

# Strategies whose scores are constant, so a rank IC is undefined rather than
# zero. Printed as "n/a" instead of a dash that could read as a missing run.
CONSTANT_SCORE_STRATEGIES = frozenset({"equal_weight_universe"})


def _fmt(value, spec=".4f", dash="-"):
    if value is None:
        return dash
    try:
        return format(float(value), spec)
    except (TypeError, ValueError):
        return str(value)


def _pct(value, spec=".2f"):
    if value is None:
        return "-"
    try:
        return f"{float(value):{spec}}%"
    except (TypeError, ValueError):
        return str(value)


def _rupees(value):
    if value is None:
        return "-"
    try:
        value = float(value)
    except (TypeError, ValueError):
        return str(value)
    if value >= 1e7:
        return f"Rs {value / 1e7:.2f} cr"
    if value >= 1e5:
        return f"Rs {value / 1e5:.2f} lakh"
    return f"Rs {value:,.0f}"


def write_pdf(payload, path):
    """Render ``payload`` (the JSON report dict) to a PDF at ``path``."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.platypus import (
            PageBreak,
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )
    except ImportError:
        logger.warning(
            "PDF report skipped: reportlab is not installed (it is in requirements.txt)."
        )
        return None

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    title_style = ParagraphStyle(
        "title", fontName="Helvetica-Bold", fontSize=17, textColor=colors.HexColor(INK),
        leading=21, spaceAfter=2,
    )
    subtitle_style = ParagraphStyle(
        "subtitle", fontName="Helvetica", fontSize=9.5,
        textColor=colors.HexColor(DEEP_TEAL), leading=13, spaceAfter=10,
    )
    heading_style = ParagraphStyle(
        "heading", fontName="Helvetica-Bold", fontSize=11.5,
        textColor=colors.HexColor(INK), leading=15, spaceBefore=12, spaceAfter=5,
    )
    body_style = ParagraphStyle(
        "body", fontName="Helvetica", fontSize=8.8, textColor=colors.HexColor(INK),
        leading=12.5, spaceAfter=5,
    )
    warn_style = ParagraphStyle(
        "warn", fontName="Helvetica", fontSize=8.8, textColor=colors.HexColor(WARN),
        leading=12.5, spaceAfter=4,
    )
    warn_head_style = ParagraphStyle(
        "warnhead", fontName="Helvetica-Bold", fontSize=9.5,
        textColor=colors.HexColor(WARN), leading=13, spaceAfter=3,
    )

    def table(data, widths, *, align_right_from=1, font_size=8.2):
        style = TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(INK)),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, -1), font_size),
            ("TOPPADDING", (0, 0), (-1, -1), 3.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1),
             [colors.white, colors.HexColor(ROW_TINT)]),
            ("LINEBELOW", (0, 0), (-1, 0), 1.2, colors.HexColor(TEAL)),
            ("LINEBELOW", (0, 1), (-1, -1), 0.3, colors.HexColor(RULE)),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (align_right_from, 0), (-1, -1), "RIGHT"),
        ])
        return Table(data, colWidths=widths, style=style, hAlign="LEFT")

    story = []
    horizons = payload.get("horizons") or []
    window = payload.get("window", {})
    rebalances = payload.get("rebalance_dates") or []

    # ---- header ---------------------------------------------------------
    story.append(Paragraph("P0 Walk-Forward Validation", title_style))
    story.append(
        Paragraph(
            f"Point-in-time backtest of price-derived factor blocks &nbsp;|&nbsp; "
            f"{window.get('start')} to {window.get('end')} &nbsp;|&nbsp; "
            f"{payload.get('frequency')} rebalance, {len(rebalances)} dates "
            f"&nbsp;|&nbsp; generated {payload.get('generated_at')}",
            subtitle_style,
        )
    )

    # ---- what this is not ------------------------------------------------
    story.append(Paragraph("What this report does and does not establish", warn_head_style))
    story.append(
        Paragraph(
            "<b>This is not a validation of Model 5.0.</b> It exercises only the "
            "price-derived blocks. Quality, growth and value together carry 70% of "
            "the production score and require point-in-time fundamentals that are "
            "not yet ingested, so none of them are tested here.",
            warn_style,
        )
    )
    story.append(
        Paragraph(
            "It answers one question from p0.md &sect;7E: <b>how much of the model's "
            "behaviour is momentum?</b> A momentum-only ranking that performs close "
            "to the full model would mean the fundamental blocks are decoration. "
            "Read every number below as evidence about momentum and risk, not about "
            "Model 5.0.",
            warn_style,
        )
    )
    story.append(
        Paragraph(
            "Two further gaps: these ablations rank <b>market-wide</b> where "
            "production ranks within sector, and momentum-only omits "
            "RS_Sector_6M_Pct (20% of the production momentum block) because the "
            "bhavcopy archive carries no sector classification.",
            warn_style,
        )
    )
    story.append(Spacer(1, 0.25 * cm))

    # ---- integrity -------------------------------------------------------
    securities = payload.get("securities", {})
    actions = payload.get("corporate_actions", {})
    cost_model = payload.get("cost_model")
    universe_rule = payload.get("universe_rule", {})

    story.append(Paragraph("Integrity controls", heading_style))
    integrity = [
        ["Control", "Status"],
        ["Universe source",
         "Archived NSE bhavcopy per session (point-in-time, includes delisted names)"],
        ["Survivorship",
         f"{securities.get('securities_total', '-')} securities; "
         f"{securities.get('delisted', '-')} delisted retained in-sample"],
        ["Identifier",
         f"ISIN-bridged Security_ID; "
         f"{securities.get('face_value_changes', '-')} face-value changes linked"],
        ["Execution", "Signal on close of t, fill at open of next confirmed session"],
        ["Corporate actions",
         f"{actions.get('ratio_actions', 0)} split/bonus adjusted, "
         f"{actions.get('dividend_events', 0)} dividends, "
         f"{actions.get('blocking_events', 0)} unadjustable events excluded"],
        ["Delisting policy", str(payload.get("delisting_policy", "-"))],
        ["Costs",
         "gross only (no cost model)" if not cost_model else
         f"effective-dated Indian charges + {cost_model.get('half_spread_rate', 0) * 1e4:.0f}bp "
         f"half-spread + sqrt impact at "
         f"{_rupees(cost_model.get('value_per_position'))}/position"],
        ["Eligibility",
         f"min turnover {_rupees(universe_rule.get('min_median_turnover_inr'))}/day, "
         f"trading frequency >= {universe_rule.get('min_trading_frequency')}, "
         f"history >= {universe_rule.get('min_history_sessions')} sessions, "
         f"{universe_rule.get('require_identifier_prefix', 'INE')}-class only (ETFs excluded)"],
        ["Parameters", "Frozen; no re-optimisation across the window"],
    ]
    story.append(table(integrity, [4.2 * cm, 12.6 * cm], align_right_from=99))

    # ---- universe --------------------------------------------------------
    diagnostics = payload.get("universe_diagnostics") or []
    if diagnostics:
        eligible = [row.get("eligible", 0) for row in diagnostics]
        considered = [row.get("input", 0) for row in diagnostics]
        story.append(Paragraph("Eligible universe per rebalance", heading_style))
        universe_rows = [
            ["Metric", "Value"],
            ["Rebalance dates", str(len(diagnostics))],
            ["Mean eligible", f"{sum(eligible) / max(1, len(eligible)):.0f}"],
            ["Min / max eligible", f"{min(eligible)} / {max(eligible)}"],
            ["Mean considered before filters",
             f"{sum(considered) / max(1, len(considered)):.0f}"],
        ]
        story.append(table(universe_rows, [7.0 * cm, 4.0 * cm]))

    story.append(PageBreak())

    # ---- results ---------------------------------------------------------
    for basis in ("gross", "net"):
        results = payload.get(basis)
        if not results:
            continue

        label = "Gross of costs" if basis == "gross" else "Net of costs"
        story.append(Paragraph(f"Rank information coefficient &mdash; {label}", heading_style))
        story.append(
            Paragraph(
                "Spearman correlation between the score on the rebalance date and the "
                "forward return. Reported with its distribution because a mean carried "
                "by two extraordinary periods is a different claim from one earned "
                "consistently. <b>%+</b> is the share of periods with a positive IC.",
                body_style,
            )
        )
        header = ["Strategy", "Horizon", "Periods", "Mean", "Median", "%+", "Worst", "Best"]
        rows = [header]
        for strategy_name in sorted(results):
            for horizon in horizons:
                entry = results[strategy_name].get(f"{horizon}M")
                if not entry:
                    continue
                ic = entry.get("ic", {})
                undefined = strategy_name in CONSTANT_SCORE_STRATEGIES
                rows.append([
                    strategy_name.replace("_", " "),
                    f"{horizon}M",
                    str(ic.get("periods", 0)),
                    "n/a" if undefined else _fmt(ic.get("mean")),
                    "n/a" if undefined else _fmt(ic.get("median")),
                    "n/a" if undefined else (
                        _pct((ic.get("positive_share") or 0) * 100, ".0f")
                        if ic.get("positive_share") is not None else "-"
                    ),
                    "n/a" if undefined else _fmt(ic.get("worst")),
                    "n/a" if undefined else _fmt(ic.get("best")),
                ])
        story.append(table(rows, [4.0 * cm, 1.6 * cm, 1.7 * cm, 1.9 * cm, 1.9 * cm,
                                  1.6 * cm, 1.8 * cm, 1.8 * cm]))

        story.append(Paragraph(f"Portfolio and bucket evidence &mdash; {label}", heading_style))
        story.append(
            Paragraph(
                "<b>vs universe</b> is the top-20 mean period return minus the eligible "
                "universe mean, so it already controls for how the market did. "
                "<b>Monotonicity</b> is +1 when decile means fall cleanly from best "
                "score to worst, 0 when the ranking carries no ordering. "
                "<b>Spread</b> is top decile minus bottom decile.",
                body_style,
            )
        )
        rows = [["Strategy", "Horizon", "Universe", "Top 20", "vs universe",
                 "Monotonicity", "D1-D10"]]
        for strategy_name in sorted(results):
            for horizon in horizons:
                entry = results[strategy_name].get(f"{horizon}M")
                if not entry:
                    continue
                top = entry.get("portfolios", {}).get("top_20", {})
                rows.append([
                    strategy_name.replace("_", " "),
                    f"{horizon}M",
                    _pct(entry.get("universe_mean_return_pct")),
                    _pct(top.get("mean_period_return_pct")),
                    _pct(top.get("vs_universe_pct"), "+.2f"),
                    _fmt(entry.get("monotonicity"), ".3f"),
                    _pct(entry.get("bucket_spread"), "+.2f"),
                ])
        story.append(table(rows, [4.0 * cm, 1.6 * cm, 2.1 * cm, 2.1 * cm, 2.4 * cm,
                                  2.4 * cm, 2.1 * cm]))
        story.append(Spacer(1, 0.2 * cm))

    # ---- turnover and coverage ------------------------------------------
    turnover = payload.get("turnover") or {}
    if turnover:
        story.append(Paragraph("Turnover", heading_style))
        story.append(
            Paragraph(
                "One-way turnover of a top-20 portfolio per rebalance. 1.0 means the "
                "portfolio was fully replaced. High turnover is what converts a real "
                "gross edge into no net edge.",
                body_style,
            )
        )
        rows = [["Strategy", "Mean one-way turnover", "Rebalances"]]
        for strategy_name in sorted(turnover):
            entry = turnover[strategy_name]
            rows.append([
                strategy_name.replace("_", " "),
                _fmt(entry.get("mean_one_way_turnover"), ".3f"),
                str(entry.get("periods", 0)),
            ])
        story.append(table(rows, [5.5 * cm, 5.0 * cm, 3.0 * cm]))

    coverage = payload.get("fill_coverage") or {}
    if coverage:
        story.append(Paragraph("Fill coverage", heading_style))
        story.append(
            Paragraph(
                "Share of scored positions that produced a usable forward return. A "
                "dropped position is recorded with a reason rather than silently "
                "omitted; a thin horizon here weakens every statistic above it.",
                body_style,
            )
        )
        rows = [["Horizon", "Coverage", "Positions", "Main reasons dropped"]]
        for horizon_label, entry in coverage.items():
            skipped = entry.get("skipped") or {}
            top_reasons = ", ".join(
                f"{name} {count}"
                for name, count in sorted(
                    skipped.items(), key=lambda item: -item[1]
                )[:3]
            )
            rows.append([
                horizon_label,
                _pct((entry.get("coverage") or 0) * 100, ".1f"),
                str(entry.get("total", 0)),
                top_reasons or "none",
            ])
        story.append(table(rows, [2.0 * cm, 2.2 * cm, 2.4 * cm, 10.2 * cm]))

    # ---- how to read -----------------------------------------------------
    story.append(Paragraph("How to read this", heading_style))
    story.append(
        Paragraph(
            "<b>The random_ranking row is the calibration.</b> It is a seeded random "
            "score, so its IC is what &quot;no signal&quot; measures on this universe "
            "and horizon. Any strategy whose IC is not clearly separated from it has "
            "not demonstrated anything.",
            body_style,
        )
    )
    story.append(
        Paragraph(
            "<b>equal_weight_universe scores every name identically</b>, so its rank IC "
            "is undefined rather than zero. It is present as the return benchmark from "
            "p0.md &sect;7B, not as a ranking.",
            body_style,
        )
    )
    story.append(
        Paragraph(
            "<b>Judge consistency before magnitude.</b> A mean IC of 0.03 with 70% of "
            "periods positive is stronger evidence than a mean of 0.06 driven by two "
            "periods. Check the %+ and worst columns before the mean.",
            body_style,
        )
    )
    story.append(
        Paragraph(
            "<b>Net is the number that matters.</b> If a gross edge disappears net of "
            "costs, the ranking may still be real but is not tradable at this position "
            "size and turnover.",
            body_style,
        )
    )

    # ---- caveats ---------------------------------------------------------
    story.append(Paragraph("Known limitations of this run", heading_style))
    for text in (
        "<b>Restatement bias remains.</b> No fundamentals are used here, so it does "
        "not bite yet &mdash; but it will once the XBRL panel lands, for any period "
        "falling back to current values rather than as-filed ones.",
        "<b>Delisting recovery is an assumption, not an observation.</b> The bhavcopy "
        "does not record why a security stopped trading. Re-run with "
        "--delisting-strategy zero and last_close to bound how much the headline "
        "depends on it.",
        "<b>Period count is modest.</b> Monthly rebalancing over roughly four years is "
        "enough to judge cross-sectional rank IC and its stability. It is not enough "
        "to claim regime robustness across a full cycle.",
        "<b>Overlapping horizons are not independent.</b> A 6M horizon sampled monthly "
        "reuses most of its window, so any t-statistic on per-period ICs overstates "
        "significance and is reported as a rough guide only.",
        "<b>Cost assumptions are documented estimates.</b> Brokerage defaults to zero "
        "(discount-broker delivery); half-spread and impact coefficient are modelled, "
        "not measured. Gross and net are shown separately for that reason.",
    ):
        story.append(Paragraph(text, body_style))

    story.append(Paragraph("Next step", heading_style))
    story.append(
        Paragraph(
            "Phase B: ingest NSE XBRL filings into a point-in-time fundamental panel "
            "keyed on filing timestamp, which unlocks the quality, growth and value "
            "blocks and makes a genuine Model 5.0 walk-forward possible. Until then "
            "the fundamental 70% of the score remains untested.",
            body_style,
        )
    )

    def decorate(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(colors.HexColor(CREAM))
        canvas.rect(0, A4[1] - 1.05 * cm, A4[0], 1.05 * cm, stroke=0, fill=1)
        canvas.setFillColor(colors.HexColor(INK))
        canvas.setFont("Helvetica-Bold", 7.5)
        canvas.drawString(1.5 * cm, A4[1] - 0.72 * cm, "MODEL 5.0  /  P0 VALIDATION")
        canvas.setFillColor(colors.HexColor(DEEP_TEAL))
        canvas.setFont("Helvetica", 7.5)
        canvas.drawRightString(
            A4[0] - 1.5 * cm,
            A4[1] - 0.72 * cm,
            "Research artefact - not an investment recommendation",
        )
        canvas.setStrokeColor(colors.HexColor(RULE))
        canvas.setLineWidth(0.4)
        canvas.line(1.5 * cm, 1.15 * cm, A4[0] - 1.5 * cm, 1.15 * cm)
        canvas.setFillColor(colors.HexColor(DEEP_TEAL))
        canvas.setFont("Helvetica", 7)
        canvas.drawString(1.5 * cm, 0.75 * cm, f"Page {doc.page}")
        canvas.drawRightString(
            A4[0] - 1.5 * cm,
            0.75 * cm,
            datetime.now().strftime("%Y-%m-%d %H:%M"),
        )
        canvas.restoreState()

    document = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        leftMargin=1.5 * cm,
        rightMargin=1.5 * cm,
        topMargin=1.6 * cm,
        bottomMargin=1.5 * cm,
        title="P0 Walk-Forward Validation",
        author="ai_stock_screener",
    )
    document.build(story, onFirstPage=decorate, onLaterPages=decorate)
    return path
