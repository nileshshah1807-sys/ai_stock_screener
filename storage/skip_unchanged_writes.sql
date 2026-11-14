-- An upsert that changes nothing writes nothing.
--
-- The concall feed and the valuation basis are re-upserted whole on every run
-- (777k and 1.2M row updates by 14 Nov 2026, against 3k and 8.5k rows), and every
-- update is a new row version: database growth, vacuum work and, after the D1
-- move, rows written against the 100k-a-day Free limit. The writers send the same
-- rows as before; this trigger drops an update whose row equals the stored one in
-- everything but updated_at, which the writer stamps on every run. A row that did
-- change is written as before, with its new updated_at.
--
-- Fires before concall_feed_updated_at (triggers run in name order), so a skipped
-- row keeps the updated_at of its last real change. Apply by hand; re-applying is safe.

create or replace function skip_unchanged_update()
returns trigger
language plpgsql
as $$
begin
    if (to_jsonb(new) - 'updated_at') = (to_jsonb(old) - 'updated_at') then
        return null;
    end if;
    return new;
end;
$$;

drop trigger if exists concall_feed_a_skip_unchanged on concall_feed;
create trigger concall_feed_a_skip_unchanged
before update on concall_feed
for each row execute function skip_unchanged_update();

drop trigger if exists valuation_basis_a_skip_unchanged on valuation_basis;
create trigger valuation_basis_a_skip_unchanged
before update on valuation_basis
for each row execute function skip_unchanged_update();
