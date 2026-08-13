# Scoping: a regulatory-evidence feed for banks, NBFCs and insurers

- **Status:** investigation complete, nothing implemented
- **Date:** 2026-08-13
- **Trigger:** section 20.8 of `docs/stock_screener_system_architecture.md`

## 1. The problem this solves

`Gross_NPA`, `Net_NPA`, `Capital_Adequacy` and `Solvency_Ratio` are required by
`specialized_quality_gate()` and sit inside the `Fundamental_Coverage` denominator, but **no
collector in this repository has ever populated them** and Yahoo Finance does not publish them.

The consequences today, in the 4.x model *and* in the Model 5.0 candidate:

| Model | Expected fields | Always missing | `Fundamental_Coverage` ceiling | Effect |
|---|---:|---|---:|---|
| Bank / NBFC Equity Quality | 8 | Gross_NPA, Net_NPA, Capital_Adequacy | 0.625 | Never BUY |
| Insurance Equity Quality | 6 | Solvency_Ratio | 0.833 | Never STRONG BUY; BUY blocked by the specialist gate |

Confirmed on a live 40-name run: all 9 financial-sector rows failed with
`missing specialized quality data`. Financials are the largest sector in the Indian market, so
this silently removes a large part of the investable universe from every actionable output.

## 2. What has to be sourced

| Field | Applies to | Unit expected by `_financial_quality_percentages()` |
|---|---|---|
| `Gross_NPA` | Banks, NBFCs | ratio or percent (units inferred from `Capital_Adequacy`) |
| `Net_NPA` | Banks, NBFCs | ratio or percent |
| `Capital_Adequacy` | Banks, NBFCs | ratio or percent; drives the unit inference |
| `Solvency_Ratio` | Insurers | multiple (e.g. 1.8x); `>10` is divided by 100 |

Cadence needs to be quarterly, per company, with a stable symbol join and an as-of date, to fit
the existing point-in-time and provenance discipline.

## 3. Verified findings

Everything below was probed directly on 2026-08-13, not inferred from documentation.

### 3.1 NSE corporate financial results API — **works, and solves banks**

```text
GET https://www.nseindia.com/api/corporates-financial-results?index=equities&period=Quarterly
GET https://www.nseindia.com/api/corporates-financial-results?index=equities&period=Quarterly&symbol=HDFCBANK
```

A homepage GET first is required to obtain cookies; the same `User-Agent` treatment the
collector already uses for `EQUITY_L.csv` is sufficient.

- Returns **3,816 filings across 2,111 distinct symbols**.
- Each row carries `symbol`, `isin`, `toDate`, `period`, `audited`, `consolidated`, `filingDate`
  and — critically — a `bank` classification flag and a direct `xbrl` URL.
- NSE serves **three separate XBRL taxonomies**, selected by that flag:

| `bank` flag | XBRL prefix | Distinct symbols | NPA tags present? |
|---|---|---:|---|
| `B` (banks) | `BANKING_` | 41 | **Yes** |
| `F` (NBFC/finance) | `NBFC_INDAS_` | 116 | **No** |
| `N` (all others) | `INDAS_` | 1,954 | n/a |

The per-symbol endpoint returned 103 historical filings for HDFCBANK, so multi-year history is
available for backfill.

### 3.2 The `BANKING_` taxonomy carries NPA — in the **standalone** filing only

Tags present and populated:

```text
PercentageOfGrossNpa        <- Gross NPA %, as a ratio
PercentageOfNpa             <- Net NPA %, as a ratio
GrossNonPerformingAssets    <- absolute rupee amount
NonPerformingAssets         <- absolute rupee amount
AdditionalTier1Ratio        <- AT1 only; NOT the CRAR
```

Spot-checked against reported Q3 FY25 figures — all three match:

| Symbol | `PercentageOfGrossNpa` | `PercentageOfNpa` |
|---|---:|---:|
| HDFCBANK | 0.0142 (1.42%) | 0.0046 (0.46%) |
| SBIN | 0.0207 (2.07%) | 0.0053 (0.53%) |
| AXISBANK | 0.0146 (1.46%) | 0.0035 (0.35%) |

