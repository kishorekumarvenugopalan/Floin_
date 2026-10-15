-- FLOIN 001: extensions and schema.
-- On Supabase, PostGIS is normally already enabled in the "extensions" schema;
-- IF NOT EXISTS makes this a no-op there.
CREATE EXTENSION IF NOT EXISTS postgis;

CREATE SCHEMA IF NOT EXISTS floin;

CREATE OR REPLACE FUNCTION floin.touch_updated_at() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;
