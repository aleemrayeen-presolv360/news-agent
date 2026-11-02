-- News Intel: source switches (Supabase). Added 2 Nov 2026.
--
-- HOW TO RUN: Supabase dashboard -> SQL Editor -> New query -> paste this whole file -> Run.
-- Run after sql/security.sql and sql/hardening.sql. Safe to run more than once.
-- To undo: the two DROP / ALTER lines at the bottom (commented out).
--
-- WHAT IT DOES
--   1. "Off for everyone" (Settings > Admin > Sources) now also stops the news pipeline
--      fetching that source. The pipeline reads the switched-off list through this function
--      with the public key, the same way it reads approved_source_feeds(). It returns only
--      names and feed addresses; no emails.
--   2. Caps each person's saved settings at 100 KB. "My sources" (sources hidden for one person
--      only) is now saved in user_setting, so it follows them to every device. Only the owner
--      can read or change their row (sql/security.sql).

CREATE OR REPLACE FUNCTION public.switched_off_sources()
RETURNS TABLE (name text, url text)
LANGUAGE sql
STABLE
SECURITY DEFINER SET search_path = public
AS $$
    SELECT name, url FROM source WHERE enabled = false ORDER BY name;
$$;
REVOKE ALL ON FUNCTION public.switched_off_sources() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.switched_off_sources() TO anon, authenticated;

ALTER TABLE user_setting DROP CONSTRAINT IF EXISTS user_setting_size_ok;
ALTER TABLE user_setting ADD CONSTRAINT user_setting_size_ok
    CHECK (length(preferences::text) <= 100000) NOT VALID;

-- Undo:
-- DROP FUNCTION IF EXISTS public.switched_off_sources();
-- ALTER TABLE user_setting DROP CONSTRAINT IF EXISTS user_setting_size_ok;
