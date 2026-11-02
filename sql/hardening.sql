-- News Intel: database checks on top of sql/security.sql (Supabase). Added 2 Nov 2026.
--
-- HOW TO RUN: Supabase dashboard -> SQL Editor -> New query -> paste this whole file -> Run.
-- Run sql/security.sql first (it already ran on 29 Oct). Safe to run more than once.
-- To undo: run sql/hardening_rollback.sql. Why each rule exists: SECURITY.md.
--
-- WHY: anyone can sign up now (since 30 Oct), and the website's form checks only run in
-- the browser. Someone can skip them by calling the database directly with the public key,
-- so the rules that matter are repeated here, where they can't be skipped:
--   1. Links must be http(s) addresses, and text has a maximum length (CHECK constraints).
--   2. Emails shown to admins come from the sign-in token, never from what the browser sent:
--      "requested by", "reviewed by" and the audit log can't be faked, and nobody changes
--      the email on their profile from the website.
--   3. Members may only log their own sign-ins, sign-ups and source requests in the audit log,
--      so the log can't be filled with fake "approved" or "changed a role" entries.
--   4. Write limits per person, so one account can't fill the free 500 MB database:
--        new notes          100 an hour, 2,000 in total
--        source requests    10 a day (admins: no limit)
--        audit entries      200 an hour
--
-- WHAT IT DOES NOT AFFECT
--   Existing rows are not checked (NOT VALID), so nothing old is refused or deleted.
--   The SQL Editor, the Table Editor and the service role skip the triggers.
--   The website shows the refusal message in the form (for example "Too many source requests today").


-- ---------------------------------------------------------------- 1. lengths and link format
ALTER TABLE source_request DROP CONSTRAINT IF EXISTS source_request_url_ok;
ALTER TABLE source_request ADD CONSTRAINT source_request_url_ok
    CHECK (url ~* '^https?://[^[:space:]]+$' AND length(url) <= 2000) NOT VALID;
ALTER TABLE source_request DROP CONSTRAINT IF EXISTS source_request_text_ok;
ALTER TABLE source_request ADD CONSTRAINT source_request_text_ok
    CHECK (length(name) BETWEEN 1 AND 200 AND length(category) <= 40
           AND coalesce(length(reason), 0) <= 1000 AND coalesce(length(review_note), 0) <= 1000) NOT VALID;

ALTER TABLE source DROP CONSTRAINT IF EXISTS source_url_ok;
ALTER TABLE source ADD CONSTRAINT source_url_ok
    CHECK (url ~* '^https?://[^[:space:]]+$' AND length(url) <= 2000) NOT VALID;
ALTER TABLE source DROP CONSTRAINT IF EXISTS source_text_ok;
ALTER TABLE source ADD CONSTRAINT source_text_ok
    CHECK (length(name) BETWEEN 1 AND 200 AND length(category) <= 40) NOT VALID;

-- Notes hold pasted images as text (an image of up to 2 MB is about 2.7 MB), so the limit is generous
ALTER TABLE note DROP CONSTRAINT IF EXISTS note_size_ok;
ALTER TABLE note ADD CONSTRAINT note_size_ok
    CHECK (coalesce(length(title), 0) <= 500 AND coalesce(length(content), 0) <= 10000000) NOT VALID;

ALTER TABLE audit_log DROP CONSTRAINT IF EXISTS audit_log_size_ok;
ALTER TABLE audit_log ADD CONSTRAINT audit_log_size_ok
    CHECK (length(action) <= 40 AND coalesce(length(details), 0) <= 5000) NOT VALID;

ALTER TABLE profile DROP CONSTRAINT IF EXISTS profile_name_ok;
ALTER TABLE profile ADD CONSTRAINT profile_name_ok
    CHECK (coalesce(length(name), 0) <= 200) NOT VALID;


-- ---------------------------------------------------------------- helpers
-- The signed-in person's email, from their sign-in token (set by Supabase, can't be edited)
CREATE OR REPLACE FUNCTION public.my_email()
RETURNS text
LANGUAGE sql
STABLE
AS $$
    SELECT auth.jwt() ->> 'email';
$$;

-- How many rows the signed-in person added to a table recently. SECURITY DEFINER because
-- members can't read audit_log; it only ever counts the caller's own rows.
CREATE OR REPLACE FUNCTION public.my_recent_rows(tbl text, since interval)
RETURNS bigint
LANGUAGE plpgsql
STABLE
SECURITY DEFINER SET search_path = public
AS $$
BEGIN
    RETURN CASE tbl
        WHEN 'note' THEN (SELECT count(*) FROM note WHERE user_id = auth.uid() AND created_at > now() - since)
        WHEN 'source_request' THEN (SELECT count(*) FROM source_request WHERE requested_by = auth.uid() AND created_at > now() - since)
        WHEN 'audit_log' THEN (SELECT count(*) FROM audit_log WHERE user_id = auth.uid() AND created_at > now() - since)
    END;
