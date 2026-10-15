-- FLOIN 003: vector reference layers. All geometries are stored in the model CRS,
-- EPSG:32644 (WGS 84 / UTM 44N), so lengths and areas are in metres.
-- Each row keeps its source feature id and original attributes for traceability.

CREATE TABLE floin.admin_boundaries (
    id            bigserial PRIMARY KEY,
    dataset_id    uuid NOT NULL REFERENCES floin.datasets(id) ON DELETE CASCADE,
    boundary_type text NOT NULL,
    code          text,
    name          text,
    zone          text,
    attributes    jsonb NOT NULL DEFAULT '{}'::jsonb,
    geom          geometry(MultiPolygon, 32644) NOT NULL
);

CREATE TABLE floin.buildings (
    id            bigserial PRIMARY KEY,
    dataset_id    uuid NOT NULL REFERENCES floin.datasets(id) ON DELETE CASCADE,
    source_id     text,
    building_type text,
    attributes    jsonb NOT NULL DEFAULT '{}'::jsonb,
    geom          geometry(MultiPolygon, 32644) NOT NULL
);

CREATE TABLE floin.roads (
    id          bigserial PRIMARY KEY,
    dataset_id  uuid NOT NULL REFERENCES floin.datasets(id) ON DELETE CASCADE,
    source_id   text,
    name        text,
    highway     text NOT NULL,
    attributes  jsonb NOT NULL DEFAULT '{}'::jsonb,
    geom        geometry(MultiLineString, 32644) NOT NULL
);

CREATE TABLE floin.railways (
    id          bigserial PRIMARY KEY,
    dataset_id  uuid NOT NULL REFERENCES floin.datasets(id) ON DELETE CASCADE,
    source_id   text,
    name        text,
    railway     text NOT NULL,
    is_metro    boolean NOT NULL DEFAULT false,
    attributes  jsonb NOT NULL DEFAULT '{}'::jsonb,
    geom        geometry(MultiLineString, 32644) NOT NULL
);

-- Rivers, streams and canals (natural and engineered open channels).
CREATE TABLE floin.rivers (
    id            bigserial PRIMARY KEY,
    dataset_id    uuid NOT NULL REFERENCES floin.datasets(id) ON DELETE CASCADE,
    source_id     text,
    name          text,
    waterway_type text NOT NULL,
    attributes    jsonb NOT NULL DEFAULT '{}'::jsonb,
    geom          geometry(MultiLineString, 32644) NOT NULL
);

-- Storm-water and basin drains.
CREATE TABLE floin.drainage (
    id          bigserial PRIMARY KEY,
    dataset_id  uuid NOT NULL REFERENCES floin.datasets(id) ON DELETE CASCADE,
    source_id   text,
    name        text,
    drain_class text NOT NULL,
    attributes  jsonb NOT NULL DEFAULT '{}'::jsonb,
    geom        geometry(MultiLineString, 32644) NOT NULL
);

CREATE TABLE floin.water_bodies (
    id          bigserial PRIMARY KEY,
    dataset_id  uuid NOT NULL REFERENCES floin.datasets(id) ON DELETE CASCADE,
    source_id   text,
    name        text,
    water_type  text,
    attributes  jsonb NOT NULL DEFAULT '{}'::jsonb,
    geom        geometry(MultiPolygon, 32644) NOT NULL
);

-- Observed floods (satellite extents, surveyed streets/points) and modelled design
-- floods (GCC return-period maps). Kept apart from model inputs: validation only.
CREATE TABLE floin.flood_references (
    id                  bigserial PRIMARY KEY,
    dataset_id          uuid NOT NULL REFERENCES floin.datasets(id) ON DELETE CASCADE,
    reference_type      text NOT NULL CHECK (reference_type IN ('observed', 'modelled_design')),
    event_name          text NOT NULL,
    event_date          date,
    return_period_years integer,
    observation_type    text NOT NULL CHECK (observation_type IN ('extent', 'street', 'point', 'depth_point')),
    depth_class         text,
    depth_min_m         double precision,
    depth_max_m         double precision,
    attributes          jsonb NOT NULL DEFAULT '{}'::jsonb,
    geom                geometry(Geometry, 32644) NOT NULL,
    CHECK (ST_SRID(geom) = 32644)
);
