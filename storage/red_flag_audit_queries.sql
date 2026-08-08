-- Current policy/severity distribution.
select
    coalesce(snapshot->>'policy', 'legacy') as policy,
    severity,
    count(*) as companies,
    sum(flag_count) as total_flags
from red_flag_snapshots
where source = 'VIGIL'
group by 1, 2
order by 1, 2;

-- Evidence for severe issuer cases that require manual confirmation.
select
    r.symbol,
    (r.snapshot->>'issuer_severity')::integer as issuer_severity,
    flag->>'type' as flag_type,
    flag->>'provider_reason' as reason,
    flag->>'date' as event_date,
    flag->>'summary' as evidence,
    flag->>'source_url' as source_url,
    r.source_status,
    r.source_as_of
from red_flag_snapshots r
cross join lateral jsonb_array_elements(r.snapshot->'flags') as flag
where r.source = 'VIGIL'
  and (r.snapshot->>'issuer_severity')::integer = 3
order by r.symbol, (flag->>'severity')::integer desc, flag->>'date' desc;

-- Daily point-in-time coverage for future walk-forward tests.
select
    observed_on,
    policy,
    count(*) as companies,
    count(*) filter (where severity = 3) as severity_3,
    sum(flag_count) as total_flags,
    max(fetched_at) as refreshed_at
from red_flag_snapshot_history
where source = 'VIGIL'
group by observed_on, policy
order by observed_on desc, policy;
