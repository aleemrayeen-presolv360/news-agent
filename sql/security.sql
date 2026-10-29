-- News Intel: who may read and change what (Supabase).
--
-- HOW TO RUN: Supabase dashboard -> SQL Editor -> paste this whole file -> Run.
-- Safe to run more than once. To undo everything: run sql/security_rollback.sql.
--
-- WHAT IT DOES
--   1. Turns on Row Level Security (RLS) on all six tables and adds the rules below
--      in the same run, so the website never sees a moment with RLS on and no rules.
--   2. Keeps the write guards (triggers) that stop members making themselves admin
--      or deciding their own source requests.
--   3. Gives the news pipeline a read-only list of approved feeds (no emails).
--   4. Limits new sign-ups to @presolv360.com addresses. Existing accounts are untouched.
--
-- WHAT IT DOES NOT AFFECT
--   The SQL Editor and the Table Editor run as "postgres", which skips RLS: you can
--   always see and fix every row there. The private service_role key skips it too.
--   RLS only limits requests made with the public anon key (the website).
--
-- THE RULES
--   Not signed in        -> nothing, in any table.
--   profile              -> you read your own row; admins read and change everyone's.
--                           Only admins change roles (guard trigger).
--   note, user_setting   -> only the owner, for everything. Admins can't read notes.
--   source               -> every signed-in member reads; only admins add or change.
--   source_request       -> you see and create your own, and may withdraw it while it
--                           waits; admins see all and approve or reject.
--   audit_log            -> signed-in people add entries about themselves; only admins read.
--   Roles other than 'admin' (e.g. the old 'viewer') are treated as members.
--
-- IF SOMETHING LOOKS WRONG AFTER RUNNING IT
--   A blocked read shows as an empty list on the website (not an error); a blocked
--   save shows "new row violates row-level security policy". Nothing is ever deleted.
--   Undo one table:  ALTER TABLE <table> DISABLE ROW LEVEL SECURITY;
--   Undo everything: run sql/security_rollback.sql.


-- ---------------------------------------------------------------- helper
-- Is the signed-in person an admin? SECURITY DEFINER runs it as the table owner, so
-- it can read profile without going through profile's own rules (no loop).
CREATE OR REPLACE FUNCTION public.is_admin()
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER SET search_path = public
AS $$
    SELECT EXISTS (SELECT 1 FROM profile WHERE id = auth.uid() AND role = 'admin');
$$;


-- ---------------------------------------------------------------- write guards
-- Column-level checks RLS can't express. Only website requests are checked (roles
-- 'anon' and 'authenticated'); the SQL Editor and the service role are not.

-- profile: only admins change roles or delete people; a re-created profile is always a Member
CREATE OR REPLACE FUNCTION public.guard_profile()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public
AS $$
BEGIN
    IF current_user NOT IN ('anon', 'authenticated') OR public.is_admin() THEN
        RETURN COALESCE(NEW, OLD);
    END IF;
    IF TG_OP = 'INSERT' THEN
        NEW.role := 'user';
    ELSIF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Only an admin can remove people' USING ERRCODE = '42501';
    ELSIF NEW.role IS DISTINCT FROM OLD.role THEN
        RAISE EXCEPTION 'Only an admin can change roles' USING ERRCODE = '42501';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS profile_guard ON profile;
CREATE TRIGGER profile_guard
    BEFORE INSERT OR UPDATE OR DELETE ON profile
    FOR EACH ROW EXECUTE FUNCTION public.guard_profile();

-- source_request: members create their own pending request and may withdraw it; only admins decide
CREATE OR REPLACE FUNCTION public.guard_source_request()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public
AS $$
BEGIN
    IF current_user NOT IN ('anon', 'authenticated') OR public.is_admin() THEN
        RETURN COALESCE(NEW, OLD);
    END IF;
    IF TG_OP = 'INSERT' THEN
        IF auth.uid() IS NULL OR NEW.status <> 'pending' OR NEW.requested_by IS DISTINCT FROM auth.uid() THEN
            RAISE EXCEPTION 'Sign in to request a source; an admin decides on it' USING ERRCODE = '42501';
        END IF;
    ELSIF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Only an admin can remove source requests' USING ERRCODE = '42501';
    ELSIF NOT (OLD.status = 'pending' AND NEW.status = 'withdrawn'
               AND OLD.requested_by = auth.uid()
               AND (NEW.name, NEW.url, NEW.category, NEW.requested_by)
                   IS NOT DISTINCT FROM (OLD.name, OLD.url, OLD.category, OLD.requested_by)) THEN
        RAISE EXCEPTION 'Only an admin can approve or reject source requests' USING ERRCODE = '42501';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS source_request_guard ON source_request;
CREATE TRIGGER source_request_guard
    BEFORE INSERT OR UPDATE OR DELETE ON source_request
    FOR EACH ROW EXECUTE FUNCTION public.guard_source_request();