**Two traps that must be handled by any implementation:**

1. **Consolidated filings return `0.00` for every NPA tag.** Banks disclose asset quality in the
   standalone results. Reading the consolidated filing — which is the first row the API returns
   for HDFCBANK — yields a silent, plausible-looking zero. A zero NPA would sail through
   `specialized_quality_gate()` as *excellent* asset quality. This is the single highest-risk
   defect in this integration and must be a test, not a comment.
2. **Values are ratios, not percentages** (`0.0142`, not `1.42`). This happens to match the unit
   inference in `_financial_quality_percentages()`, which keys off `abs(Capital_Adequacy) <= 1` —
   but that inference reads *capital adequacy*, which this source does not provide. Feeding NPA
   ratios without a `Capital_Adequacy` value would make the helper treat them as percentages and
   understate NPA by 100x. Units must be normalised at the collector, not inferred downstream.

### 3.3 What is **not** available

| Source | Probe result |
|---|---|
| `NBFC_INDAS_` XBRL (116 symbols) | No NPA, Stage 3, CAR or asset-quality tags of any kind — confirmed on 6 NBFCs, and on annual filings with 226 populated tags. Only `ImpairmentOnFinancialInstruments` (a P&L credit-cost flow) is tagged. |
| Capital adequacy / CRAR, any NSE taxonomy | Absent. Only `AdditionalTier1Ratio` exists, and it reads `0.00` for HDFCBANK. CRAR is disclosed in the notes to the results, i.e. in the PDF. |
| Insurance solvency | No `bank` flag for insurers and no rows returned for `HDFCLIFE` on this endpoint. Not in this feed. |
| yfinance statements for NBFCs | No loan book and no credit provisions. `Receivables` for BAJFINANCE is ₹58bn against ₹5,599bn of total assets, i.e. not the loan book. Cannot support a credit-cost ratio. |
| BSE `Corpfinancialresult` API | Returned an HTML error page, not JSON. `AnnGetData` returned `"No Record Found!"` for the same scrip. Not usable without further work. |
| RBI DBIE (`data.rbi.org.in`) | An Angular single-page app; no plain REST endpoint. `cimsdbie.rbi.org.in` fails TLS verification (certificate hostname mismatch). Bank-wise data exists but is annual and would need a portal-specific client. |
| IRDAI public disclosures | Liferay portal serving HTML; per-insurer quarterly disclosures are published as **PDF** (Form L-32 carries solvency). No structured feed. |
| Existing VIGIL feed (`api.tigzig.com`) | Live tables are `credit_ratings`, `insider_trading`, `pledge_data`, `sast_disclosures`, `encumbrance_events`, `surveillance_flags`, `rpt_transactions`. No asset-quality table. |

### 3.4 NBFC and CRAR evidence **does** exist — in the results PDF

The structured feeds do not carry NBFC asset quality, but the underlying disclosure is mandatory
and is published in the results attachment, which NSE exposes programmatically:

```text
GET https://www.nseindia.com/api/corporate-announcements?index=equities&symbol=BAJFINANCE
    -> rows with attchmntFile -> https://nsearchives.nseindia.com/corporate/<file>.pdf
```

Verified content (PyMuPDF, already a dependency at `PyMuPDF>=1.27.1`):

| Symbol | Extracted disclosure |
|---|---|
| BAJFINANCE | "Gross NPA (stage 3 assets gross) ratio 1.41%", "Net NPA (stage 3 net) ratio 0.5%", "Capital to risk-weighted assets ratio (calculated as per RBI guidelines)" |
| SHRIRAMFIN | "Capital adequacy ratio (%)", "Gross NPA ratio (%)", "Net NPA ratio (%)", "NPA provision coverage ratio (%)" |
| MUTHOOTFIN | "Stage III loan assets to Gross loan assets 3.51%", "Capital Adequacy Ratio 25.11%", "Provision Coverage Ratio" |

