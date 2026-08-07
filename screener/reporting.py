"""Dashboard, email, PDF, and WhatsApp delivery."""

import base64
import logging
import os
import smtplib
from datetime import datetime
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import pandas as pd
import requests

from .market_data import fmt_cr, fmt_f, fmt_pct
from .runtime import IPv4SMTP, IPv4SMTP_SSL

try:
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False

logger = logging.getLogger(__name__)

class InteractiveDashboard:
    @staticmethod
    def generate(scored_df, date_str, output_dir):
        output_path = Path(output_dir) / f"dashboard_{date_str.replace('-', '')}.html"
        try:
            top10 = scored_df.head(10)
            rows_html = ""
            dcf_rows_html = ""
            for _, r in top10.iterrows():
                tag_class = "tag-" + str(r["Rating"]).lower().replace(" ", "-")
                sentiment = r.get("News_Sentiment", "-")
                rows_html += (
                    f"<tr><td>{int(r['Rank'])}</td><td><b>{r['Symbol']}</b></td>"
                    f"<td>₹{r['Current_Price']:,.0f}</td>"
                    f"<td>{fmt_f(r.get('PE_Ratio'), 1)}</td>"
                    f"<td>{r['Fundamental_Score']:.0f}</td>"
                    f"<td>{r['Technical_Score']:.0f}</td>"
                    f"<td>{r['Combined_Score']:.1f}</td>"
                    f"<td>{fmt_f(r.get('DCF_Valuation_Score'), 1)}</td>"
                    f"<td><b>{r.get('Final_Score', r['Combined_Score']):.1f}</b></td>"
                    f"<td>{r.get('Fundamental_Model', 'Generic Fundamental Model')}</td>"
                    f"<td>{r.get('Fund_Component_Summary', '-')}</td>"
                    f"<td>{r.get('Specialized_Quality_Gate_Reason', 'passed')}</td>"
                    f"<td>{r.get('Fundamental_Anomaly_Reason') or 'none'}</td>"
                    f"<td>{r.get('Transcript_Summary', 'No transcript')}</td>"
                    f"<td>{r.get('Transcript_Technical_Gate', 'No transcript')}</td>"
                    f"<td>{sentiment}</td>"
                    f"<td><span class='tag {tag_class}'>{r['Rating']}</span></td></tr>"
                )
                dcf_rows_html += (
                    f"<tr><td>{int(r['Rank'])}</td><td><b>{r['Symbol']}</b></td>"
                    f"<td>{r.get('DCF_Sector', 'Unknown')}</td>"
                    f"<td>\u20b9{r['Current_Price']:,.0f}</td>"
                    f"<td>{fmt_cr(r.get('DCF_Market_Cap'), 0)}</td>"
                    f"<td>{fmt_pct(r.get('DCF_FCF_Yield'), 1)}</td>"
                    f"<td>{fmt_pct(r.get('DCF_Expected_Growth'), 1)}</td>"
                    f"<td>{fmt_pct(r.get('DCF_Implied_FCF_CAGR'), 1)}</td>"
                    f"<td>{fmt_pct(r.get('DCF_Implied_Terminal_Growth'), 1)}</td>"
                    f"<td>{fmt_pct(r.get('DCF_Base_Case_Upside'), 1)}</td>"
                    f"<td>{r.get('DCF_Assessment', '-')}</td>"
                    f"<td><span class='tag {tag_class}'>{r['Rating']}</span></td></tr>"
                )

            # Score distribution histogram (5-point buckets, fixed-width SVG)
            bins = list(range(0, 101, 5))
            score_distribution_column = "Final_Score" if "Final_Score" in scored_df else "Combined_Score"
            counts = (
                pd.cut(scored_df[score_distribution_column].clip(0, 100), bins=bins, include_lowest=True)
                .value_counts()
                .sort_index()
            )
            max_count = int(counts.max()) if len(counts) and counts.max() > 0 else 1
            bar_w, gap = 60, 14
            bars = ""
            for i, (interval, count) in enumerate(counts.items()):
                h = (int(count) / max_count) * 200
                x = 20 + i * (bar_w + gap)
                bars += (
                    f'<rect x="{x}" y="{220 - h:.0f}" width="{bar_w}" height="{h:.0f}" fill="#303f9f" rx="4"/>'
                    f'<text x="{x + bar_w / 2}" y="{214 - h:.0f}" text-anchor="middle" font-size="12" fill="#333">{int(count)}</text>'
                    f'<text x="{x + bar_w / 2}" y="238" text-anchor="middle" font-size="10" fill="#777">{int(interval.left)}-{int(interval.right)}</text>'
                )
            chart_w = 40 + len(counts) * (bar_w + gap)
            html_content = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Stock Screener Dashboard - {date_str}</title>
