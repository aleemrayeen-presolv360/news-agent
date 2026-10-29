-- Undo sql/security.sql: back to how the database was before (RLS off, open sign-ups).
--
-- HOW TO RUN: Supabase dashboard -> SQL Editor -> paste -> Run. Takes effect at once.
-- Use it only if the website breaks after security.sql and you need it working right
-- away; then the tables are open to anyone with the public key again.
--
-- To undo just one table instead, run only its line below.

ALTER TABLE profile        DISABLE ROW LEVEL SECURITY;
ALTER TABLE note           DISABLE ROW LEVEL SECURITY;
ALTER TABLE user_setting   DISABLE ROW LEVEL SECURITY;
ALTER TABLE source         DISABLE ROW LEVEL SECURITY;
ALTER TABLE source_request DISABLE ROW LEVEL SECURITY;
ALTER TABLE audit_log      DISABLE ROW LEVEL SECURITY;

-- Allow sign-ups from any email address again
DROP TRIGGER IF EXISTS only_team_emails ON auth.users;

-- Left in place on purpose (harmless with RLS off): the rules themselves, the write
-- guards, and approved_source_feeds(), which the pipeline keeps using.
