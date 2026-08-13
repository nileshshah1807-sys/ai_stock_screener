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
| `NBFC_INDAS_` XBRL (116 symbols) | No NPA, CAR or asset-quality tags of any kind. NBFCs disclose GNPA in results PDFs and investor presentations, not in the tagged filing. |
| Capital adequacy / CRAR, any NSE taxonomy | Absent. Only `AdditionalTier1Ratio` exists, and it reads `0.00` for HDFCBANK. CRAR is disclosed in the notes to the results, i.e. in the PDF. |
| Insurance solvency | No `bank` flag for insurers and no rows returned for `HDFCLIFE` on this endpoint. Not in this feed. |
| BSE `Corpfinancialresult` API | Returned an HTML error page, not JSON. `AnnGetData` returned `"No Record Found!"` for the same scrip. Not usable without further work. |
| RBI DBIE (`data.rbi.org.in`) | An Angular single-page app; no plain REST endpoint. `cimsdbie.rbi.org.in` fails TLS verification (certificate hostname mismatch). Bank-wise data exists but is annual and would need a portal-specific client. |
| IRDAI public disclosures | Liferay portal serving HTML; per-insurer quarterly disclosures are published as **PDF** (Form L-32 carries solvency). No structured feed. |
| Existing VIGIL feed (`api.tigzig.com`) | Live tables are `credit_ratings`, `insider_trading`, `pledge_data`, `sast_disclosures`, `encumbrance_events`, `surveillance_flags`, `rpt_transactions`. No asset-quality table. |

## 4. Coverage this would actually buy

| Population | Symbols | NPA | CRAR | Solvency |
|---|---:|---|---|---|
| Banks (`B`) | 41 | **NSE XBRL** | not sourced | n/a |
| NBFC / finance (`F`) | 116 | not sourced | not sourced | n/a |
| Insurers | few | n/a | n/a | not sourced |

So the free, official, structured route fully unblocks **NPA for 41 banks** and nothing else.

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

**Phase 2 — NBFC and insurer evidence (materially harder, decide separately).**

Every remaining field lives in PDFs. Options, in descending order of robustness:

1. **A licensed data vendor** with company-level Indian financial-sector fundamentals. Solves
   NPA, CRAR and solvency in one integration, with point-in-time history — which is also the
   blocking dependency for the Model 5.0 walk-forward validation (section 20.9). This is the only
   option that solves both problems at once and is worth pricing before building anything bespoke.
2. **PDF extraction** from NSE/BSE results attachments and IRDAI Form L-32. The repo already has
   PDF handling in `transcripts/extractor.py` to build on. Fragile against layout changes and
   needs per-company review; treat any extracted value as shadow evidence until reconciled.
3. **RBI DBIE** for annual bank-wise CRAR. Official but annual, bank-only, and needs a
   portal-specific client. Useful as a cross-check, not as the primary feed.

**Do not** scrape aggregator sites (Screener.in, Trendlyne and similar). Their terms generally
prohibit it, and the existing architecture's provenance discipline — source URL, as-of date,
verifiable primary filing — cannot be honoured by a derived, unattributable number.

## 6. Recommendation

Do Phase 1. It is small, uses an official free source, is fully verified above, and unblocks the
41 listed banks — the largest and most liquid part of the financial sector. Pair it with removing
`Capital_Adequacy` from the bank/NBFC expected-field list, since keeping a permanently
uncollectable field in a coverage denominator is a measurement bug, not conservatism.

Price a licensed vendor before committing to Phase 2 by PDF extraction. The same purchase would
resolve the point-in-time fundamentals gap that currently blocks Model 5.0's validation protocol,
so it should be evaluated against both needs together rather than as a financials-only cost.
