-- News Intel website tables (Supabase).
--
-- The live project already has these. This file documents them and lets you
-- recreate them in a new Supabase project: Supabase dashboard -> SQL Editor -> run.
-- It was written from what the website reads and writes; check column types
-- against your live project before relying on it for a migration.
--
-- Row Level Security is OFF on these tables (a deliberate choice for now).
-- That means anyone with the public anon key can read them. See README,
-- "Security notes", before storing anything sensitive.

-- One row per signed-up person. Created automatically by the trigger below.
CREATE TABLE IF NOT EXISTS profile (
    id          UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    email       TEXT,
    name        TEXT,
    role        TEXT NOT NULL DEFAULT 'user',      -- 'user' (Member) or 'admin'
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Notes written on the Notes screen. content is HTML from the editor.
CREATE TABLE IF NOT EXISTS note (
    id          BIGSERIAL PRIMARY KEY,
    user_id     UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    title       TEXT,
    content     TEXT,
    color       TEXT DEFAULT '#ffffff',            -- kept for old notes; the new UI doesn't show it
    pinned      BOOLEAN NOT NULL DEFAULT false,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS note_user_idx ON note (user_id, updated_at DESC);

-- Source list shown in Settings. enabled = false hides a source's stories for everyone.
-- Note: the news pipeline does NOT read this table; it uses agent/sources.py.
CREATE TABLE IF NOT EXISTS source (
    id          BIGSERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    url         TEXT NOT NULL,
    category    TEXT NOT NULL,                     -- tech | legal | market | competitors
    enabled     BOOLEAN NOT NULL DEFAULT true,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- News sources members asked for. An admin approves or rejects each one in
-- Settings > Source requests. The news pipeline (agent/ingest.py) fetches every
-- approved row on each run, so approving is what actually adds a feed.
-- An admin's own "Add source" is stored here too, already approved.
CREATE TABLE IF NOT EXISTS source_request (
    id                BIGSERIAL PRIMARY KEY,
    name              TEXT NOT NULL,
    url               TEXT NOT NULL,
    category          TEXT NOT NULL,               -- tech | legal | market | competitors
    reason            TEXT,                        -- why the requester wants it
    status            TEXT NOT NULL DEFAULT 'pending'
                      CHECK (status IN ('pending', 'approved', 'rejected', 'withdrawn')),
    requested_by      UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    requester_email   TEXT,
    review_note       TEXT,                        -- the admin's reason, shown to the requester
    reviewed_by_email TEXT,
    reviewed_at       TIMESTAMPTZ,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- One open or approved request per feed; a rejected feed can be asked for again
CREATE UNIQUE INDEX IF NOT EXISTS source_request_url_open
    ON source_request (lower(url)) WHERE status IN ('pending', 'approved');

-- Admin actions and sign-ins, shown in Settings > Audit log.
CREATE TABLE IF NOT EXISTS audit_log (
    id          BIGSERIAL PRIMARY KEY,
    user_id     UUID,
    user_email  TEXT,
    action      TEXT NOT NULL,                     -- login | signup | source_add | source_toggle | user_role
    details     TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Per-user preferences. Exists in the live project but the website does not use it yet
-- (preferences are kept in the browser for now).
CREATE TABLE IF NOT EXISTS user_setting (
    user_id     UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    preferences JSONB NOT NULL DEFAULT '{}'
);

-- Create a profile row whenever someone signs up. The name comes from the sign-up form.
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER SET search_path = public
AS $$
BEGIN
    INSERT INTO public.profile (id, email, name)
    VALUES (NEW.id, NEW.email, NEW.raw_user_meta_data ->> 'name')
    ON CONFLICT (id) DO NOTHING;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();

-- Make someone an admin (replace the email):
-- UPDATE profile SET role = 'admin' WHERE email = 'someone@example.com';

-- ---------------------------------------------------------------- write guards
-- RLS is off, so anyone with the public anon key can write to these tables. These
-- triggers block the writes that matter: a member making someone an admin, and a
-- member approving or rejecting a source request. Reading is not affected.
-- Only website requests are checked (roles 'anon' and 'authenticated'); the SQL
-- Editor and the service role are not, so the UPDATE above still works there.

-- Is the signed-in person an admin? SECURITY DEFINER so it can read profile safely
-- from inside the guards.
CREATE OR REPLACE FUNCTION public.is_admin()
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER SET search_path = public
AS $$
    SELECT EXISTS (SELECT 1 FROM profile WHERE id = auth.uid() AND role = 'admin');
$$;

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
