# Earnings Transcript Sentiment Integration Plan

## AI Stock Screener v3.0

Author: Chirayu Shah
Target System: Advanced NSE/BSE Stock Screener
Purpose: Integrate deterministic Earnings Call Transcript Sentiment Analysis using NSE corporate announcements + local TextBlob and financial lexicon features.
Status: Design Specification

---

# 1. Executive Summary

The existing stock screener performs:

- Fundamental analysis
- Technical analysis
- Reverse DCF valuation
- News sentiment
- Report generation
- Email/WhatsApp delivery
- Backtesting

This project adds a new alternative-data layer:

**Earnings Transcript Sentiment Analysis**

The new system will:

1. Discover newly published earnings call transcripts.
2. Download transcript PDFs.
3. Extract and clean transcript text.
4. Segment management commentary and Q&A.
5. Analyze transcript sentiment locally with TextBlob and a financial lexicon.
6. Generate structured sentiment features.
7. Incorporate transcript signals into stock ranking.
8. Track historical sentiment changes quarter-over-quarter.
9. Backtest transcript signals.

---

# 2. Design Goals

## Primary Goals

- High accuracy
- Low API cost
- Fast execution
- Fully automated
- GitHub Actions compatible
- Backtestable
- Scalable

## Secondary Goals

- Multi-model support
- Re-analysis support
- Historical transcript storage
- Quarterly trend tracking

---

# 3. System Architecture