<style>
body {{ font-family: 'Segoe UI', Arial, sans-serif; margin: 20px; background: #f5f7fa; color: #222; }}
.header {{ background: linear-gradient(90deg, #1a237e, #303f9f); color: white; padding: 30px; border-radius: 12px; margin-bottom: 25px; }}
h1 {{ margin: 0; font-size: 28px; letter-spacing: 0.5px; }}
.subtitle {{ opacity: 0.9; margin-top: 8px; font-size: 16px; }}
.card {{ background: white; border-radius: 12px; padding: 22px; margin-bottom: 25px; box-shadow: 0 4px 18px rgba(0,0,0,0.06); }}
h2 {{ color: #1a237e; margin-top: 0; font-size: 22px; border-bottom: 3px solid #e8eaf6; padding-bottom: 10px; }}
.stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 15px; margin-top: 15px; }}
.stat-box {{ background: linear-gradient(135deg, #e8eaf6, #f5f5f5); border-radius: 10px; padding: 18px; text-align: center; }}
.stat-value {{ font-size: 28px; font-weight: bold; color: #1a237e; }}
.stat-label {{ font-size: 12px; color: #555; margin-top: 6px; text-transform: uppercase; letter-spacing: 0.5px; }}
table {{ width: 100%; border-collapse: collapse; margin-top: 15px; }}
th {{ background-color: #1a237e; color: white; padding: 12px 8px; text-align: left; font-size: 13px; }}
td {{ padding: 10px 8px; border-bottom: 1px solid #e0e0e0; font-size: 13px; }}
tr:hover {{ background-color: #f8f9ff; }}
.tag {{ display: inline-block; padding: 3px 10px; border-radius: 16px; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.3px; }}
.tag-strong-buy {{ background: #e8f5e9; color: #1b5e20; }}
.tag-buy {{ background: #e3f2fd; color: #1565c0; }}
.tag-hold {{ background: #fff3e0; color: #ef6c00; }}
.tag-reduce {{ background: #fbe9e7; color: #d84315; }}
.tag-sell {{ background: #fce4ec; color: #c2185b; }}
.footer {{ text-align: center; color: #777; font-size: 12px; margin-top: 30px; padding-top: 20px; border-top: 1px solid #ddd; }}
</style>
</head><body>
<div class="header"><h1>📊 Advanced Stock Screener Dashboard</h1>
<div class="subtitle">Analysis Date: {date_str} | Interactive Report v2.2</div></div>
<div class="card"><h2>📈 Market Summary</h2>
<div class="stats">
<div class="stat-box"><div class="stat-value">{len(scored_df)}</div><div class="stat-label">Total Scanned</div></div>
<div class="stat-box"><div class="stat-value">{len(scored_df[scored_df['Rating'] == 'STRONG BUY'])}</div><div class="stat-label">Strong Buy</div></div>
<div class="stat-box"><div class="stat-value">{len(scored_df[scored_df['Rating'] == 'BUY'])}</div><div class="stat-label">Buy</div></div>
<div class="stat-box"><div class="stat-value">{len(scored_df[scored_df['Rating'] == 'HOLD'])}</div><div class="stat-label">Hold</div></div>
<div class="stat-box"><div class="stat-value">{len(scored_df[scored_df['Rating'] == 'SELL'])}</div><div class="stat-label">Sell</div></div>
</div>
</div>
<div class="card"><h2>🏆 Top 10 Picks</h2>
<table><tr><th>Rank</th><th>Symbol</th><th>Price</th><th>PE</th><th>Fund</th><th>Tech</th><th>Base</th><th>DCF</th><th>Final</th><th>Fundamental Model</th><th>Fundamental Components</th><th>Specialized Quality Gate</th><th>Data Anomalies</th><th>Transcript Summary</th><th>Transcript Technical Gate</th><th>News</th><th>Rating</th></tr>
{rows_html}
</table></div>
<div class="card"><h2>🔎 Reverse DCF</h2>
<table><tr><th>Rank</th><th>Symbol</th><th>Sector</th><th>CMP</th><th>Market Cap</th><th>FCF Yield</th><th>Expected Growth</th><th>Implied 5Y FCF CAGR</th><th>Implied Terminal Growth</th><th>Base Case Upside</th><th>Assessment</th><th>Rating</th></tr>
{dcf_rows_html}
</table>
<div style="font-size:12px;color:#777;margin-top:8px;">Reverse DCF solves the market-implied assumptions behind today's market cap using a 5-year DCF model. "Expected Growth" is a sector- and size-aware benchmark (not a single flat rate) used as the explicit growth assumption; "Implied 5Y FCF CAGR" is what the market is actually pricing in.</div>
</div>
<div class="card"><h2>📊 Score Distribution</h2>
<svg viewBox="0 0 {chart_w} 255" style="width:100%;max-height:280px;background:#f8f9ff;border-radius:8px;">
{bars}
</svg>
<div style="font-size:12px;color:#777;margin-top:6px;">Final score buckets (0–100) vs number of stocks</div>
</div>
<div class="card"><h2>💡 Advanced Features Active</h2>
<ul style="line-height:1.8;font-size:15px;color:#333;">
<li>✅ ADX (Wilder) + Stochastic RSI + ATR technical indicators</li>
<li>✅ Freshness-checked caching (prices 18h / fundamentals 7d)</li>
<li>✅ Liquidity pre-filter (penny &amp; illiquid names excluded)</li>
<li>✅ Data-completeness gate (thin-data stocks capped at HOLD)</li>
<li>✅ Backtest engine (run history tracking + score stats by rating)</li>
<li>✅ Word-boundary news sentiment for top picks (FII/DII feed = placeholder)</li>
<li>✅ Reverse DCF market-implied growth and terminal-growth analysis</li>
<li>✅ Interactive HTML dashboard with embedded SVG charts</li>
</ul>
</div>
<div class="footer">Generated by Stock Screener Advanced v2.2 | Not investment advice. Consult a SEBI-registered advisor.</div>
</body></html>"""

            with open(output_path, "w", encoding="utf-8") as f:
                f.write(html_content)
            logger.info(f"Interactive dashboard generated: {output_path}")
            return str(output_path)
        except Exception as e:
            logger.error(f"Dashboard generation failed: {e}")
            return None

class EmailReporter:
    def __init__(self, config):
        self.config = config

    def create_html_report(self, df, date_str):
        top = df.head(self.config.TOP_STOCKS_COUNT)
        summary = {
            "total": len(df),
            "strong_buy": len(df[df["Rating"] == "STRONG BUY"]),
            "buy": len(df[df["Rating"] == "BUY"]),
            "hold": len(df[df["Rating"] == "HOLD"]),
            "reduce": len(df[df["Rating"] == "REDUCE"]),
            "sell": len(df[df["Rating"] == "SELL"]),
        }
        rows = ""
        dcf_rows = ""
        for _, r in top.iterrows():
            css = "tag-" + str(r["Rating"]).lower().replace(" ", "-")
            wt = f"F {r.get('Dynamic_Weight_Fund', 0.7):.0%} / T {r.get('Dynamic_Weight_Tech', 0.3):.0%}"
            capped_star = "*" if r.get("Rating_Capped") else ""
            rating_gate = r.get("Rating_Cap_Reason") or r.get("Strong_Buy_Gate_Reason") or "passed"
            rows += (
                f"<tr><td>{int(r['Rank'])}</td><td><b>{r['Symbol']}</b></td>"
                f"<td>₹{r['Current_Price']:,.0f}</td>"
                f"<td>{fmt_f(r.get('PE_Ratio'), 1)}</td>"
                f"<td>{r['Fundamental_Score']:.0f}</td>"
                f"<td>{r['Technical_Score']:.0f}</td>"
                f"<td>{wt}</td>"
                f"<td>{fmt_f(r.get('ADX_14'), 1)}</td>"
                f"<td>{fmt_f(r.get('RSI_14'), 1)}</td>"
                f"<td>{fmt_f(r.get('StochRSI_14'), 1)}</td>"
                f"<td>{fmt_f(r.get('ATR_14'), 2)}</td>"
                f"<td>{fmt_pct(r.get('Revenue_Growth'), 1)}</td>"
                f"<td>{fmt_pct(r.get('Earnings_Growth'), 1)}</td>"
                f"<td>{fmt_f(r.get('Pct_Change_3M'), 1)}%</td>"
                f"<td>{fmt_f(r.get('MA50_Slope_Pct'), 1)}%</td>"
                f"<td>{fmt_f(r.get('ADX_Plus_DI'), 1)} / {fmt_f(r.get('ADX_Minus_DI'), 1)}</td>"
                f"<td>{rating_gate}</td>"
                f"<td>{r.get('Fundamental_Model', 'Generic Fundamental Model')}</td>"
                f"<td>{r.get('Fund_Component_Summary', '-')}</td>"
                f"<td>{r.get('Specialized_Quality_Gate_Reason', 'passed')}</td>"
                f"<td>{r.get('Fundamental_Anomaly_Reason') or 'none'}</td>"
                f"<td>{r['Combined_Score']:.1f}</td>"
                f"<td>{fmt_f(r.get('DCF_Valuation_Score'), 1)}</td>"
                f"<td><b>{r.get('Final_Score', r['Combined_Score']):.1f}</b></td>"
                f"<td>{r.get('Transcript_Summary', 'No transcript')}</td>"
                f"<td>{r.get('Transcript_Technical_Gate', 'No transcript')}</td>"
                f"<td>{r.get('Transcript_Quality_Gate', 'No transcript')}</td>"
                f"<td class='{css}'>{r['Rating']}{capped_star}</td></tr>"
            )
            dcf_rows += (
                f"<tr><td>{int(r['Rank'])}</td><td><b>{r['Symbol']}</b></td>"
                f"<td>{r.get('DCF_Sector', 'Unknown')}</td>"
                f"<td>\u20b9{r['Current_Price']:,.0f}</td>"
                f"<td>{fmt_cr(r.get('DCF_Market_Cap'), 0)}</td>"
                f"<td>{fmt_cr(r.get('DCF_Base_FCF'), 0)}</td>"
                f"<td>{fmt_pct(r.get('DCF_FCF_Yield'), 1)}</td>"
                f"<td>{fmt_pct(r.get('DCF_Expected_Growth'), 1)}</td>"
                f"<td>{fmt_pct(r.get('DCF_Implied_FCF_CAGR'), 1)}</td>"
                f"<td>{fmt_pct(r.get('DCF_Implied_Terminal_Growth'), 1)}</td>"
                f"<td>{fmt_pct(r.get('DCF_Base_Case_Upside'), 1)}</td>"
                f"<td>{r.get('DCF_Assessment', '-')}</td>"
                f"<td class='{css}'>{r['Rating']}{capped_star}</td></tr>"
            )

        html = f"""<html><head><style>
body{{font-family:Arial,sans-serif;margin:20px;background:#f5f7fa;}}
.card{{background:white;border-radius:12px;padding:25px;margin-bottom:20px;box-shadow:0 4px 18px rgba(0,0,0,0.06);}}
h1{{color:#1a237e;margin:0;font-size:26px;}}
h2{{color:#303f9f;border-bottom:3px solid #e8eaf6;padding-bottom:10px;margin-top:0;}}
table{{border-collapse:collapse;width:100%;font-size:11px;}}
th{{background:#1a237e;color:white;padding:10px;text-align:center;}}
td{{padding:9px;border-bottom:1px solid #ddd;text-align:center;}}
.tag-strong-buy{{color:#1b5e20;font-weight:bold;}}
.tag-buy{{color:#2e7d32;font-weight:bold;}}
.tag-hold{{color:#f57f17;}}
.tag-reduce{{color:#e65100;}}
.tag-sell{{color:#b71c1c;font-weight:bold;}}
</style></head><body>
<div class="card"><h1>📊 Advanced Stock Screener Report</h1>
<p><b>Date:</b> {date_str} &nbsp;|&nbsp; <b>Features:</b> ADX / StochRSI / ATR, Freshness-checked caches, Liquidity filter, Data-quality gate, Backtest log, News sentiment, Reverse DCF</p></div>
<div class="card"><h2>Market Summary</h2>
<p><b>Total:</b> {summary['total']} |
<span class="tag-strong-buy">Strong Buy: {summary['strong_buy']}</span> |
<span class="tag-buy">Buy: {summary['buy']}</span> |
<span class="tag-hold">Hold: {summary['hold']}</span> |
<span class="tag-reduce">Reduce: {summary['reduce']}</span> |
<span class="tag-sell">Sell: {summary['sell']}</span></p></div>
<div class="card"><h2>Top {self.config.TOP_STOCKS_COUNT} Stocks</h2>
<table><tr><th>Rank</th><th>Symbol</th><th>Price (INR)</th><th>PE</th><th>Fund</th><th>Tech</th><th>Weights</th><th>ADX</th><th>RSI (14)</th><th>StochRSI %K (14,14,3)</th><th>ATR</th><th>Rev Gr</th><th>Earn Gr</th><th>3M</th><th>MA50 Slope</th><th>+DI / -DI</th><th>Rating Gate</th><th>Fundamental Model</th><th>Fundamental Components</th><th>Specialized Quality Gate</th><th>Data Anomalies</th><th>Base</th><th>DCF</th><th>Final</th><th>Transcript Summary</th><th>Transcript Technical Gate</th><th>Transcript Quality Gate</th><th>Rating</th></tr>
{rows}
</table></div>
<div class="card"><h2>Reverse DCF: Market-Implied Expectations</h2>
<p>Model uses a 5-year explicit forecast and a {fmt_pct(self.config.REVERSE_DCF_DISCOUNT_RATE)} required equity return. Yahoo's operating-cash-flow-less-capex field is treated as an equity cash-flow proxy, not mislabeled as FCFF. "Expected Growth" is a sector- and size-aware benchmark used as the explicit growth assumption; {fmt_pct(self.config.REVERSE_DCF_TERMINAL_GROWTH)} fixed terminal growth is used when solving for implied FCF CAGR.</p>
<table><tr><th>Rank</th><th>Symbol</th><th>Sector</th><th>CMP</th><th>Market Cap</th><th>Base FCF</th><th>FCF Yield</th><th>Expected Growth</th><th>Implied 5Y FCF CAGR</th><th>Implied Terminal Growth</th><th>Base Case Upside</th><th>Assessment</th><th>Rating</th></tr>
{dcf_rows}
</table></div>
<div class="card"><p><b>Note:</b> Base = weighted Fundamental and Technical scores. Final = Base blended with DCF only when reported cash flow produces a valid proxy result; otherwise Final equals Base. Reverse DCF compares market cap to a discounted equity cash-flow proxy and solves for assumptions implied by today's price. * = rating capped at HOLD by a data-quality, model, or price-trend gate. Not investment advice — consult a SEBI-registered advisor.</p></div>
</body></html>"""
        return html

    def create_pdf_report(self, df, date_str):
        """Render the same Top-N + Reverse DCF data shown in the email as a
        formatted PDF, using reportlab (pure Python, no OS-level dependencies).
        Returns the output path, or None if reportlab isn't installed or the
        PDF could not be built."""
        if not REPORTLAB_AVAILABLE:
            logger.warning("PDF report skipped: reportlab is not installed (add it to requirements.txt).")
            return None
        try:
            top = df.head(self.config.TOP_STOCKS_COUNT)
            pdf_path = self.config.OUTPUT_DIR / f"stock_report_{date_str.replace('-', '')}.pdf"

            styles = getSampleStyleSheet()
            story = [
                Paragraph("Advanced Stock Screener Report", styles["Title"]),
                Paragraph(f"Date: {date_str}", styles["Normal"]),
                Spacer(1, 0.4 * cm),
            ]

            top_header = ["Rank", "Symbol", "CMP", "PE", "Fund", "Tech", "Model", "Fund Evidence", "Quality Gate", "Base", "DCF", "Final", "Transcript", "Technical Gate", "Rating"]
            top_rows = [top_header]
            for _, r in top.iterrows():
                top_rows.append([
                    int(r["Rank"]),
                    r["Symbol"],
                    f"\u20b9{r['Current_Price']:,.0f}",
                    fmt_f(r.get("PE_Ratio"), 1),
                    f"{r['Fundamental_Score']:.0f}",
                    f"{r['Technical_Score']:.0f}",
                    r.get("Fundamental_Model", "Generic Fundamental Model"),
                    r.get("Fund_Component_Summary", "-"),
                    r.get("Specialized_Quality_Gate_Reason", "passed"),
                    f"{r['Combined_Score']:.1f}",
                    fmt_f(r.get("DCF_Valuation_Score"), 1),
                    f"{r.get('Final_Score', r['Combined_Score']):.1f}",
                    r.get("Transcript_Summary", "No transcript"),
                    r.get("Transcript_Technical_Gate", "No transcript"),
                    r["Rating"],
                ])
            story.append(Paragraph(f"Top {self.config.TOP_STOCKS_COUNT} Stocks", styles["Heading2"]))
            story.append(self._pdf_table(top_rows, [1.0, 1.8, 1.4, 1.0, 1.0, 1.0, 2.4, 2.4, 2.5, 1.0, 1.0, 1.0, 2.4, 2.5, 1.4]))
            story.append(Spacer(1, 0.6 * cm))

            dcf_header = [
                "Rank", "Symbol", "Sector", "CMP", "Mkt Cap", "FCF Yield",
                "Exp Growth", "Impl 5Y CAGR", "Impl Term Growth", "Upside", "Assessment", "Rating",
            ]
            dcf_rows = [dcf_header]
            for _, r in top.iterrows():
                dcf_rows.append([
                    int(r["Rank"]),
                    r["Symbol"],
                    r.get("DCF_Sector", "Unknown"),
                    f"\u20b9{r['Current_Price']:,.0f}",
                    fmt_cr(r.get("DCF_Market_Cap"), 0),
                    fmt_pct(r.get("DCF_FCF_Yield"), 1),
                    fmt_pct(r.get("DCF_Expected_Growth"), 1),
                    fmt_pct(r.get("DCF_Implied_FCF_CAGR"), 1),
                    fmt_pct(r.get("DCF_Implied_Terminal_Growth"), 1),
                    fmt_pct(r.get("DCF_Base_Case_Upside"), 1),
                    r.get("DCF_Assessment", "-"),
                    r["Rating"],
                ])
            story.append(Paragraph("Reverse DCF: Market-Implied Expectations", styles["Heading2"]))
            story.append(self._pdf_table(
                dcf_rows,
                [1.1, 2.0, 2.2, 1.8, 2.0, 1.8, 1.8, 2.0, 2.1, 1.6, 2.2, 1.8],
            ))
            story.append(Spacer(1, 0.4 * cm))
            story.append(Paragraph(
                "Not investment advice - consult a SEBI-registered advisor.",
                styles["Italic"],
            ))

            doc = SimpleDocTemplate(
                str(pdf_path),
                pagesize=landscape(A4),
                topMargin=1.2 * cm, bottomMargin=1.2 * cm, leftMargin=1.2 * cm, rightMargin=1.2 * cm,
            )
            doc.build(story)
            return pdf_path
        except Exception as e:
            logger.warning(f"PDF report generation failed: {e}")
            return None

    @staticmethod
    def _pdf_table(rows, col_widths_cm):
        table = Table(rows, colWidths=[w * cm for w in col_widths_cm], repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a237e")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 7),
            ("FONTSIZE", (0, 0), (-1, 0), 7.5),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f7fa")]),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        return table

    def _build_message(self, html_content, date_str, csv_path, pdf_path=None):
        recipients = [addr.strip() for addr in self.config.EMAIL_RECEIVER.split(",") if addr.strip()]
        msg = MIMEMultipart()
        msg["From"] = self.config.EMAIL_SENDER
        msg["To"] = ", ".join(recipients)
        msg["Subject"] = f"{self.config.EMAIL_SUBJECT_PREFIX} - {date_str}"
        msg.attach(MIMEText(html_content, "html"))
        if csv_path and os.path.exists(csv_path) and self.config.ATTACH_CSV:
            with open(csv_path, "rb") as f:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(f.read())
                encoders.encode_base64(part)
                part.add_header("Content-Disposition", f"attachment; filename={os.path.basename(csv_path)}")
                msg.attach(part)
        if pdf_path and os.path.exists(pdf_path) and self.config.ATTACH_PDF:
            with open(pdf_path, "rb") as f:
                part = MIMEBase("application", "pdf")
                part.set_payload(f.read())
                encoders.encode_base64(part)
                part.add_header("Content-Disposition", f"attachment; filename={os.path.basename(pdf_path)}")
                msg.attach(part)
        return msg

    def _build_brevo_payload(self, html_content, date_str, csv_path, pdf_path=None):
        payload = {
            "sender": {
                "email": self.config.EMAIL_SENDER,
                "name": self.config.EMAIL_SUBJECT_PREFIX,
            },
            "to": [{"email": email.strip()} for email in self.config.EMAIL_RECEIVER.split(",") if email.strip()],
            "subject": f"{self.config.EMAIL_SUBJECT_PREFIX} - {date_str}",
            "htmlContent": html_content,
        }
        attachments = []
        if csv_path and os.path.exists(csv_path) and self.config.ATTACH_CSV:
            with open(csv_path, "rb") as f:
                attachments.append({
                    "name": os.path.basename(csv_path),
                    "content": base64.b64encode(f.read()).decode("ascii"),
                })
        if pdf_path and os.path.exists(pdf_path) and self.config.ATTACH_PDF:
            with open(pdf_path, "rb") as f:
                attachments.append({
                    "name": os.path.basename(pdf_path),
                    "content": base64.b64encode(f.read()).decode("ascii"),
                })
        if attachments:
            payload["attachment"] = attachments
        return payload

    def _send_email_brevo(self, html_content, date_str, csv_path=None, pdf_path=None):
        if not self.config.BREVO_API_KEY:
            logger.error("Brevo email not sent: BREVO_API_KEY is required when EMAIL_DELIVERY_METHOD=BREVO.")
            return False

        payload = self._build_brevo_payload(html_content, date_str, csv_path, pdf_path)
        if not payload["to"]:
            logger.error("Brevo email not sent: EMAIL_RECEIVER must contain at least one email address.")
            return False

        try:
            response = requests.post(
                self.config.BREVO_API_URL,
                headers={
                    "accept": "application/json",
                    "api-key": self.config.BREVO_API_KEY,
                    "content-type": "application/json",
                },
                json=payload,
                timeout=self.config.SMTP_TIMEOUT_SECONDS,
            )
        except requests.RequestException as e:
            logger.error(f"Brevo email network/API request failed: {e}")
            return False

        if 200 <= response.status_code < 300:
            logger.info(f"Email sent to {self.config.EMAIL_RECEIVER} via Brevo HTTP API")
            return True

        logger.error(f"Brevo email failed: HTTP {response.status_code} {response.text[:500]}")
        return False

    def _get_gmail_api_access_token(self):
        missing = [
            name for name in ("GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET", "GMAIL_REFRESH_TOKEN")
            if not getattr(self.config, name)
        ]
        if missing:
            logger.error(f"Gmail API email not sent: missing {', '.join(missing)}.")
            return None

        try:
            response = requests.post(
                self.config.GMAIL_TOKEN_URL,
                data={
                    "client_id": self.config.GMAIL_CLIENT_ID,
                    "client_secret": self.config.GMAIL_CLIENT_SECRET,
                    "refresh_token": self.config.GMAIL_REFRESH_TOKEN,
                    "grant_type": "refresh_token",
                },
                timeout=self.config.SMTP_TIMEOUT_SECONDS,
            )
        except requests.RequestException as e:
            logger.error(f"Gmail API token refresh failed: {e}")
            return None

        if 200 <= response.status_code < 300:
            token = response.json().get("access_token")
            if token:
                return token
            logger.error(f"Gmail API token refresh response did not include access_token: {response.text[:500]}")
            return None

        logger.error(f"Gmail API token refresh failed: HTTP {response.status_code} {response.text[:500]}")
        return None

    def _send_email_gmail_api(self, html_content, date_str, csv_path=None, pdf_path=None):
        token = self._get_gmail_api_access_token()
        if not token:
            return False

        msg = self._build_message(html_content, date_str, csv_path, pdf_path)
        raw_message = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
        try:
            response = requests.post(
                self.config.GMAIL_SEND_URL,
                headers={
                    "authorization": f"Bearer {token}",
                    "content-type": "application/json",
                },
                json={"raw": raw_message},
                timeout=self.config.SMTP_TIMEOUT_SECONDS,
            )
        except requests.RequestException as e:
            logger.error(f"Gmail API send request failed: {e}")
            return False

        if 200 <= response.status_code < 300:
            message_id = response.json().get("id", "unknown")
            logger.info(f"Email sent to {self.config.EMAIL_RECEIVER} via Gmail API; message id={message_id}")
            return True

        logger.error(f"Gmail API send failed: HTTP {response.status_code} {response.text[:500]}")
        return False

    def send_email(self, html_content, date_str, csv_path=None, pdf_path=None):
        if not self.config.EMAIL_ENABLED:
            logger.info("Email disabled; set EMAIL_ENABLED=True in config_local.py to send")
            return False
        if not self.config.EMAIL_SENDER or not self.config.EMAIL_RECEIVER:
            logger.error("Email not sent: EMAIL_SENDER and EMAIL_RECEIVER are required.")
            return False
        if self.config.EMAIL_DELIVERY_METHOD == "BREVO":
            return self._send_email_brevo(html_content, date_str, csv_path, pdf_path)
        if self.config.EMAIL_DELIVERY_METHOD == "GMAIL_API":
            return self._send_email_gmail_api(html_content, date_str, csv_path, pdf_path)
        if self.config.EMAIL_DELIVERY_METHOD != "SMTP":
            logger.error(
                f"Unsupported EMAIL_DELIVERY_METHOD={self.config.EMAIL_DELIVERY_METHOD!r}; "
                "use SMTP, BREVO, or GMAIL_API."
            )
            return False
        if not self.config.EMAIL_PASSWORD:
            logger.error(
                "SMTP email not sent: EMAIL_PASSWORD is required. "
                "For Gmail, use an app password via environment variable or config_local.py."
            )
            return False
        msg = self._build_message(html_content, date_str, csv_path, pdf_path)
        # Try port 465 (SSL) first — works on most cloud hosts including Railway.
        # Fall back to port 587 (STARTTLS) if 465 is unreachable.
        configured_port = self.config.SMTP_PORT
        fallback_port = 587 if configured_port == 465 else 465
        attempts = [
            (configured_port, "SSL" if configured_port == 465 else "STARTTLS"),
            (fallback_port, "SSL" if fallback_port == 465 else "STARTTLS"),
        ]
        smtp_ssl_class = IPv4SMTP_SSL if self.config.SMTP_FORCE_IPV4 else smtplib.SMTP_SSL
        smtp_class = IPv4SMTP if self.config.SMTP_FORCE_IPV4 else smtplib.SMTP
        for port, mode in attempts:
            try:
                if mode == "SSL":
                    with smtp_ssl_class(self.config.SMTP_SERVER, port, timeout=self.config.SMTP_TIMEOUT_SECONDS) as server:
                        server.login(self.config.EMAIL_SENDER, self.config.EMAIL_PASSWORD)
                        server.send_message(msg)
                else:
                    with smtp_class(self.config.SMTP_SERVER, port, timeout=self.config.SMTP_TIMEOUT_SECONDS) as server:
                        server.ehlo()
                        server.starttls()
                        server.ehlo()
                        server.login(self.config.EMAIL_SENDER, self.config.EMAIL_PASSWORD)
                        server.send_message(msg)
                logger.info(f"Email sent to {self.config.EMAIL_RECEIVER} via port {port} ({mode})")
                return True
            except smtplib.SMTPAuthenticationError as e:
                logger.error(
                    f"Email authentication failed on port {port} ({mode}). "
                    "Your Gmail app password, sender address, or Google account settings are invalid. "
                    f"SMTP response: {e.smtp_code} {e.smtp_error!r}"
                )
                return False
            except OSError as e:
                logger.warning(
                    f"Email network attempt port {port} ({mode}) failed: {e}. "
                    f"SMTP_FORCE_IPV4={self.config.SMTP_FORCE_IPV4}"
                )
            except Exception as e:
                logger.warning(f"Email attempt port {port} ({mode}) failed: {e}")
        logger.error(
            "Email failed on all SMTP attempts. If the error is network-related, check Railway outbound "
            "connectivity/firewall; if it says authentication failed, regenerate the Gmail app password."
        )
        return False

# =====================================================
# WHATSAPP REPORTER (self-contained: Twilio / CallMeBot / PyWhatKit)
# =====================================================
class WhatsAppReporter:
    def __init__(self, config):
        self.config = config

    def create_whatsapp_message(self, df, date_str):
        top = df.head(self.config.WHATSAPP_TOP_COUNT)
        msg = f"*ADVANCED STOCK REPORT {date_str}*\n"
        msg += (
            f"Total: {len(df)} | STRONG BUY: {len(df[df['Rating'] == 'STRONG BUY'])} "
            f"| BUY: {len(df[df['Rating'] == 'BUY'])}\n"
            f"Features: ADX/Stoch/ATR, Smart caches, Liquidity filter, Dashboard, News\n\n"
        )
        for _, r in top.iterrows():
            msg += (
                f"{int(r['Rank'])}. {r['Symbol']} ₹{r['Current_Price']:,.0f} "
                f"Score:{r.get('Final_Score', r['Combined_Score']):.0f} {r['Rating']} ADX:{fmt_f(r.get('ADX_14'), 0)}\n"
            )
        msg += "\nDisclaimer: Not investment advice. Consult a SEBI-registered advisor."
        return msg

    def send_via_twilio(self, message):
        from twilio.rest import Client
        client = Client(self.config.TWILIO_ACCOUNT_SID, self.config.TWILIO_AUTH_TOKEN)
        to = self.config.WHATSAPP_RECEIVER
        if not to.startswith("whatsapp:"):
            to = f"whatsapp:{to}"
        client.messages.create(body=message, from_=self.config.TWILIO_WHATSAPP_NUMBER, to=to)
        logger.info("WhatsApp sent via Twilio")

    def send_via_callmebot(self, message):
        resp = requests.get(
            "https://api.callmebot.com/whatsapp.php",
            params={
                "phone": self.config.CALLMEBOT_PHONE,
                "text": message,
                "apikey": self.config.CALLMEBOT_API_KEY,
            },
            timeout=15,
        )
        if resp.status_code == 200:
            logger.info("WhatsApp sent via CallMeBot")
        else:
            logger.warning(f"CallMeBot returned HTTP {resp.status_code}")

    def send_via_pywhatkit(self, message):
        # NOTE: requires a desktop with a browser logged into WhatsApp Web;
        # will NOT work on a headless server. Prefer TWILIO or CALLMEBOT there.
        import pywhatkit
        now = datetime.now()
        send_min = now.minute + 2
        send_hour = now.hour
        if send_min >= 60:
            send_min -= 60
            send_hour = (send_hour + 1) % 24
        pywhatkit.sendwhatmsg(
            self.config.PYWHATKIT_PHONE, message,
            send_hour, send_min, wait_time=self.config.PYWHATKIT_WAIT_TIME,
        )
        logger.info("WhatsApp scheduled via PyWhatKit")

    def send_whatsapp(self, df, date_str):
        if not self.config.WHATSAPP_ENABLED:
            return
        message = self.create_whatsapp_message(df, date_str)
        method = str(self.config.WHATSAPP_METHOD).upper()
        if method == "TWILIO":
            self.send_via_twilio(message)
        elif method == "CALLMEBOT":
            self.send_via_callmebot(message)
        elif method == "PYWHATKIT":
            self.send_via_pywhatkit(message)
        else:
            logger.warning(f"Unknown WHATSAPP_METHOD: {method}")
