-- Buying during the trial ends it (6 Nov 2026). The subscription now starts at
-- once (no start_at), so the webhook's 'active' event nulls trial_ends_at: the
-- row no longer carries a trial. custom_access_token_hook is unchanged: for
-- 'active' it already grants plan <id> until current_period_end (greatest()
-- ignores the null). Applied by hand; safe to re-run.
create or replace function billing_apply_event(
    p_razorpay_subscription_id text,
    p_user_id uuid,
    p_plan_id text,
    p_status text,
    p_current_period_end timestamptz,
    p_event_id text,
    p_event_at timestamptz
)
returns boolean
language plpgsql
security definer
set search_path = public
as $$
declare
    changed integer;
begin
    if coalesce(p_event_id, '') = '' or p_event_at is null then
        return false;
    end if;
    update subscriptions s set
        razorpay_subscription_id = p_razorpay_subscription_id,
        status = coalesce(p_status, s.status),
        -- paying ends the trial: the row no longer carries a trial end
        trial_ends_at = case when p_status = 'active' then null else s.trial_ends_at end,
        current_period_end = coalesce(p_current_period_end, s.current_period_end),
        plan_id = coalesce(p_plan_id, s.plan_id),
        last_event_id = p_event_id,
        last_event_at = p_event_at,
        updated_at = now()
    where (s.razorpay_subscription_id = p_razorpay_subscription_id
           or (s.razorpay_subscription_id is null and s.user_id = p_user_id))
      and s.last_event_id is distinct from p_event_id
      and (s.last_event_at is null
           or s.last_event_at < p_event_at
           or (s.last_event_at = p_event_at
               and billing_status_rank(coalesce(p_status, s.status)) >= billing_status_rank(s.status)));
    get diagnostics changed = row_count;
    return changed > 0;
end;
$$;
revoke all on function billing_apply_event(text, uuid, text, text, timestamptz, text, timestamptz) from public, anon, authenticated;
grant execute on function billing_apply_event(text, uuid, text, text, timestamptz, text, timestamptz) to service_role;
