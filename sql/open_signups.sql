-- Let anyone create a News Intel account (email or Google), not only @presolv360.com.
--
-- HOW TO RUN: Supabase dashboard -> SQL Editor -> New query -> paste -> Run.
-- Safe to run more than once. It only removes the sign-up check; Row Level Security stays on,
-- so each person still sees only their own notes, saves and settings, and only admins
-- change sources, roles and source requests.
DROP TRIGGER IF EXISTS only_team_emails ON auth.users;
DROP FUNCTION IF EXISTS public.only_team_emails();
