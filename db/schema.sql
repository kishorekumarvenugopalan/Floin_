-- FLOIN — canonical PostGIS schema (the shareable contract for this database).
--
-- Idempotent: safe to re-run against an existing database.
-- Used in two places, so the two paths can never drift:
--   1. docker compose up -d  -> mounted as /docker-entrypoint-initdb.d/10-floin-schema.sql
--   2. db/Dockerfile         -> COPY ed into the prebuilt ghcr.io image
--
-- Contract with the app (do not rename `geom`):
--   app/api/location/query/route.ts:90 and app/api/location/features/route.ts:14 run
--     SELECT ST_AsGeoJSON(geom)::json AS geometry, row_to_json(t) - 'geom' AS props
--       FROM <table> t
--      WHERE ST_Intersects(geom, ST_MakeEnvelope($1,$2,$3,$4,4326))
--   Vector tables therefore expose a column literally named `geom` in SRID 4326.
--
-- Geometry columns are declared generic `geometry(Geometry,4326)` on purpose:
-- data/vectors mixes Polygon/MultiPolygon and — per the note in
-- app/api/location/query/route.ts:55-57 — GeometryCollection is common in the GCC KML
-- exports. A narrower typmod would reject those rows. Dominant type per layer is
-- recorded in floin_expected_layers.geom_type instead.
--
-- The 2026-10 dataset expansion adds 30 raw layers from data/vectors (GCC/OSM/GEE
-- exports). Several of them mix Polygon + MultiPolygon + GeometryCollection inside a
-- single file — and chennai_gcc_flood_extent_2005, chennai_rivers_map and
-- chennai_slum_boundaries are GeometryCollection-only — so the generic typmod is what
-- makes these loadable at all.

CREATE EXTENSION IF NOT EXISTS postgis;

-- ---------------------------------------------------------------------------
-- 1. Registry — what this database is and what it is supposed to contain
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS floin_meta (
  key        text PRIMARY KEY,
  value      text NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);

INSERT INTO floin_meta (key, value) VALUES
  ('schema_version', '2'),
  ('crs',            'EPSG:4326'),
  ('generator',      'db/schema.sql'),
  ('data_root',      'data/vectors + data/rasters (see docs/DB_SHARING.md)')
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now();

-- Expected layers — mirrors scripts/load_postgis.py and db/bootstrap-load.sh (all
-- three lists are the same 38 layers; keep them in sync when adding data).
-- `scripts/db_share.py verify` diffs this against the live database, so a stale
-- dump or a skipped file shows up immediately instead of silently returning 0 rows.
CREATE TABLE IF NOT EXISTS floin_expected_layers (
  layer_name  text PRIMARY KEY,
  layer_role  text NOT NULL CHECK (layer_role IN ('vector', 'raster')),
  source_file text NOT NULL,
  geom_type   text NOT NULL
);

