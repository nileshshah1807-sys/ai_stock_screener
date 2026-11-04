-- =====================================================================
-- Step 4 of storage/rating_access_schema.sql: close the base tables
-- =====================================================================
--
-- Apply only after the dashboard that reads the `*_visible` views is deployed.
-- The dashboard before it reads these tables directly and would get
-- "permission denied" on every page.
--
-- Signed-in viewers then read ratings only through the views, which null them
-- for anyone but an admin. The service role (the publisher and the workers)
-- keeps its own grants and is unaffected.
--
-- To undo: grant select on the three tables to authenticated again.

revoke select on screener_snapshot from authenticated, anon;
revoke select on screener_history from authenticated, anon;
revoke select on screener_runs from authenticated, anon;
