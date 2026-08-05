create extension if not exists pgcrypto;

create table if not exists transcript_filings (
    id uuid primary key default gen_random_uuid(),
    exchange text not null check (exchange in ('NSE')),
    seq_id text not null,
    symbol text not null,
    company_name text,
    announcement_date timestamptz,
    attachment_url text,
    description text,
    status text not null default 'discovered',
    attempt_count integer not null default 0,
    last_error text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (exchange, seq_id)
);

create table if not exists transcript_documents (
    id uuid primary key default gen_random_uuid(),
    sha256 text not null unique,
    size_bytes bigint not null check (size_bytes > 0),
    extraction_method text not null,
    created_at timestamptz not null default now()
);

create table if not exists transcript_filing_documents (
    filing_id uuid primary key references transcript_filings(id) on delete cascade,
    document_id uuid not null references transcript_documents(id) on delete restrict,
    created_at timestamptz not null default now()
);

create table if not exists transcripts (
    id uuid primary key default gen_random_uuid(),
    document_id uuid not null unique references transcript_documents(id) on delete cascade,
    symbol text not null,
    quarter text,
    call_date date,
    cleaned_text text not null,
    token_count integer not null check (token_count >= 0),
    text_hash text not null,
    created_at timestamptz not null default now()
);

create table if not exists transcript_sentiments (
    id uuid primary key default gen_random_uuid(),
    transcript_id uuid not null references transcripts(id) on delete cascade,
    overall_score numeric(5,2) not null check (overall_score between 0 and 100),
    optimism_score numeric(5,2) not null check (optimism_score between 0 and 100),
    guidance_score numeric(5,2) not null check (guidance_score between 0 and 100),
    risk_score numeric(5,2) not null check (risk_score between 0 and 100),
    confidence_score numeric(5,2) not null check (confidence_score between 0 and 100),
    analyst_pressure numeric(5,2) not null check (analyst_pressure between 0 and 100),
    management_confidence numeric(5,2) not null check (management_confidence between 0 and 100),
    answer_quality numeric(5,2) not null check (answer_quality between 0 and 100),
    guidance_direction text not null,
    structured_output jsonb not null,
    model_name text not null,
    analysis_version text not null,
    estimated_cost_usd numeric(10,6) not null default 0,
    created_at timestamptz not null default now(),
    unique (transcript_id, model_name, analysis_version)
);

create index if not exists transcripts_symbol_call_date_idx on transcripts(symbol, call_date desc);
create index if not exists transcript_sentiments_transcript_idx on transcript_sentiments(transcript_id);

create or replace function set_transcript_filing_updated_at()
returns trigger language plpgsql as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

drop trigger if exists transcript_filings_updated_at on transcript_filings;
create trigger transcript_filings_updated_at
before update on transcript_filings
for each row execute function set_transcript_filing_updated_at();

create or replace view transcript_sentiment_history as
select
    t.symbol,
    t.call_date,
    s.overall_score,
    s.optimism_score,
    s.guidance_score,
    s.risk_score,
    s.management_confidence,
    s.guidance_direction,
    s.created_at,
    lag(s.optimism_score) over (
        partition by t.symbol order by t.call_date nulls last, s.created_at
    ) as previous_optimism_score,
    row_number() over (
        partition by t.symbol order by t.call_date desc nulls last, s.created_at desc
    ) as sentiment_rank
from transcripts t
join transcript_sentiments s on s.transcript_id = t.id;

create or replace view latest_transcript_sentiment as
select
    symbol,
    call_date,
    overall_score,
    optimism_score,
    guidance_score,
    risk_score,
    management_confidence,
    guidance_direction,
    optimism_score - previous_optimism_score as optimism_qoq_delta
from transcript_sentiment_history
where sentiment_rank = 1;

alter table transcript_filings enable row level security;
alter table transcript_documents enable row level security;
alter table transcript_filing_documents enable row level security;
alter table transcripts enable row level security;
alter table transcript_sentiments enable row level security;