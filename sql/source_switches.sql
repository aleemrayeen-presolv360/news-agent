-- News Intel: sources and their switches (Supabase). 2 Nov 2026.
--
-- HOW TO RUN: Supabase dashboard -> SQL Editor -> New query -> paste this whole file -> Run.
-- Run after sql/security.sql and sql/hardening.sql. Safe to run more than once.
-- To undo: the lines under "Undo" at the bottom.
--
-- The website's source list comes from the news pipeline (frontend/data.js), so the website
-- shows exactly what is fetched. This file holds what the website and the pipeline share:
--   1. source_off: sources an admin switched off for everyone, by the pipeline's source id.
--      Signed-in people read it (their stories are hidden); only admins change it. The pipeline
--      reads it through switched_off_sources() and stops fetching those sources.
--   2. approved_source_feeds(): approved source requests for the pipeline to fetch, with the
--      category the requester picked. Names, links and categories only; no emails.
--   3. A 100 KB cap on each person's saved settings (user_setting), which hold "My sources".
--
-- The old `source` table is no longer used by the website or the pipeline; it is left as it was.


-- ---------------------------------------------------------------- 1. off for everyone
CREATE TABLE IF NOT EXISTS source_off (
    source_id   TEXT PRIMARY KEY CHECK (length(source_id) BETWEEN 1 AND 100),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE source_off ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS source_off_read ON source_off;
CREATE POLICY source_off_read ON source_off FOR SELECT TO authenticated
    USING (true);
DROP POLICY IF EXISTS source_off_admin ON source_off;
CREATE POLICY source_off_admin ON source_off FOR ALL TO authenticated
    USING (public.is_admin())
    WITH CHECK (public.is_admin());

DROP FUNCTION IF EXISTS public.switched_off_sources();
CREATE FUNCTION public.switched_off_sources()
RETURNS TABLE (source_id text)
LANGUAGE sql
STABLE
SECURITY DEFINER SET search_path = public
AS $$
    SELECT source_id FROM source_off ORDER BY source_id;
$$;
REVOKE ALL ON FUNCTION public.switched_off_sources() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.switched_off_sources() TO anon, authenticated;


-- ---------------------------------------------------------------- 2. approved requests
-- agent/ingest.py reads these every 4 hours with the public key. Row Level Security hides
-- source_request from that key, so this function hands over just what the pipeline needs.
DROP FUNCTION IF EXISTS public.approved_source_feeds();
CREATE FUNCTION public.approved_source_feeds()
RETURNS TABLE (id bigint, name text, url text, category text)
LANGUAGE sql
STABLE
SECURITY DEFINER SET search_path = public
AS $$
    SELECT id, name, url, category FROM source_request WHERE status = 'approved' ORDER BY id;
$$;
REVOKE ALL ON FUNCTION public.approved_source_feeds() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.approved_source_feeds() TO anon, authenticated;


-- ---------------------------------------------------------------- 3. saved settings size
ALTER TABLE user_setting DROP CONSTRAINT IF EXISTS user_setting_size_ok;
ALTER TABLE user_setting ADD CONSTRAINT user_setting_size_ok
    CHECK (length(preferences::text) <= 100000) NOT VALID;


-- Undo:
-- DROP FUNCTION IF EXISTS public.switched_off_sources();
-- DROP TABLE IF EXISTS source_off;
-- ALTER TABLE user_setting DROP CONSTRAINT IF EXISTS user_setting_size_ok;
-- (approved_source_feeds() is needed by the pipeline; keep it.)
