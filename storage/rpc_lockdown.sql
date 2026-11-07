-- pending_transcripts_for_analysis is SECURITY DEFINER and was executable by
-- anon and authenticated, so the public key could list every transcript's
-- id, symbol, quarter, call date, hash and token count through /rest/v1/rpc
-- (RLS on transcripts is bypassed). Only the workers call it, with the service role.
-- Covers every existing overload (live: text, text, integer) and is safe to re-run.
do $$
declare fn regprocedure;
begin
  for fn in
    select p.oid::regprocedure from pg_proc p
    where p.pronamespace = 'public'::regnamespace and p.proname = 'pending_transcripts_for_analysis'
  loop
    execute format('revoke execute on function %s from public, anon, authenticated', fn);
    execute format('grant execute on function %s to service_role', fn);
  end loop;
end $$;