INSERT INTO floin_expected_layers (layer_name, layer_role, source_file, geom_type) VALUES
  ('buildings',                   'vector', 'buildings.geojson',                   'Polygon/MultiPolygon'),
  ('highway',                     'vector', 'highway.geojson',                     'LineString'),
  ('natural_water',               'vector', 'natural_water.geojson',               'Polygon'),
  ('waterway',                    'vector', 'waterway.geojson',                    'LineString'),
  ('rainfall_stations',           'vector', 'rainfall_stations.geojson',           'Point'),
  ('chennai2015_inundation',      'vector', 'chennai2015_inundation.geojson',      'Polygon/MultiPolygon'),
  ('chennai2015_hotspots',        'vector', 'chennai2015_hotspots.geojson',        'Point'),
  ('chennai2015_flooded_streets', 'vector', 'chennai2015_flooded_streets.geojson', 'LineString'),
  ('dem',                         'raster', 'rasters_COP30/DEM.tif',               'raster'),
  ('flow_direction',              'raster', 'Flow_Direction.tif',                  'raster'),
  ('flow_accumulation',           'raster', 'Flow_Accumulation.tif',               'raster'),
  ('watershed',                   'raster', 'Watershed.tif',                       'raster'),
  ('streams',                     'raster', 'Streams.tif',                         'raster'),
  -- 2026-10 expansion — raw layers living in data/vectors. The data pipeline has not
  -- produced data/processed/vectors copies for these yet, so scripts/load_postgis.py
  -- and db/bootstrap-load.sh fall back to the raw file (same `geom`/EPSG:4326 contract).
  -- Table name == file stem: the hash suffix is part of the source id, not decoration.
  ('chennai_basin_buckingham_canal_map_1bb30ede',       'vector', 'chennai_basin_buckingham_canal_map_1bb30ede.geojson',       'LineString/MultiLineString'),
  ('chennai_basin_macro_drains_map_80b07b87',           'vector', 'chennai_basin_macro_drains_map_80b07b87.geojson',           'LineString'),
  ('chennai_basin_micro_drains_map_4d6437e5',           'vector', 'chennai_basin_micro_drains_map_4d6437e5.geojson',           'LineString/MultiLineString'),
  ('chennai_basin_rivers_and_streams_map_9434de03',     'vector', 'chennai_basin_rivers_and_streams_map_9434de03.geojson',     'LineString/MultiLineString'),
  ('chennai_flood_hazard_zones_map_7f29da20',           'vector', 'chennai_flood_hazard_zones_map_7f29da20.geojson',           'Polygon/MultiPolygon/GeometryCollection'),
  ('chennai_flooding_points_in_2015_93d2905a',          'vector', 'chennai_flooding_points_in_2015_93d2905a.geojson',          'Point'),
  ('chennai_flows_10_years_return_period_1bfef958',     'vector', 'chennai_flows_10_years_return_period_1bfef958.geojson',     'Polygon/MultiPolygon/GeometryCollection'),
  ('chennai_flows_100_years_return_period_994a99a1',    'vector', 'chennai_flows_100_years_return_period_994a99a1.geojson',    'Polygon/MultiPolygon/GeometryCollection'),
  ('chennai_flows_200_years_return_period_61f1f06f',    'vector', 'chennai_flows_200_years_return_period_61f1f06f.geojson',    'Polygon/MultiPolygon/GeometryCollection'),
  ('chennai_flows_25_year_return_period_a6b4f2b1',      'vector', 'chennai_flows_25_year_return_period_a6b4f2b1.geojson',      'Polygon/MultiPolygon/GeometryCollection'),
  ('chennai_flows_50_years_return_period_a6b20b7c',     'vector', 'chennai_flows_50_years_return_period_a6b20b7c.geojson',     'Polygon/MultiPolygon/GeometryCollection'),
  ('chennai_flows_5_year_return_period_ef3286de',       'vector', 'chennai_flows_5_year_return_period_ef3286de.geojson',       'Polygon/MultiPolygon/GeometryCollection'),
  ('chennai_gcc_flood_extent_2005_c49407c8',            'vector', 'chennai_gcc_flood_extent_2005_c49407c8.geojson',            'GeometryCollection'),
  ('chennai_gcc_flood_hostspots_2020_3a141c21',         'vector', 'chennai_gcc_flood_hostspots_2020_3a141c21.geojson',         'Point'),
  ('chennai_inundation_points_with_depth_of_inundation_814ca028', 'vector', 'chennai_inundation_points_with_depth_of_inundation_814ca028.geojson', 'Point'),
  ('chennai_neighbourhood_parks_map_81043b6d',          'vector', 'chennai_neighbourhood_parks_map_81043b6d.geojson',          'Point'),
  ('chennai_rivers_map_c6393f3d',                       'vector', 'chennai_rivers_map_c6393f3d.geojson',                       'GeometryCollection'),
  ('chennai_slum_boundaries_map_5959f0f4',              'vector', 'chennai_slum_boundaries_map_5959f0f4.geojson',              'GeometryCollection'),
  ('chennai_slums_map_02144a0c',                        'vector', 'chennai_slums_map_02144a0c.geojson',                        'Point'),
  ('chennai_storm_water_drains_swd_map_2023_c4907fed',  'vector', 'chennai_storm_water_drains_swd_map_2023_c4907fed.geojson',  'LineString/MultiLineString'),
  ('chennai_uchcs_map_a604ea86',                        'vector', 'chennai_uchcs_map_a604ea86.geojson',                        'Point'),
  ('chennai_uphcs_map_a33b403b',                        'vector', 'chennai_uphcs_map_a33b403b.geojson',                        'Point'),
  ('chennai_water_census_map_2023_7e357cf5',            'vector', 'chennai_water_census_map_2023_7e357cf5.geojson',            'Point'),
  ('chennai_waterbodies_map_2019_8d557090',             'vector', 'chennai_waterbodies_map_2019_8d557090.geojson',             'GeometryCollection'),
  ('fl20151123ind_shp_ls8_20151014_preflood',           'vector', 'fl20151123ind_shp_ls8_20151014_preflood.geojson',           'Polygon'),
  ('fl20151123ind_shp_s1_20150901_preflood',            'vector', 'fl20151123ind_shp_s1_20150901_preflood.geojson',            'Polygon'),
  ('fl20151123ind_shp_s1_20151112_flood',               'vector', 'fl20151123ind_shp_s1_20151112_flood.geojson',               'Polygon'),
  ('fl20151123ind_shp_s1_20151124_flood',               'vector', 'fl20151123ind_shp_s1_20151124_flood.geojson',               'MultiPolygon/Polygon'),
  ('sewage_ventilating_columns_5d31106a',               'vector', 'sewage_ventilating_columns_5d31106a.geojson',               'Point'),
  ('sewerage_command_area_b186696c',                    'vector', 'sewerage_command_area_b186696c.geojson',                    'GeometryCollection')
ON CONFLICT (layer_name) DO UPDATE SET
  layer_role  = EXCLUDED.layer_role,
  source_file = EXCLUDED.source_file,
  geom_type   = EXCLUDED.geom_type;

