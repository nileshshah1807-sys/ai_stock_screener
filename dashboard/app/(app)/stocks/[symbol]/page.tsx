import { notFound } from "next/navigation";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";

import { CompanyLogo } from "@/components/company-logo";
import { RatingBadge } from "@/components/rating-badge";
import { ZoomIn } from "@/components/motion";
import { DecisionScore } from "@/components/stock/decision-score";
import { FactorBlocks } from "@/components/stock/factor-blocks";
import { FieldList, Panel, type Field } from "@/components/stock/field-list";
import { HistoryChart } from "@/components/stock/history-chart";
import { PayloadExplorer } from "@/components/stock/payload-explorer";
import { ScoreWaterfall } from "@/components/stock/score-waterfall";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";
import {
  formatDate,
  formatINR,
  formatINRCompact,
  formatNumber,
  formatPercent,
  formatRatioAsPercent,
  formatScore,
  MISSING,
} from "@/lib/format";
import {
  dataQuality,
  dcfStatus,
  eligibilityClass,
  marketRegime,
  primaryGate,
  stabilityStatus,
} from "@/lib/labels";
import { getLatestRun, getStock, getStockHistory } from "@/lib/queries";

export const dynamic = "force-dynamic";

function pick(payload: Record<string, unknown>, key: string): unknown {
  const value = payload?.[key];
  return value === "" ? null : value;
}

function text(payload: Record<string, unknown>, key: string): string {
  const value = pick(payload, key);
  return value === null || value === undefined ? MISSING : String(value);
}

function numeric(payload: Record<string, unknown>, key: string): number | null {
  const value = pick(payload, key);
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function reasons(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.map(String).map((item) => item.trim()).filter(Boolean);
  }
  if (typeof value !== "string" || !value.trim()) return [];
  try {
    const parsed: unknown = JSON.parse(value);
    if (Array.isArray(parsed)) {
      return parsed.map(String).map((item) => item.trim()).filter(Boolean);
    }
  } catch {
    // Older exports used a semicolon-delimited scalar. It remains authoritative.
  }
  return value.split(";").map((item) => item.trim()).filter(Boolean);
}

export async function generateMetadata({
  params,
}: PageProps<"/stocks/[symbol]">) {
  const { symbol } = await params;
  return { title: symbol.toUpperCase() };
}

