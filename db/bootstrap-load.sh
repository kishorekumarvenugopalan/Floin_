#!/usr/bin/env bash
# FLOIN — first-boot data load for the prebuilt shared image (db/Dockerfile).
#
# Runs from /docker-entrypoint-initdb.d on the *first* boot of the container,
# against the freshly initialised cluster (temporary server on the local unix
# socket), before the real server starts listening.
#   vector layers -> ogr2ogr   (gdal-bin, installed by db/Dockerfile)
#   raster layers -> raster2pgsql (ships with postgis/postgis)
#
# Keep the two lists below in sync with scripts/load_postgis.py. The
# machine-readable copy of the same truth is floin_expected_layers in
# db/schema.sql, which `scripts/db_share.py verify` diffs against the live DB.

set -uo pipefail   # deliberately no -e: one missing/unreadable layer must not abort cluster init

DATA_VEC="${FLOIN_DATA_VECTORS:-/opt/floin/data/vectors}"
DATA_RAST="${FLOIN_DATA_RASTERS:-/opt/floin/data/rasters}"
PG_USER="${POSTGRES_USER:-floin}"
PG_DB="${POSTGRES_DB:-floin}"
PG_SOCKET="${PGHOST:-/var/run/postgresql}"
PGURI="host=${PG_SOCKET} user=${PG_USER} dbname=${PG_DB}"

log() { printf '[floin-load] %s\n' "$*"; }

psql_v() { psql --no-psqlrc -v ON_ERROR_STOP=1 -U "$PG_USER" -d "$PG_DB" "$@"; }

if [ "${FLOIN_SKIP_LOAD:-0}" = "1" ]; then
  log "FLOIN_SKIP_LOAD=1 — schema is applied, data load skipped (empty typed tables)"
  exit 0
fi

log "image bootstrap — vectors <- ${DATA_VEC}"

VECTORS=(
  buildings=buildings.geojson
  highway=highway.geojson
  natural_water=natural_water.geojson
  waterway=waterway.geojson
  rainfall_stations=rainfall_stations.geojson
  chennai2015_inundation=chennai2015_inundation.geojson
  chennai2015_hotspots=chennai2015_hotspots.geojson
  chennai2015_flooded_streets=chennai2015_flooded_streets.geojson
  # 2026-10 dataset expansion (raw data/vectors, see floin_expected_layers)
  chennai_basin_buckingham_canal_map_1bb30ede=chennai_basin_buckingham_canal_map_1bb30ede.geojson
  chennai_basin_macro_drains_map_80b07b87=chennai_basin_macro_drains_map_80b07b87.geojson
  chennai_basin_micro_drains_map_4d6437e5=chennai_basin_micro_drains_map_4d6437e5.geojson
  chennai_basin_rivers_and_streams_map_9434de03=chennai_basin_rivers_and_streams_map_9434de03.geojson
  chennai_flood_hazard_zones_map_7f29da20=chennai_flood_hazard_zones_map_7f29da20.geojson
  chennai_flooding_points_in_2015_93d2905a=chennai_flooding_points_in_2015_93d2905a.geojson
  chennai_flows_10_years_return_period_1bfef958=chennai_flows_10_years_return_period_1bfef958.geojson
  chennai_flows_100_years_return_period_994a99a1=chennai_flows_100_years_return_period_994a99a1.geojson
  chennai_flows_200_years_return_period_61f1f06f=chennai_flows_200_years_return_period_61f1f06f.geojson
  chennai_flows_25_year_return_period_a6b4f2b1=chennai_flows_25_year_return_period_a6b4f2b1.geojson
  chennai_flows_50_years_return_period_a6b20b7c=chennai_flows_50_years_return_period_a6b20b7c.geojson
  chennai_flows_5_year_return_period_ef3286de=chennai_flows_5_year_return_period_ef3286de.geojson
  chennai_gcc_flood_extent_2005_c49407c8=chennai_gcc_flood_extent_2005_c49407c8.geojson
  chennai_gcc_flood_hostspots_2020_3a141c21=chennai_gcc_flood_hostspots_2020_3a141c21.geojson
  chennai_inundation_points_with_depth_of_inundation_814ca028=chennai_inundation_points_with_depth_of_inundation_814ca028.geojson
  chennai_neighbourhood_parks_map_81043b6d=chennai_neighbourhood_parks_map_81043b6d.geojson
  chennai_rivers_map_c6393f3d=chennai_rivers_map_c6393f3d.geojson
  chennai_slum_boundaries_map_5959f0f4=chennai_slum_boundaries_map_5959f0f4.geojson
  chennai_slums_map_02144a0c=chennai_slums_map_02144a0c.geojson
  chennai_storm_water_drains_swd_map_2023_c4907fed=chennai_storm_water_drains_swd_map_2023_c4907fed.geojson
  chennai_uchcs_map_a604ea86=chennai_uchcs_map_a604ea86.geojson
  chennai_uphcs_map_a33b403b=chennai_uphcs_map_a33b403b.geojson
  chennai_water_census_map_2023_7e357cf5=chennai_water_census_map_2023_7e357cf5.geojson
  chennai_waterbodies_map_2019_8d557090=chennai_waterbodies_map_2019_8d557090.geojson
  fl20151123ind_shp_ls8_20151014_preflood=fl20151123ind_shp_ls8_20151014_preflood.geojson
  fl20151123ind_shp_s1_20150901_preflood=fl20151123ind_shp_s1_20150901_preflood.geojson
  fl20151123ind_shp_s1_20151112_flood=fl20151123ind_shp_s1_20151112_flood.geojson
  fl20151123ind_shp_s1_20151124_flood=fl20151123ind_shp_s1_20151124_flood.geojson
  sewage_ventilating_columns_5d31106a=sewage_ventilating_columns_5d31106a.geojson
  sewerage_command_area_b186696c=sewerage_command_area_b186696c.geojson
)