```text
NSE Announcements
        │
        ▼
Transcript Discovery
        │
        ▼
PDF Download
        │
        ▼
Text Extraction
        │
        ▼
Transcript Cleaning
        │
        ▼
Speaker Segmentation
        │
        ▼
Chunk Generator
        │
        ▼
Local Sentiment Analysis
        │
        ▼
Sentiment Aggregation
        │
        ▼
Feature Store
        │
        ▼
Stock Screener
        │
        ▼
Email / Dashboard / Backtest

4. Project Structure
project/
│
├── app.py
│
├── transcripts/
│   ├── collector.py
│   ├── downloader.py
│   ├── extractor.py
│   ├── cleaner.py
│   ├── segmenter.py
│   ├── chunker.py
│   └── repository.py
│
├── sentiment/
│   ├── local_analyzer.py
│   ├── analyzer.py
│   ├── aggregator.py
│   └── schemas.py
│
├── storage/
│   ├── db.py
│   └── models.py
│
├── scoring/
│   ├── stock_scorer.py
│   └── transcript_enricher.py
│
├── workers/
│   ├── transcript_worker.py
│   └── sentiment_worker.py
│
└── data/
    ├── transcripts/
    ├── metadata/
    └── sentiment/

5. Transcript Discovery
Data Source

NSE Corporate Announcements

Fetch:

announcements = nse.announcements(
    index="equities"
)

Discovery Frequency

GitHub Actions Schedule:

10:00 IST
17:00 IST
21:00 IST

Transcript Detection Rules

Accept if metadata contains:

transcript
conference call transcript
concall transcript
earnings call transcript
analyst meet transcript
investor call transcript


Reject if:

AGM transcript
EGM transcript
postal ballot transcript
court proceeding transcript

6. Database Model
filings
id
exchange
seq_id
symbol
company_name
announcement_date
attachment_url
description
status
created_at


Unique Key:

(exchange, seq_id)

documents
id
filing_id
pdf_path
sha256
size_bytes
downloaded_at

transcripts
id
document_id
symbol
quarter
call_date
text_path
token_count
text_hash
created_at

transcript_sentiment
id
transcript_id
overall_score
optimism_score
guidance_score
risk_score
confidence_score
analyst_pressure
management_confidence
guidance_direction
model_name
analysis_version
created_at

7. PDF Download Pipeline
Download Rules

Only download:

PDF attachments
Not previously processed
Not previously hashed

Deduplication

Level 1

seq_id


Level 2

PDF SHA256

8. Text Extraction
Extraction Order
Primary
PyMuPDF

Fallback
OCR


Only OCR if extracted text is poor.

9. Transcript Cleaning

Remove:

page numbers
headers
footers
safe harbor text
duplicate lines
excess whitespace


Keep:

speaker names
guidance
financial metrics
percentages
currency values

10. Speaker Segmentation

Identify:

Operator
Management
CEO
CFO
COO
Analysts
Moderator


Classify transcript blocks as:

prepared_remarks
analyst_question
management_answer
closing

11. Chunking Strategy

Target Chunk Size:

4000 tokens


Overlap:

150 tokens


Chunk Boundaries:

Speaker boundary
Question boundary
Answer boundary


Never split inside management answer.

12. Local Sentiment Analysis
Purpose

Extract structured financial sentiment.

Method

Each chunk is analyzed locally using TextBlob sentence polarity plus a
transparent financial positive, negative, uncertainty, and guidance lexicon.
The result is deterministic, requires no API key, and is the primary ranking
signal when a fresh transcript is available. Backtest it continuously before
relying on it for investment decisions.

13. Structured Output Schema

Required Output:

{
  "optimism": 0,
  "guidance_strength": 0,
  "management_confidence": 0,
  "risk_intensity": 0,
  "analyst_pressure": 0,
  "answer_quality": 0,

  "guidance_direction": "",
  "revenue_outlook": "",
  "margin_outlook": "",
  "demand_outlook": "",

  "catalysts": [],
  "risks": [],

  "evidence": []
}


All scores:

0-100

14. Sentiment Dimensions
Optimism

Measures:

Growth language
Expansion plans
Positive outlook


Weight:

25%

Management Confidence

Measures:

Level of certainty
Specific commitments
Execution confidence


Weight:

20%

Guidance Strength

Measures:

Raised guidance
Maintained guidance
Lowered guidance


Weight:

20%

Risk Intensity

Measures:

Demand risk
Pricing risk
Raw material risk
Competitive pressure


Weight:

20%


Penalty factor.

Analyst Pressure

Measures:

Repeated questioning
Concern level
Management defensiveness


Weight:

15%


Penalty factor.

15. Transcript Score Calculation
Raw Score
25% Optimism
20% Confidence
20% Guidance
20% Risk Adjustment
15% Answer Quality


Output:

0-100

16. Quarterly Trend Analysis

Store historical sentiment.

Calculate:

QoQ Optimism Delta
QoQ Confidence Delta
QoQ Risk Delta
QoQ Guidance Change


Example:

{
  "current_optimism": 74,
  "previous_optimism": 61,
  "delta": 13
}

17. Recency Weight

Use sentiment decay.

0-30 Days      100%
31-60 Days      75%
61-90 Days      50%
91-180 Days     25%
180+ Days        0%

18. Integrating with Stock Screener

Current Model:

70% Fundamental
30% Technical


Current DCF Adjustment:

20%


New Flow:

Fundamental
Technical
DCF
Transcript Sentiment

Final Weight Recommendation
Fundamental           50%
Technical             22%
DCF                   18%
Transcript            10%

19. Score Modifiers

Transcript can adjust final score.

Positive:

Strong guidance +3
High confidence +2
Positive QoQ tone +2


Negative:

Guidance downgrade -5
High risk -4
High analyst pressure -2


Maximum Adjustments:

+5
-7

20. Strong Buy Conditions

Current Conditions:

Score >= 70
ADX >= 20
Revenue growth
Earnings growth


Add:

No guidance downgrade
Risk score < threshold


Transcript absent:

No penalty

21. GitHub Actions Design
Workflow A

transcripts.yml

Runs:

10:00 IST
17:00 IST
21:00 IST


Tasks:

Discover transcripts
Download PDFs
Extract text
Run local sentiment analysis
Store sentiment

Workflow B

daily-screener.yml

Runs:

07:00 IST


Tasks:

Read transcript sentiment
Run stock screener
Generate reports
Email results

22. Storage Strategy

Persist:

Processed Filing IDs
Transcript Metadata
Sentiment Results
Backtest Data


Do Not Persist:

Large PDFs
Temporary OCR files
Intermediate chunks


Store:

JSON
SQLite
PostgreSQL


SQLite for MVP.

PostgreSQL for scale.

23. Runtime Optimization

Do not analyze same transcript twice.

Cache Key:

Transcript SHA256
Prompt Version
Model Name


Reuse previous result.

No network inference budget is required. Bound work with
`TRANSCRIPT_ANALYSIS_LIMIT` when GitHub Actions runtime needs to be reduced.

24. Error Handling

Retry:

429
500
502
503
504
Timeout


Do Not Retry:

Bad PDF
403
Missing document
Corrupt file

25. Backtesting

Store:

Transcript sentiment
Final rating
Price at prediction
Future returns


Measure:

5-day return
20-day return
60-day return


Compare:

High sentiment stocks
Low sentiment stocks

26. Phase 1

Objective:

Transcript collection.

Deliverables:

Discovery
Download
Storage
Extraction
27. Phase 2

Objective:

Local TextBlob and financial-lexicon sentiment analysis.

Deliverables:

Chunking
Structured output
Aggregation
Scoring
28. Phase 3

Objective:

Stock screener integration.

Deliverables:

Score modifiers
Dashboard integration
Email integration
29. Phase 4

Objective:

Backtesting validation.

Deliverables:

Historical statistics
Signal validation
Weight optimization
30. Phase 5

Objective:

Production scaling.

Deliverables:

PostgreSQL
Redis
Better caching
Parallel workers
Final Recommendation

Start with:

NSE announcements
SQLite
PyMuPDF extraction
Local structured outputs
Shadow-mode transcript fields
GitHub Actions scheduling

Focus most heavily on:

Guidance Changes
Management Confidence
Management Q&A
Risk Increase/Decrease
QoQ Tone Change

Do NOT overweight generic positive sentiment.

The strongest predictive signal is expected to be:

QoQ sentiment improvement + maintained/raised guidance + strong management confidence.


This Markdown is already structured for direct consumption by an implementation agent and can serve as the master specification for the transcript sentiment module.
```
