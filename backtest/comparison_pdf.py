"""CAGR comparison report: the model against the indices.

A single question, answered without hedging: **did this beat simply owning the
index, and by how much?**

Three things the layout refuses to let a reader get wrong.

*The basis is stated next to every number.* NSE's historical endpoint serves
price indices only -- every TRI spelling returns nothing -- so the headline
compares price return to price return. Putting the strategy's dividend-inclusive
return next to a dividend-less index would hand it roughly the market's yield,
about 1-1.5% a year in India, for nothing. The dividend contribution is shown
separately instead.

*CAGR comes only from chaining periods.* At a monthly rebalance the one-month
horizon chains exactly, because each period's exit session is the next period's
entry. Compounding an overlapping 6-month horizon sampled monthly would count the
same market move up to six times.

*Net is the number that matters.* Gross and net sit side by side so the cost
model's contribution is visible rather than assumed.
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
GOOD = "#0E6473"
BAD = "#B42318"


def _fmt(value, spec=".2f", dash="-"):
    if value is None:
        return dash
    try:
        return format(float(value), spec)
    except (TypeError, ValueError):
        return str(value)


def _pct(value, spec=".2f"):
    return "-" if value is None else f"{_fmt(value, spec)}%"


def write_comparison_pdf(payload, path, *, comparison=None):
    """Render the CAGR comparison to ``path``.

    ``payload`` is the walk-forward report dict; ``comparison`` the output of
    :func:`backtest.benchmarks.build_comparison`.
    """
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
        logger.warning("Comparison PDF skipped: reportlab is not installed.")
        return None

    comparison = comparison or payload.get("comparison") or {}
    if not comparison:
        logger.warning("Comparison PDF skipped: no comparison data")
        return None

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    title_style = ParagraphStyle(
        "title", fontName="Helvetica-Bold", fontSize=17,
        textColor=colors.HexColor(INK), leading=21, spaceAfter=2,
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
        "body", fontName="Helvetica", fontSize=8.8,
        textColor=colors.HexColor(INK), leading=12.5, spaceAfter=5,
    )
    warn_style = ParagraphStyle(
        "warn", fontName="Helvetica", fontSize=8.8,
        textColor=colors.HexColor(WARN), leading=12.5, spaceAfter=4,
    )

    def table(data, widths, *, align_right_from=1, font_size=8.2, emphasis=None):
        style = [
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
        ]
        for row_index, column_index, colour in emphasis or []:
            style.append(
                ("TEXTCOLOR", (column_index, row_index), (column_index, row_index),
                 colors.HexColor(colour))
            )
            style.append(
                ("FONTNAME", (column_index, row_index), (column_index, row_index),
                 "Helvetica-Bold")
            )
        return Table(data, colWidths=widths, style=TableStyle(style), hAlign="LEFT")

    story = []
    window = payload.get("window", {})
    size = comparison.get("portfolio_size", 20)
    horizon = comparison.get("horizon_months", 1)
    rebalances = comparison.get("rebalances", 0)

    story.append(Paragraph("Model vs Index &mdash; CAGR Comparison", title_style))
    story.append(
        Paragraph(
            f"{window.get('start')} to {window.get('end')} &nbsp;|&nbsp; "
            f"{payload.get('frequency')} rebalance, {rebalances} periods "
            f"&nbsp;|&nbsp; equal-weighted top {size} &nbsp;|&nbsp; "
            f"{horizon}-month holding, non-overlapping &nbsp;|&nbsp; "
            f"generated {payload.get('generated_at')}",
            subtitle_style,
        )
    )

    story.append(Paragraph("Basis", heading_style))
    story.append(
        Paragraph(
            "<b>Price return compared with price return.</b> NSE's historical "
            "index endpoint serves price indices only &mdash; every total-return "
            "(TRI) spelling returns no data. The strategy's dividends are "
            "therefore reported separately rather than folded into the headline, "
            "because comparing a dividend-inclusive strategy against a "
            "dividend-less index would credit the model with roughly the market's "
            "yield (about 1&ndash;1.5% a year in India) for nothing.",
            body_style,
        )
    )
    story.append(
        Paragraph(
            "<b>Index returns are measured over the sessions the strategy actually "
            "traded</b> &mdash; the same next-session entry and the same exit "
            "&mdash; not between month-ends, so neither side is measuring a "
            "different span of market time.",
            body_style,
        )
    )

    # ---- headline ---------------------------------------------------------
    strategies = comparison.get("strategies", {})
    indices = comparison.get("indices", {})
    index_names = sorted(indices)

    story.append(Paragraph("Headline: CAGR by strategy", heading_style))
    header = ["Strategy", "Gross CAGR", "Net CAGR"] + [
        f"vs {name.replace('NIFTY ', 'N')}" for name in index_names
    ]
    rows = [header]
    emphasis = []
    for row_index, name in enumerate(sorted(strategies), start=1):
        entry = strategies[name]
        row = [
            name.replace("_", " "),
            _pct(entry.get("gross_cagr_pct")),
            _pct(entry.get("net_cagr_pct")),
        ]
        for column_index, index_name in enumerate(index_names, start=3):
            versus = entry.get("versus", {}).get(index_name, {})
            difference = versus.get("cagr_difference_pct")
            row.append(_pct(difference, "+.2f"))
            if difference is not None:
                emphasis.append(
                    (row_index, column_index, GOOD if difference > 0 else BAD)
                )
        rows.append(row)
    widths = [3.6 * cm, 2.3 * cm, 2.3 * cm] + [2.4 * cm] * len(index_names)
    story.append(table(rows, widths, emphasis=emphasis))
    story.append(
        Paragraph(
            "<b>vs &lt;index&gt;</b> is the strategy's CAGR minus that index's "
            "CAGR over the identical periods, net of costs where a cost model ran. "
            "A positive number is outperformance in annualised percentage points.",
            body_style,
        )
    )

    # ---- index reference --------------------------------------------------
    story.append(Paragraph("Index reference", heading_style))
    rows = [["Index", "CAGR", "Volatility", "Sharpe", "Max drawdown", "Periods"]]
    for name in index_names:
        entry = indices[name]
        metrics = entry.get("metrics", {})
        rows.append([
            name,
            _pct(entry.get("cagr_pct")),
            _pct(metrics.get("volatility_ann_pct")),
            _fmt(metrics.get("sharpe"), ".2f"),
            _pct(metrics.get("max_drawdown_pct")),
            str(entry.get("periods", 0)),
        ])
    universe = comparison.get("eligible_universe", {})
    if universe.get("cagr_pct") is not None:
        rows.append([
            "Eligible universe (equal weight)",
            _pct(universe.get("cagr_pct")),
            "-", "-", "-",
            str(universe.get("periods", 0)),
        ])
    story.append(
        table(rows, [6.2 * cm, 2.1 * cm, 2.2 * cm, 1.8 * cm, 2.6 * cm, 1.8 * cm])
    )
    story.append(
        Paragraph(
            "The <b>eligible universe</b> row is the benchmark that controls for "
            "size and breadth: the same point-in-time universe the strategy chose "
            "from, held equally weighted. Beating NIFTY 500 while trailing this "
            "means the model captured a small-cap tilt rather than stock selection.",
            body_style,
        )
    )

    story.append(PageBreak())

    # ---- risk-adjusted ----------------------------------------------------
    story.append(Paragraph("Risk-adjusted comparison", heading_style))
    rows = [["Strategy", "Basis", "CAGR", "Volatility", "Sharpe", "Max DD", "Hit rate"]]
    for name in sorted(strategies):
        entry = strategies[name]
        metrics = entry.get("net_metrics") or entry.get("gross_metrics") or {}
        rows.append([
            name.replace("_", " "),
            "net" if entry.get("net_metrics") else "gross",
            _pct(entry.get("net_cagr_pct") or entry.get("gross_cagr_pct")),
            _pct(metrics.get("volatility_ann_pct")),
            _fmt(metrics.get("sharpe"), ".2f"),
            _pct(metrics.get("max_drawdown_pct")),
            _pct(metrics.get("hit_rate_pct"), ".0f"),
        ])
    story.append(
        table(rows, [3.6 * cm, 1.6 * cm, 2.1 * cm, 2.2 * cm, 1.8 * cm, 2.4 * cm, 2.0 * cm])
    )

    # ---- excess vs the broad index ---------------------------------------
    broad = "NIFTY 500" if "NIFTY 500" in indices else (index_names[0] if index_names else None)
    if broad:
        story.append(
            Paragraph(f"Excess return against {broad}", heading_style)
        )
        rows = [[
            "Strategy", "Mean excess/period", "Tracking error",
            "Information ratio", "Periods beaten",
        ]]
        for name in sorted(strategies):
            versus = strategies[name].get("versus", {}).get(broad, {})
            excess = versus.get("excess", {})
            share = excess.get("periods_beaten_share")
            rows.append([
                name.replace("_", " "),
                _pct(excess.get("mean_excess_pct"), "+.2f"),
                _pct(excess.get("tracking_error_ann_pct")),
                _fmt(excess.get("information_ratio"), ".2f"),
                _pct(None if share is None else share * 100, ".0f"),
            ])
        story.append(
            table(rows, [3.6 * cm, 3.2 * cm, 2.8 * cm, 3.0 * cm, 2.8 * cm])
        )
        story.append(
            Paragraph(
                "<b>Information ratio</b> is excess return per unit of tracking "
                "error &mdash; how reliably the outperformance was earned, not how "
                "large it was. <b>Periods beaten</b> is the share of rebalances "
                "where the strategy outpaced the index; a high CAGR with a low "
                "share was carried by a handful of periods.",
                body_style,
            )
        )

    # ---- turnover ---------------------------------------------------------
    turnover = payload.get("turnover") or {}
    if turnover:
        story.append(Paragraph("Turnover and cost drag", heading_style))
        rows = [["Strategy", "One-way turnover", "Gross CAGR", "Net CAGR", "Cost drag"]]
        for name in sorted(strategies):
            entry = strategies[name]
            gross = entry.get("gross_cagr_pct")
            net = entry.get("net_cagr_pct")
            drag = None if gross is None or net is None else gross - net
            rows.append([
                name.replace("_", " "),
                _fmt((turnover.get(name) or {}).get("mean_one_way_turnover"), ".3f"),
                _pct(gross),
                _pct(net),
                _pct(drag, "-.2f") if drag is not None else "-",
            ])
        story.append(
            table(rows, [3.6 * cm, 3.0 * cm, 2.4 * cm, 2.4 * cm, 2.4 * cm])
        )
        story.append(
            Paragraph(
                "Cost drag is annualised, and it is the difference between a "
                "ranking that works on paper and one that works in an account. "
                "A strategy replacing most of its book every month pays it "
                "repeatedly.",
                body_style,
            )
        )

    # ---- caveats ----------------------------------------------------------
    story.append(Paragraph("Before quoting these numbers", heading_style))
    for text in (
        "<b>An index is investable and this portfolio is a simulation.</b> The "
        "index CAGR is achievable through a low-cost fund; the strategy CAGR "
        "assumes every fill happened at the modelled price and size.",
        "<b>The window is what it is.</b> A CAGR over a few years is dominated by "
        "the market regime inside it. Check the periods-beaten share and the "
        "drawdown before treating a CAGR gap as skill.",
        "<b>Costs are modelled, not measured.</b> Statutory charges are exact and "
        "effective-dated; half-spread and market impact are assumptions, which is "
        "why gross and net are both shown.",
        "<b>Delisting recovery is an assumption.</b> Re-run with "
        "--delisting-strategy zero and last_close to see how much of the gap "
        "depends on it.",
    ):
        story.append(Paragraph(text, warn_style if text.startswith("<b>An index") else body_style))

    def decorate(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(colors.HexColor(CREAM))
        canvas.rect(0, A4[1] - 1.05 * cm, A4[0], 1.05 * cm, stroke=0, fill=1)
        canvas.setFillColor(colors.HexColor(INK))
        canvas.setFont("Helvetica-Bold", 7.5)
        canvas.drawString(1.5 * cm, A4[1] - 0.72 * cm, "MODEL 5.0  /  CAGR vs INDEX")
        canvas.setFillColor(colors.HexColor(DEEP_TEAL))
        canvas.setFont("Helvetica", 7.5)
        canvas.drawRightString(
            A4[0] - 1.5 * cm, A4[1] - 0.72 * cm,
            "Research artefact - not an investment recommendation",
        )
        canvas.setStrokeColor(colors.HexColor(RULE))
        canvas.setLineWidth(0.4)
        canvas.line(1.5 * cm, 1.15 * cm, A4[0] - 1.5 * cm, 1.15 * cm)
        canvas.setFillColor(colors.HexColor(DEEP_TEAL))
        canvas.setFont("Helvetica", 7)
        canvas.drawString(1.5 * cm, 0.75 * cm, f"Page {doc.page}")
        canvas.drawRightString(
            A4[0] - 1.5 * cm, 0.75 * cm, datetime.now().strftime("%Y-%m-%d %H:%M")
        )
        canvas.restoreState()

    document = SimpleDocTemplate(
        str(path), pagesize=A4,
        leftMargin=1.5 * cm, rightMargin=1.5 * cm,
        topMargin=1.6 * cm, bottomMargin=1.5 * cm,
        title="Model vs Index CAGR Comparison", author="ai_stock_screener",
    )
    document.build(story, onFirstPage=decorate, onLaterPages=decorate)
    return path