**This also closes the CRAR gap for banks**, which no XBRL taxonomy carries. One PDF pipeline
could serve all four fields for both banks and NBFCs.

Measured reliability over 12 NBFCs, scanning up to 6 recent results attachments each and
ignoring attachments of 3 pages or fewer:

| Measure | Result |
|---|---:|
| Results PDF reachable | 86% |
| Digitally extractable (>=500 chars/page, i.e. not a scan) | 86% |
| CRAR phrase detected | 83% |
| Gross NPA phrase detected | 50% |
| Net NPA phrase detected | 50% |
| All three detected | 42% |

**The 50% is a detection limit, not an availability limit**, and the difference matters for
estimating the work. Known causes, each fixable:

1. **Label vocabulary varies by filer.** MUTHOOTFIN writes "Stage III" in Roman numerals, which a
   `stage\s*3` pattern misses entirely. Others use "GNPA", "Gross Non-Performing Assets", or
   "Gross Stage 3 assets to gross loan assets". A production extractor needs a curated synonym
   set, not one regex.
2. **Attachment selection is the real bottleneck.** Each company files ~57 results-related
   announcements; many are one-page board-meeting intimations rather than the results with the
   RBI annexure. Naively taking the most recent one yielded 29%; scanning six and skipping short
   documents raised it to 42%.
3. **Some filings are scanned images.** BAJFINANCE's 40-page, 8.9 MB PDF extracts as OCR-garbled
   text ("Grou NPA (stage 3 as\"\"~ gro<1) ratio 1.41:."), where the phrase is still detectable
   but the *number* is not safely parseable.
4. **Labels and values are separated in the text stream.** SHRIRAMFIN's extraction emits every
   value, then every label. Regex adjacency ("label followed by number") will silently mis-pair
   figures. This needs coordinate-based table extraction via `page.find_tables()` or word
   bounding boxes — the single most important design constraint here, because a mis-paired CRAR
   is worse than a missing one: it passes the gate with a fabricated number.

## 4. Coverage this would actually buy

| Population | Symbols | NPA | CRAR | Solvency |
|---|---:|---|---|---|
| Banks (`B`) | 41 | **NSE XBRL** (clean) | NSE results PDF | n/a |
| NBFC / finance (`F`) | 116 | NSE results PDF | NSE results PDF | n/a |
| Insurers | few | n/a | n/a | IRDAI PDF (not probed in depth) |

The free structured route fully and cleanly unblocks **NPA for 41 banks**. Everything else is
obtainable but only through PDF extraction, at the reliability measured in 3.4.

Even for those 41, BUY additionally requires clearing the `Fundamental_Coverage` floor. Supplying
2 of the 3 missing bank fields lifts coverage from 0.625 to 0.875, which clears both the 0.70
Model 5.0 BUY floor and the 0.75 STRONG BUY floor — **so NPA alone is enough to unblock banks**,
even without CRAR, provided `Capital_Adequacy` is dropped from the expected-field list rather
than left permanently missing.

## 5. Recommended design

**Phase 1 — banks, from NSE XBRL (recommended; highest value per unit of work).**

- New `screener/regulatory.py` with a `NSEResultsXBRLCollector`, mirroring the shape of
  `screener/statements.py`: injectable fetcher, long-TTL CSV cache
  (`regulatory_cache.csv`), bounded per-run backfill, schema version.
- Select filings with `bank == "B"` **and** `consolidated` not starting with `"Cons"`, newest
  `toDate` first.
- Parse `PercentageOfGrossNpa` / `PercentageOfNpa`, normalise explicitly to percent at the
  collector, and export `Gross_NPA`, `Net_NPA`, plus `Regulatory_As_Of`, `Regulatory_Source_URL`
  and `Regulatory_Filing_Type` for provenance.
