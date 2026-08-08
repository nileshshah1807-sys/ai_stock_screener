es—we can add this without materially slowing the daily scan. The right solution is hybrid: buy or consume structured data where it is reliable, retain our own scoring logic, and perform document analysis outside the daily scan.
Best ready-made options found
Source	What it provides	Suitability
Trendlyne	Analyst estimates, actual-versus-estimate surprises, ownership, promoter pledges, insider trades, DVM/checklist scores, transcripts, presentations and document search	Best all-round Indian-market candidate
VIGIL API	Credit-rating changes, promoter pledges, pledge invocation, insider trades, SAST, ASM/GSM/ESM flags and related-party transactions	Best free hard-red-flag source
Finmagine	Precomputed management tone, concall decoder, pledge history, earnings catalyst and company scorecards	Interesting ready-made NLP provider, but needs validation
Drishti	Structured announcements, earnings, concalls, alerts and streaming feeds	Useful event-discovery alternative
FactSet/LSEG/S&P/Quartr	Institutional transcripts, estimates and formal management-guidance datasets	Highest-quality but probably expensive
IndianAPI	Transcripts, consensus forecasts, targets and credit ratings	Suitable for prototyping; weaker guarantees
Tijori	Accounting red-flag scanner and good research interface	Useful manually, but no clearly documented production API


1. VIGIL is immediately useful
VIGIL exposes approximately 750 Indian companies and seven structured datasets:
Credit-rating actions.
Insider transactions.
Promoter pledge snapshots.
Pledge creation, release and invocation.
SAST disclosures.
ASM/GSM/ESM and other surveillance flags.
Related-party transactions.
It is free, no-auth, CC0-licensed, updated daily, supports bulk Parquet/SQLite downloads and comes from NSE/SEBI source records. We can download everything once in a background job instead of making one API request per company.
Caution: it is maintained by one person and does not appear to offer an institutional SLA. We should mirror it into Supabase, monitor freshness and retain the original filing data. It should be an input, not our only source.
2. Trendlyne appears to be the best commercial fit
Trendlyne’s current data offering includes:
Analyst estimates.
Actual results and surprise percentages.
Financial statements and ratios.
Insider and SAST transactions.
Promoter pledges.
Earnings-call transcripts and presentations.
Semantic search across company documents.
DVM and checklist scores.
It supports multi-stock retrieval, which is important for speed. Trendlyne MCP capabilities, Detailed estimates.
However, automated production APIs require a custom enterprise arrangement. Before purchasing, we should ask about:
Full NSE coverage, including small and microcaps.
Point-in-time estimate history—not restated historical values.
Exact timestamps for estimate revisions.
Bulk endpoints and rate limits.
Rights to cache data in Supabase.
Source attribution and historical depth.
Transcript and estimate coverage percentages.
Whether MCP access is permitted in unattended GitHub Actions.
Trendlyne would principally solve our missing analyst-estimates problem.
3. Finmagine could replace much of our NLP work
Finmagine advertises precomputed Indian-market:
Management-tone trajectories.
Concall decoding.
Dodged/downplayed topics.
Guidance and investor lens.
Pledge history.
Earnings-catalyst and PEAD scores.
It offers REST and MCP endpoints, so the daily application could retrieve JSON rather than download and analyze PDFs. Finmagine API documentation.
But it appears relatively new. Before allowing its output to affect rankings, we should test:
Whether every conclusion includes evidence and source links.
Coverage of smaller NSE companies.
Historical quarter availability.
How missing calls are represented.
Whether the methodology and model version are stable.
Whether scores can be reproduced.
Accuracy against 50–100 transcripts we have already processed.
My recommendation is to test it as a challenger source, not immediately replace our pipeline.
4. Institutional sources exist, but may be excessive
For a larger budget:
LSEG I/B/E/S Guidance explicitly captures management guidance and links it with analyst forecasts.
FactSet supplies global events, audio and transcripts; its estimates API has long historical coverage.
S&P Capital IQ Estimates supplies estimate revisions, surprises and global analyst consensus.
Quartr supplies global first-party transcripts, audio, filings and presentations.
These are the strongest options for point-in-time institutional data, but likely cost far more than the rest of this project.
How we keep the scan fast
The daily scan should never parse transcripts, invoke NLP models or query external APIs company by company.
NSE/Vendor/VIGIL
       ↓
Background ingestion and validation
       ↓
Supabase management/red-flag snapshots
       ↓
Daily scan: one bulk database lookup and DataFrame join
The repository already follows this pattern for transcripts: a separate worker analyzes calls and saves the results; the daily scan only retrieves stored sentiment. We should extend that design.
Suggested refresh schedule:
Prices and technicals: daily/current.
Analyst estimates: daily during result season; otherwise every few days.
Transcript/guidance: event-driven when a new call appears.
Credit ratings and surveillance flags: daily.
Promoter pledge/ownership: quarterly plus event updates.
Related-party transactions: after each filing.
Guidance-delivery history: update after new results.
The scan would perform one cached read for all symbols. That should be negligible compared with the existing per-symbol Yahoo fundamentals collection.
Reduce paid API usage further
Because the management overlay will be capped at ±5 points, we do not need expensive enrichment for every NSE company.
After calculating the base score:
Candidate set =
    current top names
    + portfolio/watchlist companies
    + every stock within 5 points of the top-20 cutoff
A stock more than five points below the cutoff cannot enter the top 20 through a maximum +5 management adjustment. Therefore, only the candidate set needs fresh estimates or deeper transcript research.
Recommended architecture
I recommend three independent signal groups.
Hard red flags
Primarily structured, ready-made data:
Credit-rating downgrade/default.
Pledge invocation or rapidly increasing pledge.
ASM/GSM/ESM surveillance.
Auditor/CFO/independent-director resignation.
Qualified audit opinion.
Material related-party transactions.
Regulatory or exchange action.
Use VIGIL first and later cross-check high-severity events against NSE filings.
Expectations
Prefer a commercial structured source:
EPS/revenue consensus.
Actual-versus-consensus surprise.
Estimate revision over 7/30/90 days.
Number of contributing analysts.
Forecast dispersion.
Management guidance versus consensus.
Trendlyne is currently the most practical candidate to evaluate.
Management evidence
Use the existing pipeline plus an optional vendor:
Quantified guidance.
Guidance revision.
Risks and catalysts.
Q&A responsiveness.
Prepared-remarks versus Q&A tone gap.
Historical guidance delivery.
Finmagine could supply a second opinion; our own pipeline retains control and provides fallback coverage.
Important protection against vendor errors
Purchasing data reduces PDF discovery, OCR and normalization errors—but it does not eliminate errors. It replaces some of them with vendor coverage and methodology risk.
Every imported signal should store:
symbol
signal_type
severity
effective_date
source_provider
source_url
raw_value
derived_value
evidence
confidence
fetched_at
expires_at
methodology_version
A composite vendor score without evidence should receive limited weight. Severe flags should be confirmed against the underlying exchange filing before they cap a rating.
My recommendation
Start with:
VIGIL as the free structured red-flag feed.
Our existing asynchronous transcript pipeline.
A vendor-neutral ExternalSignalProvider interface.
A short Trendlyne evaluation for point-in-time analyst estimates.
A free Finmagine comparison on its supported large-cap symbols.
One cached management/red-flag snapshot joined into the daily scan.
No ranking impact until coverage and accuracy tests pass.