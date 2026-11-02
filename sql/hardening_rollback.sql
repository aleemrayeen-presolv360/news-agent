-- Undo sql/hardening.sql. Supabase dashboard -> SQL Editor -> paste -> Run.
-- Leaves sql/security.sql (Row Level Security and the guards) in place. Deletes no rows.

DROP TRIGGER IF EXISTS profile_stamp ON profile;
DROP TRIGGER IF EXISTS note_stamp ON note;
DROP TRIGGER IF EXISTS source_request_stamp ON source_request;
DROP TRIGGER IF EXISTS audit_log_stamp ON audit_log;
DROP FUNCTION IF EXISTS public.stamp_website_write();
DROP FUNCTION IF EXISTS public.my_recent_rows(text, interval);
DROP FUNCTION IF EXISTS public.my_email();

ALTER TABLE source_request DROP CONSTRAINT IF EXISTS source_request_url_ok;
ALTER TABLE source_request DROP CONSTRAINT IF EXISTS source_request_text_ok;
ALTER TABLE source DROP CONSTRAINT IF EXISTS source_url_ok;
ALTER TABLE source DROP CONSTRAINT IF EXISTS source_text_ok;
ALTER TABLE note DROP CONSTRAINT IF EXISTS note_size_ok;
ALTER TABLE audit_log DROP CONSTRAINT IF EXISTS audit_log_size_ok;
ALTER TABLE profile DROP CONSTRAINT IF EXISTS profile_name_ok;

DROP INDEX IF EXISTS note_user_created_idx;
DROP INDEX IF EXISTS source_request_by_created_idx;
DROP INDEX IF EXISTS audit_log_user_created_idx;