- Tests that must exist before this is trusted:
  - a consolidated filing's zeros are **rejected**, not published as pristine asset quality;
  - unit normalisation is asserted against a known value (HDFCBANK 1.42%);
  - a missing/failed filing leaves the fields missing and the row fails closed;
  - stale filings beyond a configured age are not silently reused.
- Then decide `Capital_Adequacy`: either drop it from `FINANCIAL_SPECIALIZED_FIELDS` and from
  `specialized_quality_gate()`'s bank requirements, or keep the gate and accept that banks stay
  blocked. **Dropping an uncollectable field from the coverage denominator is the honest option**
  — coverage should measure how much of what is knowable is known.

*Estimate: ~1 day including tests, entirely within existing patterns.*

**Phase 2 — NBFC NPA and CRAR from the results PDF (viable, but a real project).**

Verified as available in 3.4. Design constraints that follow directly from the measurements:

- **Coordinate-based table extraction, never regex adjacency.** Labels and values are separated
  in the text stream. A mis-paired CRAR is worse than a missing one, because it passes the
  regulatory gate with a fabricated number. Use `page.find_tables()` or word bounding boxes and
  require the value to sit in the same visual row as its label.
- **Curated synonym set** covering at minimum: Stage 3 / Stage III / GNPA / Gross NPA / Gross
  Non-Performing Assets / Gross Stage 3 assets to gross loan assets; and Capital Adequacy /
  Capital to Risk-Weighted Assets / CRAR.
- **Attachment selection needs its own logic** — filter to multi-page documents and prefer those
  containing the annexure heading, rather than taking the most recent results announcement.
- **Sanity bounds and shadow mode.** Reject GNPA outside 0-30%, CRAR outside 5-60%, and route
  everything through the existing `Shadow_*` pattern (`red_flags/shadow.py`) until a sample has
  been reconciled against the filings by hand. Extracted regulatory numbers should not gate a
  live rating on their first run.
- **Scanned filings must fail closed.** Where characters-per-page indicates an image PDF, emit
  missing rather than a parsed number; BAJFINANCE demonstrates a case where the phrase is
  detectable but the digits are corrupted.

*Estimate: 1-2 weeks including per-company reconciliation, plus ongoing maintenance as filers
change layout. This is the honest cost — it is a parsing project, not a collector.*

**Phase 3 — insurers.** IRDAI publishes Form L-32 solvency as PDF only; individual insurer
investor-relations pages carry the same. Few listed names, so manual quarterly entry into a small
curated CSV is a defensible alternative to building a third extractor.

**Alternative to Phases 2-3 — a licensed data vendor.** Company-level Indian financial-sector
fundamentals with point-in-time history solves NPA, CRAR and solvency in one integration *and*
resolves the point-in-time dependency that currently blocks Model 5.0's walk-forward validation
(section 20.9). Given Phase 2 is 1-2 weeks plus indefinite maintenance, this should be priced
against both needs together before any bespoke parser is written.

**Do not** scrape aggregator sites (Screener.in, Trendlyne and similar). Their terms generally
prohibit it, and the existing architecture's provenance discipline — source URL, as-of date,
verifiable primary filing — cannot be honoured by a derived, unattributable number.

## 6. Recommendation

1. **Do Phase 1 now.** Small, official, free, fully verified, and it unblocks the 41 listed banks
   — the largest and most liquid part of the sector — for about a day of work.
2. **Drop `Capital_Adequacy` from the bank/NBFC expected-field list** at the same time. Keeping a
   permanently uncollectable field in a coverage denominator is a measurement bug, not
   conservatism, and NPA alone lifts bank coverage from 0.625 to 0.875, clearing both the BUY and
   STRONG BUY floors.
3. **Price a licensed vendor before starting Phase 2.** The PDF route works and is fully scoped
   above, but 1-2 weeks plus permanent layout maintenance, for 116 NBFCs, is a poor trade if a
   vendor also closes the validation blocker.
4. If no vendor is acquired, build Phase 2 in shadow mode and reconcile by hand before letting any
   extracted number gate a published rating.