-- ---------------------------------------------------------------- row level security
ALTER TABLE profile        ENABLE ROW LEVEL SECURITY;
ALTER TABLE note           ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_setting   ENABLE ROW LEVEL SECURITY;
ALTER TABLE source         ENABLE ROW LEVEL SECURITY;
ALTER TABLE source_request ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_log      ENABLE ROW LEVEL SECURITY;

-- profile (rows are created by the sign-up trigger, which isn't limited by these rules)
DROP POLICY IF EXISTS profile_read ON profile;
CREATE POLICY profile_read ON profile FOR SELECT TO authenticated
    USING (id = auth.uid() OR public.is_admin());
DROP POLICY IF EXISTS profile_update ON profile;
CREATE POLICY profile_update ON profile FOR UPDATE TO authenticated
    USING (id = auth.uid() OR public.is_admin())
    WITH CHECK (id = auth.uid() OR public.is_admin());
DROP POLICY IF EXISTS profile_delete ON profile;
CREATE POLICY profile_delete ON profile FOR DELETE TO authenticated
    USING (public.is_admin());

-- note: private to its owner
DROP POLICY IF EXISTS note_owner ON note;
CREATE POLICY note_owner ON note FOR ALL TO authenticated
    USING (user_id = auth.uid())
    WITH CHECK (user_id = auth.uid());

-- user_setting: private to its owner
DROP POLICY IF EXISTS user_setting_owner ON user_setting;
CREATE POLICY user_setting_owner ON user_setting FOR ALL TO authenticated
    USING (user_id = auth.uid())
    WITH CHECK (user_id = auth.uid());

-- source: everyone signed in reads the list; admins manage it
DROP POLICY IF EXISTS source_read ON source;
CREATE POLICY source_read ON source FOR SELECT TO authenticated
    USING (true);
DROP POLICY IF EXISTS source_admin ON source;
CREATE POLICY source_admin ON source FOR ALL TO authenticated
    USING (public.is_admin())
    WITH CHECK (public.is_admin());

-- source_request: your own, or all of them for admins
DROP POLICY IF EXISTS source_request_read ON source_request;
CREATE POLICY source_request_read ON source_request FOR SELECT TO authenticated
    USING (requested_by = auth.uid() OR public.is_admin());
DROP POLICY IF EXISTS source_request_create ON source_request;
CREATE POLICY source_request_create ON source_request FOR INSERT TO authenticated
    WITH CHECK ((requested_by = auth.uid() AND status = 'pending') OR public.is_admin());
DROP POLICY IF EXISTS source_request_update ON source_request;
CREATE POLICY source_request_update ON source_request FOR UPDATE TO authenticated
    USING ((requested_by = auth.uid() AND status = 'pending') OR public.is_admin())
    WITH CHECK ((requested_by = auth.uid() AND status = 'withdrawn') OR public.is_admin());
DROP POLICY IF EXISTS source_request_delete ON source_request;
CREATE POLICY source_request_delete ON source_request FOR DELETE TO authenticated
    USING (public.is_admin());

-- audit_log: write entries about yourself; admins read
DROP POLICY IF EXISTS audit_log_write ON audit_log;
CREATE POLICY audit_log_write ON audit_log FOR INSERT TO authenticated
    WITH CHECK (user_id = auth.uid());
DROP POLICY IF EXISTS audit_log_read ON audit_log;
CREATE POLICY audit_log_read ON audit_log FOR SELECT TO authenticated
    USING (public.is_admin());


-- ---------------------------------------------------------------- news pipeline
-- agent/ingest.py reads approved feeds every 4 hours with the public key. RLS hides
-- source_request from that key, so this function hands over just what the pipeline
-- needs: id, name and feed address of approved requests. No emails or reasons.
CREATE OR REPLACE FUNCTION public.approved_source_feeds()
RETURNS TABLE (id bigint, name text, url text)
LANGUAGE sql
STABLE
SECURITY DEFINER SET search_path = public
AS $$
    SELECT id, name, url FROM source_request WHERE status = 'approved' ORDER BY id;
$$;
REVOKE ALL ON FUNCTION public.approved_source_feeds() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.approved_source_feeds() TO anon, authenticated;


-- ---------------------------------------------------------------- sign-ups
-- Only @presolv360.com addresses can create an account. The website says so before
-- sending the form; this is the check that can't be skipped.
-- To allow another domain later, edit the LIKE line and run this section again.
CREATE OR REPLACE FUNCTION public.only_team_emails()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF lower(NEW.email) NOT LIKE '%@presolv360.com' THEN
        RAISE EXCEPTION 'News Intel is for the Presolv360 team: sign up with your @presolv360.com email'
            USING ERRCODE = '42501';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS only_team_emails ON auth.users;
CREATE TRIGGER only_team_emails
    BEFORE INSERT ON auth.users
    FOR EACH ROW EXECUTE FUNCTION public.only_team_emails();
