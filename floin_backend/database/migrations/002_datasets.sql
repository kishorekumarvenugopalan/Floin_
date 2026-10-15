-- FLOIN 002: dataset catalog.
-- One row per dataset FLOIN knows about: where it is stored, its spatial reference,
-- coverage, value range, provenance and whether it is usable. Rejected placeholder
-- files are registered too (status = 'rejected') so their exclusion is documented.
CREATE TABLE floin.datasets (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name            text NOT NULL UNIQUE,
    title           text NOT NULL,
    dataset_type    text NOT NULL CHECK (dataset_type IN ('raster', 'vector')),
    category        text NOT NULL,
    stage           text NOT NULL CHECK (stage IN ('source', 'processed')),
    description     text,
    source          text,
    source_url      text,
    licence         text,
    format          text,
    storage_kind    text NOT NULL CHECK (storage_kind IN ('postgis', 'storage', 'none')),
    storage_path    text,
    table_name      text,
    crs             text,
    srid            integer,
    resolution_x    double precision,
    resolution_y    double precision,
    width           integer,
    height          integer,
    min_x           double precision,
    min_y           double precision,
    max_x           double precision,
    max_y           double precision,
    footprint       geometry(Polygon, 4326),
    dtype           text,
    nodata_value    double precision,
    min_value       double precision,
    max_value       double precision,
    feature_count   bigint,
    geometry_type   text,
    checksum_sha256 text,
    size_bytes      bigint,
    version         text NOT NULL DEFAULT '1',
    status          text NOT NULL CHECK (status IN ('available', 'limited', 'rejected', 'missing')),
    quality_notes   text,
    lineage         jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    CHECK (storage_kind <> 'postgis' OR table_name IS NOT NULL),
    CHECK (storage_kind <> 'storage' OR storage_path IS NOT NULL)
);

CREATE TRIGGER datasets_touch_updated_at
    BEFORE UPDATE ON floin.datasets
    FOR EACH ROW EXECUTE FUNCTION floin.touch_updated_at();