-- ---------------------------------------------------------------------------
-- 2. Vector layer skeletons — empty, typed, indexed.
--    scripts/load_postgis.py / db/bootstrap-load.sh fill these with
--    `ogr2ogr … -lco GEOMETRY_NAME=geom -lco SPATIAL_INDEX=GIST`, which replaces
--    the table in place (same `geom` column, so the API contract holds either way).
-- ---------------------------------------------------------------------------

DO $$
DECLARE
  layer text;
  vector_layers text[] := ARRAY[
    'buildings', 'highway', 'natural_water', 'waterway', 'rainfall_stations',
    'chennai2015_inundation', 'chennai2015_hotspots', 'chennai2015_flooded_streets',
    -- 2026-10 expansion (see floin_expected_layers above)
    'chennai_basin_buckingham_canal_map_1bb30ede',
    'chennai_basin_macro_drains_map_80b07b87',
    'chennai_basin_micro_drains_map_4d6437e5',
    'chennai_basin_rivers_and_streams_map_9434de03',
    'chennai_flood_hazard_zones_map_7f29da20',
    'chennai_flooding_points_in_2015_93d2905a',
    'chennai_flows_10_years_return_period_1bfef958',
    'chennai_flows_100_years_return_period_994a99a1',
    'chennai_flows_200_years_return_period_61f1f06f',
    'chennai_flows_25_year_return_period_a6b4f2b1',
    'chennai_flows_50_years_return_period_a6b20b7c',
    'chennai_flows_5_year_return_period_ef3286de',
    'chennai_gcc_flood_extent_2005_c49407c8',
    'chennai_gcc_flood_hostspots_2020_3a141c21',
    'chennai_inundation_points_with_depth_of_inundation_814ca028',
    'chennai_neighbourhood_parks_map_81043b6d',
    'chennai_rivers_map_c6393f3d',
    'chennai_slum_boundaries_map_5959f0f4',
    'chennai_slums_map_02144a0c',
    'chennai_storm_water_drains_swd_map_2023_c4907fed',
    'chennai_uchcs_map_a604ea86',
    'chennai_uphcs_map_a33b403b',
    'chennai_water_census_map_2023_7e357cf5',
    'chennai_waterbodies_map_2019_8d557090',
    'fl20151123ind_shp_ls8_20151014_preflood',
    'fl20151123ind_shp_s1_20150901_preflood',
    'fl20151123ind_shp_s1_20151112_flood',
    'fl20151123ind_shp_s1_20151124_flood',
    'sewage_ventilating_columns_5d31106a',
    'sewerage_command_area_b186696c'
  ];
BEGIN
  FOREACH layer IN ARRAY vector_layers LOOP
    EXECUTE format(
      'CREATE TABLE IF NOT EXISTS public.%I ('
      '  id bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,'
      '  geom geometry(Geometry, 4326) NOT NULL,'
      '  loaded_at timestamptz NOT NULL DEFAULT now()'
      ')', layer);
    EXECUTE format(
      'CREATE INDEX IF NOT EXISTS %I ON public.%I USING GIST (geom)',
      layer || '_geom_gix', layer);
    EXECUTE format(
      'COMMENT ON TABLE public.%I IS %L',
      layer, 'FLOIN vector layer — ingested from data/vectors via ogr2ogr, EPSG:4326, geometry column "geom"');
  END LOOP;
END $$;

-- ---------------------------------------------------------------------------
-- 3. Ingest log — one row per load, written by the loader / image bootstrap
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS floin_ingest_log (
  id            bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
  table_name    text NOT NULL,
  layer_role    text NOT NULL CHECK (layer_role IN ('vector', 'raster')),
  source_file   text,
  feature_count bigint,
  loader        text,
  loaded_at     timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- 4. Report view — what `npm run db:verify` and the DB CI job read
-- ---------------------------------------------------------------------------

CREATE OR REPLACE VIEW floin_db_report AS
SELECT e.layer_name,
       e.layer_role,
       e.geom_type                  AS expected_geom_type,
       g.type                       AS actual_geom_type,
       g.srid,
       (g.f_table_name IS NOT NULL) AS table_present
  FROM floin_expected_layers e
  LEFT JOIN geometry_columns g
    ON g.f_table_schema = 'public'
   AND g.f_table_name   = e.layer_name
 ORDER BY e.layer_role, e.layer_name;

-- ---------------------------------------------------------------------------
-- 5. Shared-DB hygiene — a restored dump does not carry ownership. If the
--    application role exists (see .env.example: user `floin`), let it read
--    everything without taking ownership of the restored objects.
-- ---------------------------------------------------------------------------

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'floin') THEN
    EXECUTE 'GRANT USAGE ON SCHEMA public TO floin';
    EXECUTE 'GRANT SELECT ON ALL TABLES IN SCHEMA public TO floin';
    EXECUTE 'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO floin';
    RAISE NOTICE 'floin role present - granted read access to public schema';
  ELSE
    RAISE NOTICE 'floin role absent - skipped grants (create it, then re-run db/schema.sql)';
  END IF;
END $$;
