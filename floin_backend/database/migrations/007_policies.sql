-- FLOIN 007: access control.
-- The FastAPI backend connects as the database owner (Supabase "postgres" role),
-- which bypasses row level security. Browser clients must go through the API, so
-- RLS is enabled with no policies: Supabase anon/authenticated roles get nothing.
DO $$
DECLARE
    t record;
BEGIN
    FOR t IN SELECT tablename FROM pg_tables WHERE schemaname = 'floin' LOOP
        EXECUTE format('ALTER TABLE floin.%I ENABLE ROW LEVEL SECURITY', t.tablename);
    END LOOP;
END;
$$;

REVOKE ALL ON SCHEMA floin FROM PUBLIC;

DO $$
DECLARE
    r text;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA floin FROM %I', r);
            EXECUTE format('REVOKE ALL ON SCHEMA floin FROM %I', r);
        END IF;
    END LOOP;
END;
$$;
