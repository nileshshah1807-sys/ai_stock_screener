import { NextResponse, type NextRequest } from "next/server";

import { getViewer } from "@/lib/auth";
import { parseFilters } from "@/lib/filters";
import { getExportRows, getLatestRun } from "@/lib/queries";
import type { SnapshotRow } from "@/lib/types";

export const dynamic = "force-dynamic";

const COLUMNS: Array<[keyof SnapshotRow, string]> = [
  ["investment_rank", "Investment_Rank"],
  ["actionable_rank", "Actionable_Rank"],
  ["symbol", "Symbol"],
  ["company", "Company"],
  ["sector", "Sector"],
  ["rating", "Rating"],
  ["decision_score", "Decision_Score"],
  ["evidence_score", "Evidence_Score"],
  ["final_score", "Final_Score"],
  ["fundamental_score", "Fundamental_Score"],
  ["technical_score", "Technical_Score"],
  ["fund_fields_present", "Fund_Fields_Present"],
  ["fund_fields_expected", "Fund_Fields_Expected"],
  ["buy_eligible", "Buy_Eligible"],
  ["strong_buy_eligible", "Strong_Buy_Eligible"],
  ["rating_capped", "Rating_Capped"],
  ["rating_cap_reason", "Rating_Cap_Reason"],
  ["gate_failures", "Gate_Failures"],
  ["current_price", "Current_Price"],
  ["pct_change_1m", "Pct_Change_1M"],
  ["pct_change_3m", "Pct_Change_3M"],
  ["market_cap", "Market_Cap"],
  ["pe_ratio", "PE_Ratio"],
  ["pb_ratio", "PB_Ratio"],
  ["roe", "ROE"],
  ["dcf_status", "DCF_Status"],
  ["dcf_base_case_upside", "DCF_Base_Case_Upside"],
  ["transcript_status", "Transcript_Status"],
  ["transcript_scoring_eligible", "Transcript_Scoring_Eligible"],
  ["red_flag_status", "Red_Flag_Status"],
  ["red_flag_severity", "Red_Flag_Severity"],
  ["liquidity_grade", "Liquidity_Grade"],
  ["portfolio_actionable", "Portfolio_Actionable"],
  ["median_turnover_20d_inr", "Median_Turnover_20D_INR"],
];

/**
 * RFC 4180 escaping.
 *
 * Company names in this universe contain commas and the occasional quote, and
 * gate-failure strings contain both. A naive join would shift every later
 * column on those rows.
 */
function csvCell(value: unknown): string {
  if (value === null || value === undefined) return "";
  const text = String(value);
  if (/[",\r\n]/.test(text)) {
    return `"${text.replace(/"/g, '""')}"`;
  }
  return text;
}

export async function GET(request: NextRequest) {
  // Route handlers are not covered by the page-level check, and Proxy only
  // verifies that a session exists. Re-check membership here.
  const viewer = await getViewer();
  if (!viewer) {
    return NextResponse.json({ error: "Not authorised" }, { status: 403 });
  }

  const run = await getLatestRun();
  if (!run) {
    return NextResponse.json({ error: "No run published" }, { status: 404 });
  }

  const filters = parseFilters(
    Object.fromEntries(request.nextUrl.searchParams.entries()),
  );
  // Multi-valued filters need every occurrence, which Object.fromEntries drops.
  filters.rating = request.nextUrl.searchParams.getAll("rating");
  filters.sector = request.nextUrl.searchParams.getAll("sector");

  const rows = await getExportRows(run.run_date, filters);

  const header = COLUMNS.map(([, label]) => label).join(",");
  const body = rows
    .map((row) => COLUMNS.map(([key]) => csvCell(row[key])).join(","))
    .join("\r\n");

  // The export reflects a filtered view of one dated run, so the filename
  // records which run it came from rather than the download date.
  const filename = `screener_${run.run_date.replace(/-/g, "")}_filtered.csv`;

  return new NextResponse(`${header}\r\n${body}\r\n`, {
    headers: {
      "Content-Type": "text/csv; charset=utf-8",
      "Content-Disposition": `attachment; filename="${filename}"`,
      "Cache-Control": "no-store",
    },
  });
}