END;
$$;
REVOKE ALL ON FUNCTION public.my_recent_rows(text, interval) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.my_recent_rows(text, interval) TO authenticated;

-- So the counts above stay fast
CREATE INDEX IF NOT EXISTS note_user_created_idx ON note (user_id, created_at);
CREATE INDEX IF NOT EXISTS source_request_by_created_idx ON source_request (requested_by, created_at);
CREATE INDEX IF NOT EXISTS audit_log_user_created_idx ON audit_log (user_id, created_at);


-- ---------------------------------------------------------------- 2-4. stamp and limit website writes
-- Only website requests (roles 'anon' and 'authenticated') are touched, like the guards in
-- sql/security.sql. These run after those guards (triggers fire in name order).
CREATE OR REPLACE FUNCTION public.stamp_website_write()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public
AS $$
DECLARE
    admin boolean;
BEGIN
    IF current_user NOT IN ('anon', 'authenticated') THEN
        RETURN NEW;
    END IF;
    admin := public.is_admin();

    IF TG_OP = 'INSERT' THEN
        NEW.created_at := now();   -- the browser's clock can't dodge the limits below
    END IF;

    IF TG_TABLE_NAME = 'profile' THEN
        IF TG_OP = 'UPDATE' THEN
            NEW.email := OLD.email;
            NEW.created_at := OLD.created_at;
        END IF;

    ELSIF TG_TABLE_NAME = 'note' THEN
        IF TG_OP = 'INSERT' THEN
            IF public.my_recent_rows('note', interval '1 hour') >= 100 THEN
                RAISE EXCEPTION 'Too many new notes in the last hour. Wait a while and try again.';
            END IF;
            IF public.my_recent_rows('note', interval '100 years') >= 2000 THEN
                RAISE EXCEPTION 'You have 2,000 notes, the most allowed. Delete some to add more.';
            END IF;
        ELSE
            NEW.created_at := OLD.created_at;
        END IF;

    ELSIF TG_TABLE_NAME = 'source_request' THEN
        IF TG_OP = 'INSERT' THEN
            NEW.requester_email := public.my_email();
            NEW.reviewed_by_email := CASE WHEN admin AND NEW.status <> 'pending' THEN public.my_email() END;
            IF NOT admin AND public.my_recent_rows('source_request', interval '1 day') >= 10 THEN
                RAISE EXCEPTION 'Too many source requests today. Try again tomorrow.';
            END IF;
        ELSE
            NEW.requester_email := OLD.requester_email;
            NEW.created_at := OLD.created_at;
            IF admin AND NEW.status IS DISTINCT FROM OLD.status AND NEW.status IN ('approved', 'rejected') THEN
                NEW.reviewed_by_email := public.my_email();
            ELSIF NOT admin THEN
                -- A requester may only withdraw (sql/security.sql); everything else stays as it was
                NEW.reason := OLD.reason;
                NEW.review_note := OLD.review_note;
                NEW.reviewed_by_email := OLD.reviewed_by_email;
                NEW.reviewed_at := OLD.reviewed_at;
            END IF;
        END IF;

    ELSIF TG_TABLE_NAME = 'audit_log' THEN
        NEW.user_email := public.my_email();
        IF NOT admin AND NEW.action NOT IN ('login', 'signup', 'source_request') THEN
            RAISE EXCEPTION 'Only an admin can record admin actions' USING ERRCODE = '42501';
        END IF;
        IF public.my_recent_rows('audit_log', interval '1 hour') >= 200 THEN
            RAISE EXCEPTION 'Too many actions in the last hour. Wait a while and try again.';
        END IF;
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS profile_stamp ON profile;
CREATE TRIGGER profile_stamp
    BEFORE UPDATE ON profile
    FOR EACH ROW EXECUTE FUNCTION public.stamp_website_write();

DROP TRIGGER IF EXISTS note_stamp ON note;
CREATE TRIGGER note_stamp
    BEFORE INSERT OR UPDATE ON note
    FOR EACH ROW EXECUTE FUNCTION public.stamp_website_write();

DROP TRIGGER IF EXISTS source_request_stamp ON source_request;
CREATE TRIGGER source_request_stamp
    BEFORE INSERT OR UPDATE ON source_request
    FOR EACH ROW EXECUTE FUNCTION public.stamp_website_write();

-- audit_log rows are never updated from the website (no update rule), so inserts only
DROP TRIGGER IF EXISTS audit_log_stamp ON audit_log;
CREATE TRIGGER audit_log_stamp
    BEFORE INSERT ON audit_log
    FOR EACH ROW EXECUTE FUNCTION public.stamp_website_write();
