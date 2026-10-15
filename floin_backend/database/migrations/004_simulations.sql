-- FLOIN 004: simulation runs, their exact inputs, generated outputs and results.

CREATE TABLE floin.simulation_runs (
    id                text PRIMARY KEY,
    status            text NOT NULL CHECK (status IN ('queued', 'running', 'completed', 'failed')),
    scenario          text NOT NULL,
    rainfall_source   text NOT NULL CHECK (rainfall_source IN ('uniform', 'dataset')),
    rainfall_mm       double precision,
    rainfall_dataset  text,
    duration_hours    double precision NOT NULL CHECK (duration_hours > 0),
    parameters        jsonb NOT NULL,
    model_version     text NOT NULL,
    current_stage     text,
    error             text,
    runtime_seconds   double precision,
    created_at        timestamptz NOT NULL DEFAULT now(),
    started_at        timestamptz,
    completed_at      timestamptz
);

-- Which catalog datasets (and which file checksums) a run consumed: makes runs reproducible.
CREATE TABLE floin.simulation_inputs (
    simulation_id   text NOT NULL REFERENCES floin.simulation_runs(id) ON DELETE CASCADE,
    role            text NOT NULL,
    dataset_id      uuid NOT NULL REFERENCES floin.datasets(id),
    dataset_name    text NOT NULL,
    dataset_version text NOT NULL,
    checksum_sha256 text,
    PRIMARY KEY (simulation_id, role)
);

CREATE TABLE floin.simulation_outputs (
    id              bigserial PRIMARY KEY,
    simulation_id   text NOT NULL REFERENCES floin.simulation_runs(id) ON DELETE CASCADE,
    name            text NOT NULL,
    storage_path    text NOT NULL,
    format          text NOT NULL,
    size_bytes      bigint,
    checksum_sha256 text,
    stats           jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (simulation_id, name)
);

CREATE TABLE floin.simulation_results (
    simulation_id text PRIMARY KEY REFERENCES floin.simulation_runs(id) ON DELETE CASCADE,
    hydrology     jsonb NOT NULL,
    terrain       jsonb NOT NULL,
    flood         jsonb NOT NULL,
    exposure      jsonb NOT NULL,
    hazard        jsonb NOT NULL,
    risk          jsonb NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now()
);

-- Flood extent polygonised by depth class (1 = lowest configured class).
CREATE TABLE floin.simulation_flood_polygons (
    id            bigserial PRIMARY KEY,
    simulation_id text NOT NULL REFERENCES floin.simulation_runs(id) ON DELETE CASCADE,
    depth_class   smallint NOT NULL,
    geom          geometry(Polygon, 32644) NOT NULL
);

CREATE TABLE floin.simulation_ward_summary (
    simulation_id      text NOT NULL REFERENCES floin.simulation_runs(id) ON DELETE CASCADE,
    boundary_id        bigint NOT NULL REFERENCES floin.admin_boundaries(id) ON DELETE CASCADE,
    flooded_area_m2    double precision NOT NULL,
    buildings_affected integer NOT NULL,
    road_length_m      double precision NOT NULL,
    PRIMARY KEY (simulation_id, boundary_id)
);