export default async function StockPage({ params }: PageProps<"/stocks/[symbol]">) {
  // Next.js 16: params is a Promise.
  const { symbol } = await params;

  const run = await getLatestRun();
  if (!run) notFound();

  const [row, history] = await Promise.all([
    getStock(run.run_date, symbol),
    getStockHistory(symbol),
  ]);

  if (!row) notFound();

  const payload = row.payload ?? {};
  const factorModel = row.factor_model_applied === true;
  const buyFundamentalCoverageMargin = numeric(
    payload,
    "Buy_Fundamental_Coverage_Margin",
  );
  const buyTechnicalCoverageMargin = numeric(
    payload,
    "Buy_Technical_Coverage_Margin",
  );
  const gate = primaryGate(row.primary_gate);
  const regime = marketRegime(row.market_regime);
  const eligibility = eligibilityClass(row.eligibility_class);
  const capApplied =
    row.decision_cap_applied === true || row.rating_capped === true;
  const capReasons = reasons(
    row.decision_cap_reason ??
      row.rating_cap_reason ??
      pick(payload, "Gate_Failures"),
  );
  const evidenceScore = row.evidence_score;
  const decisionScore = row.decision_score ?? row.final_score;
  const pointsRemoved =
    evidenceScore !== null && decisionScore !== null
      ? Math.max(0, evidenceScore - decisionScore)
      : null;

  const policyFields: Field[] = [
    {
      label: "Research rating",
      value: row.research_rating ?? row.evidence_rating ?? MISSING,
      hint: "The rating implied by research evidence before policy eligibility checks.",
    },
    {
      label: "Policy-eligible rating",
      value: row.policy_eligible_rating ?? row.decision_rating ?? MISSING,
      tone: capApplied ? "caution" : "default",
      hint: "The highest rating allowed after applying this row's observed gates.",
    },
    {
      label: "Evidence score",
      value: formatScore(evidenceScore),
      hint: "Score entering the policy stage.",
    },
    {
      label: "Decision ceiling",
      value: formatScore(row.decision_score_ceiling),
      tone: capApplied ? "caution" : "muted",
      hint: "Maximum score permitted by the active gate combination.",
    },
    {
      label: "Published decision",
      value: formatScore(decisionScore),
    },
    {
      label: "Points removed",
      value:
        pointsRemoved !== null && pointsRemoved > 0.005
          ? `-${formatNumber(pointsRemoved, 2)}`
          : "0.00",
      tone: pointsRemoved !== null && pointsRemoved > 0.005 ? "negative" : "muted",
    },
    {
      label: "Primary constraint",
      value: gate.label,
      tone: capApplied ? "caution" : "muted",
      hint: gate.meaning || undefined,
    },
    {
      label: "Eligibility class",
      value: eligibility.label,
      hint: eligibility.meaning || undefined,
    },
  ];

  const gateFields: Field[] = [
    {
      label: "Published rating",
      value: <RatingBadge rating={row.rating} size="md" />,
    },
    {
      label: "BUY gates",
      value: row.buy_eligible ? "Passed" : "Failed",
      tone: row.buy_eligible ? "positive" : "caution",
      hint: row.buy_eligible ? undefined : text(payload, "Buy_Gate_Reason"),
    },
    {
      label: "STRONG BUY gates",
      value: row.strong_buy_eligible ? "Passed" : "Failed",
      tone: row.strong_buy_eligible ? "positive" : "muted",
      hint: row.strong_buy_eligible
        ? undefined
        : text(payload, "Strong_Buy_Gate_Reason"),
    },
    {
      label: "Rating capped",
      value: row.rating_capped ? "Yes" : "No",
      tone: row.rating_capped ? "caution" : "muted",
      hint: row.rating_capped ? (row.rating_cap_reason ?? undefined) : undefined,
    },
    {
      label: "Trend confirmed",
      value: row.trend_confirmed ? "Yes" : "No",
      tone: row.trend_confirmed ? "positive" : "caution",
      hint: "BUY requires a constructive medium-term chart, not valuation alone.",
    },
    {
      label: "Data quality",
      value: dataQuality(row.data_quality).label,
      hint: dataQuality(row.data_quality).meaning || undefined,
    },
    {
      label: "Gate failures",
      value: row.gate_failure_count ?? 0,
      tone: (row.gate_failure_count ?? 0) > 0 ? "caution" : "muted",
      hint: row.gate_failures ?? undefined,
    },
    {
      label: "Stability",
      value: stabilityStatus(row.decision_stability_status).label,
      hint: stabilityStatus(row.decision_stability_status).meaning || undefined,
    },
  ];

  const coverageFields: Field[] = [
    {
      label: "Factor coverage",
      value: formatRatioAsPercent(row.factor_coverage, 0),
    },
    {
      label: "Quality coverage",
      value: formatRatioAsPercent(row.quality_coverage, 0),
    },
    {
      label: "Growth coverage",
      value: formatRatioAsPercent(row.growth_coverage, 0),
    },
    {
      label: "Value coverage",
      value: formatRatioAsPercent(row.value_coverage, 0),
    },
    {
      label: "Momentum coverage",
      value: formatRatioAsPercent(row.momentum_coverage, 0),
    },
    {
      label: "Risk coverage",
      value: formatRatioAsPercent(row.risk_coverage, 0),
    },
    {
      label: "Fundamental coverage",
      value: formatRatioAsPercent(row.fundamental_coverage, 0),
      hint:
        buyFundamentalCoverageMargin === null
          ? undefined
          : `BUY-floor margin ${formatRatioAsPercent(buyFundamentalCoverageMargin, 1, true)}.`,
    },
    {
      label: "Technical coverage",
      value: formatRatioAsPercent(row.technical_coverage, 0),
      hint:
        buyTechnicalCoverageMargin === null
          ? undefined
          : `BUY-floor margin ${formatRatioAsPercent(buyTechnicalCoverageMargin, 1, true)}.`,
    },
    {
      label: "Price session aligned",
      value:
        row.price_bar_aligned === null
          ? MISSING
          : row.price_bar_aligned
            ? "Yes"
            : "No",
      tone:
        row.price_bar_aligned === null
          ? "muted"
          : row.price_bar_aligned
            ? "positive"
            : "caution",
      hint: row.price_bar_aligned === true
        ? "Technical evidence uses the run's expected completed session."
        : row.price_bar_aligned === false
          ? "An older vendor bar is retained for audit but cannot support BUY conviction."
          : undefined,
    },
    {
      label: "Market regime",
      value: regime.label,
      hint: regime.meaning || undefined,
    },
  ];

  const fundamentalFields: Field[] = [
    { label: "Model", value: row.fundamental_model ?? MISSING },
    {
      label: "Coverage",
      value: formatRatioAsPercent(row.fundamental_coverage, 0),
      tone:
        factorModel
          ? buyFundamentalCoverageMargin !== null &&
            buyFundamentalCoverageMargin < 0
            ? "caution"
            : "default"
          : (row.fundamental_coverage ?? 1) < 0.55
            ? "caution"
            : "default",
      hint: factorModel
        ? `${row.fund_fields_present ?? MISSING} of ${row.fund_fields_expected ?? MISSING} expected fields. Model 5.0 applies the coverage floors configured for this run.`
        : `${row.fund_fields_present ?? MISSING} of ${row.fund_fields_expected ?? MISSING} fields the selected sector model expects. BUY needs 55%, STRONG BUY 75%.`,
    },
    { label: "Fundamental score", value: formatScore(row.fundamental_score) },
    { label: "Valuation pts", value: text(payload, "Fund_Valuation_Points") },
    { label: "Quality pts", value: text(payload, "Fund_Quality_Points") },
    { label: "Growth pts", value: text(payload, "Fund_Growth_Points") },
    { label: "Income pts", value: text(payload, "Fund_Income_Points") },
    { label: "PE", value: formatNumber(row.pe_ratio, 1) },
    { label: "PB", value: formatNumber(row.pb_ratio, 2) },
    { label: "ROE", value: formatRatioAsPercent(row.roe) },
    { label: "Debt / equity", value: formatNumber(row.debt_to_equity, 2) },
    { label: "Revenue growth", value: formatRatioAsPercent(row.revenue_growth, 1, true) },
    { label: "Earnings growth", value: formatRatioAsPercent(row.earnings_growth, 1, true) },
    { label: "Market cap", value: formatINRCompact(row.market_cap) },
  ];

  const technicalFields: Field[] = [
    { label: "Technical score", value: formatScore(row.technical_score) },
    {
      label: "Coverage",
      value: formatRatioAsPercent(row.technical_coverage, 0),
      tone: factorModel
        ? buyTechnicalCoverageMargin !== null && buyTechnicalCoverageMargin < 0
          ? "caution"
          : "default"
        : (row.technical_coverage ?? 1) < 0.75
          ? "caution"
          : "default",
      hint: factorModel
        ? "Model 5.0 applies the technical-coverage floor configured for this run; missing inputs also shrink the observed score toward neutral."
        : "The observed score is shrunk toward neutral by this factor when inputs are missing.",
    },
    {
      label: "Observed score",
      value: formatScore(numeric(payload, "Technical_Observed_Score")),
      hint: "Before the coverage shrink above.",
    },
    { label: "RSI 14", value: formatNumber(row.rsi_14, 1) },
    { label: "ADX 14", value: formatNumber(row.adx_14, 1) },
    { label: "MA20", value: formatINR(numeric(payload, "MA20"), 1) },
    { label: "MA50", value: formatINR(numeric(payload, "MA50"), 1) },
    { label: "MA50 slope", value: formatPercent(numeric(payload, "MA50_Slope_Pct"), 2, true) },
    { label: "1M change", value: formatPercent(row.pct_change_1m, 1, true) },
    { label: "3M change", value: formatPercent(row.pct_change_3m, 1, true) },
    { label: "6M change", value: formatPercent(row.pct_change_6m, 1, true) },
    { label: "Demand proxy", value: text(payload, "Demand_Proxy_Status") },
    { label: "CMF 21", value: formatNumber(numeric(payload, "CMF_21"), 3) },
    { label: "Volume ratio", value: formatNumber(numeric(payload, "Vol_Ratio"), 2) },
  ];

  const dcf = dcfStatus(row.dcf_status);

  const dcfFields: Field[] = [
    { label: "Status", value: dcf.label, hint: dcf.meaning || undefined },
    {
      label: factorModel ? "Value-block eligible" : "Blend eligible",
      value: row.dcf_blend_eligible ? "Yes" : "No",
      tone: row.dcf_blend_eligible ? "positive" : "muted",
      hint: factorModel
        ? row.dcf_blend_eligible
          ? "Included once inside the Value block; no separate post-research adjustment."
          : "Visible as audit evidence but excluded from the Value block."
        : row.dcf_blend_eligible
          ? undefined
          : "Neutral audit evidence: contributes zero to the score.",
    },
    { label: "Valuation score", value: formatScore(row.dcf_valuation_score) },
    { label: "Base-case upside", value: formatRatioAsPercent(row.dcf_base_case_upside, 1, true) },
    { label: "Assessment", value: row.dcf_assessment ?? MISSING },
    { label: "FCF yield", value: formatRatioAsPercent(numeric(payload, "DCF_FCF_Yield")) },
    { label: "Implied 5Y FCF CAGR", value: formatRatioAsPercent(numeric(payload, "DCF_Implied_FCF_CAGR")) },
    { label: "Implied terminal growth", value: formatRatioAsPercent(numeric(payload, "DCF_Implied_Terminal_Growth")) },
    { label: "Discount rate", value: formatRatioAsPercent(numeric(payload, "DCF_Discount_Rate")) },
    { label: "Cash-flow basis", value: text(payload, "DCF_Cash_Flow_Basis") },
  ];

  const transcriptFields: Field[] = [
    { label: "Status", value: row.transcript_status ?? MISSING },
    {
      label: "Scoring eligible",
      value: row.transcript_scoring_eligible ? "Yes" : "No",
      tone: row.transcript_scoring_eligible ? "positive" : "muted",
      hint: row.transcript_scoring_eligible
        ? "Downside-only: can reduce conviction, never raise it."
        : "Visible for context; no score, rating, or rank effect.",
    },
    { label: "Evidence period", value: text(payload, "Transcript_Evidence_Period") },
    { label: "Expected period", value: text(payload, "Transcript_Expected_Period") },
    { label: "Call date", value: formatDate(text(payload, "Transcript_Call_Date")) },
    { label: "Age (days)", value: row.transcript_age_days ?? MISSING },
    { label: "Score", value: formatScore(row.transcript_score) },
    { label: "Guidance", value: row.transcript_guidance ?? MISSING },
    { label: "Risk", value: text(payload, "Transcript_Risk") },
    { label: "Management confidence", value: text(payload, "Transcript_Management_Confidence") },
  ];

  const liquidityFields: Field[] = [
    { label: "Grade", value: row.liquidity_grade ?? MISSING },
    {
      label: "Executable",
      value: row.portfolio_actionable ? "Yes" : "No",
      tone: row.portfolio_actionable ? "positive" : "caution",
    },
    { label: "20D median turnover", value: formatINRCompact(row.median_turnover_20d_inr) },
    { label: "NSE impact cost", value: formatPercent(row.nse_impact_cost_pct, 2) },
    { label: "NSE group", value: text(payload, "NSE_Liquidity_Group") },
    { label: "Est. build days", value: formatNumber(row.portfolio_estimated_build_days, 1) },
    { label: "Actionable rank", value: row.actionable_rank ?? MISSING },
    { label: "Trading frequency 60D", value: formatPercent(numeric(payload, "Trading_Frequency_60D"), 1) },
  ];

  const redFlagFields: Field[] = [
    { label: "Status", value: row.red_flag_status ?? MISSING },
    { label: "Issuer severity", value: row.red_flag_issuer_severity ?? MISSING },
    { label: "Trading severity", value: row.red_flag_trading_severity ?? MISSING },
    { label: "Flag count", value: row.red_flag_count ?? MISSING },
    { label: "Summary", value: text(payload, "Red_Flag_Summary") },
    { label: "As of", value: formatDate(text(payload, "Red_Flag_As_Of")) },
    {
      label: "If confirmed",
      value: text(payload, "Shadow_Red_Flag_Rating_If_Confirmed"),
      hint: "Counterfactual only. The live rating above is unchanged.",
    },
    { label: "Promoter encumbered", value: formatPercent(numeric(payload, "Red_Flag_Promoter_Encumbered_Pct"), 1) },
  ];

  return (
    /*
      Arriving here is always a drill-down from a grid row, so the page scales
      up into place rather than cross-fading. That reads as pushing *into* the
      row that was clicked instead of as an unrelated page swapping in. Kept to
      450ms with a small overshoot -- long enough to register the direction of
      travel, short enough that the financials are readable immediately.
    */
    <ZoomIn className="space-y-4 px-4 py-5 sm:px-6">
        {/*
          Hero band. The headline figures -- price, 1M, 3M, market cap, rank --
          are pulled up here rather than sitting in a "Price and size" card
          further down. The previous header used a full-width row for a ticker
          and a company name and nothing else, leaving most of the fold empty
          while the numbers a reader opens this page for were below it.
        */}
        <div className="panel p-5 sm:p-6">
          <Link
            href="/"
            className="inline-flex items-center gap-1 rounded-full text-xs text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <ArrowLeft className="size-3" aria-hidden />
            Back to screener
          </Link>

          <div className="mt-3 flex items-center gap-3">
            <CompanyLogo
              symbol={row.symbol}
              domain={row.logo_domain}
              size="lg"
            />
            <div className="flex min-w-0 flex-wrap items-baseline gap-x-3 gap-y-1">
              <h1 className="font-mono text-[1.75rem] font-bold leading-tight tracking-tight">
                {row.symbol}
              </h1>
              <p className="text-heading text-muted-foreground">{row.company}</p>
              <RatingBadge rating={row.rating} size="md" />
            </div>
          </div>

          <p className="mt-1.5 text-xs text-muted-foreground">
            {row.sector ?? MISSING}
            {row.industry ? ` · ${row.industry}` : ""} · Rank{" "}
            {row.investment_rank ?? MISSING} of {run.row_count} · Bar{" "}
            {formatDate(row.price_bar_as_of ?? run.price_bar_as_of)}
          </p>

          <dl className="mt-5 grid grid-cols-2 gap-px overflow-hidden rounded-row bg-border sm:grid-cols-4">
            {[
              { label: "Price", value: formatINR(row.current_price), tone: "" },
              {
                label: "1M",
                value: formatPercent(row.pct_change_1m, 1, true),
                tone:
                  (row.pct_change_1m ?? 0) >= 0 ? "text-positive" : "text-negative",
              },
              {
                label: "3M",
                value: formatPercent(row.pct_change_3m, 1, true),
                tone:
                  (row.pct_change_3m ?? 0) >= 0 ? "text-positive" : "text-negative",
              },
              { label: "Market cap", value: formatINRCompact(row.market_cap), tone: "" },
            ].map((stat) => (
              <div key={stat.label} className="bg-muted/40 px-4 py-3">
                <dt className="text-[11px] uppercase tracking-wider text-muted-foreground">
                  {stat.label}
                </dt>
                <dd className={`tabular mt-0.5 text-lead font-semibold ${stat.tone}`}>
                  {stat.value}
                </dd>
              </div>
            ))}
          </dl>
        </div>

        {/*
          The ring gets a fixed narrow column and the waterfall gets the rest.
          Previously they shared a 1.15:1 split, which left the ring floating in
          a tall panel of empty space while the waterfall -- the widest graphic
          on the page -- was squeezed.
        */}
        <div className="grid gap-4 lg:grid-cols-[minmax(0,20rem)_minmax(0,1fr)]">
          <Panel
            title="Decision score"
            description="Against the 0-100 range it is rated on. Ticks mark the REDUCE / HOLD / BUY / STRONG BUY boundaries."
          >
            <DecisionScore
              score={row.decision_score ?? row.final_score}
              rating={row.rating}
              caption={
                row.rating_capped
                  ? (row.rating_cap_reason ??
                    "A policy ceiling reduced this score.")
                  : undefined
              }
            />
          </Panel>

          <div className="space-y-4">
            {factorModel ? (
              <Panel
                title="Factor blocks"
                description="Model 5.0 ranks each economic concept separately, then blends them. Coverage says how much of a block was actually observed."
              >
                <FactorBlocks row={row} />
              </Panel>
            ) : null}

            <Panel
              title="How this score was produced"
              description={
                factorModel
                  ? "The sequence starts with the published factor research score. Reverse DCF is already counted inside Value; later evidence and policy ceilings are then applied once."
                  : "The finalizer runs this sequence once, after all evidence is present. A stage that is not eligible contributes exactly zero."
              }
            >
              <ScoreWaterfall row={row} />
            </Panel>
          </div>
        </div>

        <Panel
          title="Decision audit"
          description="Every explanation below comes from this row's exported evidence and policy fields; no company-specific rules are used."
        >
          <Tabs defaultValue="policy" className="gap-4">
            <TabsList variant="line" aria-label="Decision audit views">
              <TabsTrigger value="policy">Policy ceiling</TabsTrigger>
              <TabsTrigger value="gates">Gate checks</TabsTrigger>
              <TabsTrigger value="coverage">Evidence coverage</TabsTrigger>
            </TabsList>

            <TabsContent value="policy" className="space-y-4">
              <div
                className={`rounded-row border p-4 ${
                  capApplied
                    ? "border-caution/40 bg-caution/5"
                    : "border-border bg-muted/20"
                }`}
              >
                <p className="text-sm font-medium">
                  {capApplied
                    ? `${gate.label} limited the policy-eligible decision.`
                    : "No policy ceiling reduced this decision."}
                </p>
                {capReasons.length ? (
                  <ul className="mt-2 space-y-1 text-xs leading-relaxed text-muted-foreground">
                    {capReasons.map((reason) => (
                      <li key={reason} className="flex gap-2">
                        <span aria-hidden>&bull;</span>
                        <span>{reason}</span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="mt-1 text-xs text-muted-foreground">
                    The exported row contains no active cap reason.
                  </p>
                )}
              </div>
              <FieldList fields={policyFields} columns={4} />
            </TabsContent>

            <TabsContent value="gates">
              <FieldList fields={gateFields} columns={4} />
            </TabsContent>

            <TabsContent value="coverage">
              <FieldList fields={coverageFields} columns={4} />
            </TabsContent>
          </Tabs>
        </Panel>

        <Panel
          title="Decision score history"
          description="Slim daily history, retained beyond the full-snapshot window."
        >
          <HistoryChart history={history} />
        </Panel>

        <div className="grid gap-4 lg:grid-cols-2">
          <Panel
            title="Fundamentals"
            description="Scored by the sector-specific model named below, not a single generic ratio set."
          >
            <FieldList fields={fundamentalFields} columns={2} />
          </Panel>

          <Panel
            title="Technicals"
            description="All indicators computed on the same completed daily bar."
          >
            <FieldList fields={technicalFields} columns={2} />
          </Panel>

          <Panel
            title="Reverse DCF"
            description="Solves the assumptions implied by today's market cap. Evidence, not a target price."
          >
            <FieldList fields={dcfFields} columns={2} />
          </Panel>

          <Panel
            title="Management transcript"
            description="Downside-only evidence: a call can reduce conviction but never promote it."
          >
            <FieldList fields={transcriptFields} columns={2} />
          </Panel>

          <Panel
            title="Red-flag evidence (shadow)"
            description="Counterfactual audit only. These never change the live score or rating."
          >
            <FieldList fields={redFlagFields} columns={2} />
          </Panel>

          <Panel
            title="Liquidity and execution"
            description={
              factorModel
                ? "Execution evidence. It never changes the research score, but it can cap BUY eligibility and therefore affect the rating and eligibility-class rank."
                : "An execution overlay. It never changes the score, rating, or investment rank."
            }
          >
            <FieldList fields={liquidityFields} columns={2} />
          </Panel>
        </div>

        <Panel
          title="Complete source record"
          description="Every field the screener exported for this row, including audit columns not surfaced above."
        >
        <PayloadExplorer payload={payload} />
      </Panel>
    </ZoomIn>
  );
}