for pair in "${VECTORS[@]}"; do
  table="${pair%%=*}"
  file="${pair##*=}"
  src="${DATA_VEC}/${file}"
  if [ ! -f "$src" ]; then
    log "skip vector ${table} — ${file} not present in the image"
    continue
  fi
  log "ogr2ogr ${table} <- ${file}"
  if ogr2ogr -f PostgreSQL "PG:${PGURI}" "$src" \
      -nln "$table" -overwrite \
      -lco GEOMETRY_NAME=geom -lco FID=id -lco SPATIAL_INDEX=GIST; then
    psql_v -q -c "INSERT INTO floin_ingest_log (table_name, layer_role, source_file, loader)
                  VALUES ('${table}', 'vector', '${file}', 'db/bootstrap-load.sh');"
  else
    log "WARN ogr2ogr failed for ${table} (exit $?)"
  fi
done

log "image bootstrap — rasters <- ${DATA_RAST}"

RASTERS=(
  dem=rasters_COP30/DEM.tif
  flow_direction=Flow_Direction.tif
  flow_accumulation=Flow_Accumulation.tif
  watershed=Watershed.tif
  streams=Streams.tif
)

for pair in "${RASTERS[@]}"; do
  table="${pair%%=*}"
  file="${pair##*=}"
  src="${DATA_RAST}/${file}"
  if [ ! -f "$src" ]; then
    log "skip raster ${table} — ${file} not present in the image"
    continue
  fi
  log "raster2pgsql ${table} <- ${file}"
  if raster2pgsql -s 4326 -I -C -M -t 256x256 "$src" "public.${table}" \
      | psql --no-psqlrc -q -U "$PG_USER" -d "$PG_DB"; then
    psql_v -q -c "INSERT INTO floin_ingest_log (table_name, layer_role, source_file, loader)
                  VALUES ('${table}', 'raster', '${file}', 'db/bootstrap-load.sh');"
  else
    log "WARN raster2pgsql failed for ${table}"
  fi
done

log "done — report:"
psql_v -c "SELECT layer_role, layer_name, table_present, actual_geom_type, srid FROM floin_db_report;"
log "raster tables are not part of floin_db_report (they are not in geometry_columns);"
log "check them with: SELECT r_table_name FROM raster_columns WHERE r_table_schema='public';"
