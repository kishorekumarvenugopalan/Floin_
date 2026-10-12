import pathlib, subprocess, sys, json, os, shutil
ROOT = pathlib.Path(__file__).resolve().parent.parent
VEC = ROOT/"data/processed/vectors"
VEC_FALLBACK = ROOT/"data/vectors"
RAST = ROOT/"data/rasters"
RAST_COP = RAST/"rasters_COP30"
DB = os.environ.get("DATABASE_URL", "postgresql://floin:floin@localhost:5432/floin")
DB_PG = os.environ.get("PG_CONN", "host=localhost dbname=floin user=floin password=floin")

if os.name == "nt":
    # Auto-pick GDAL + PG client tools from common Windows installs
    # (QGIS ships ogr2ogr; EDB PostgreSQL ships psql; PostGIS adds raster2pgsql)
    qgis_bins = list(pathlib.Path("C:/Program Files").glob("QGIS*/bin"))
    pg_bins = (
        sorted(pathlib.Path("C:/Program Files/PostgreSQL").glob("*/bin"), reverse=True)
        + sorted(pathlib.Path("C:/Program Files (x86)/PostgreSQL").glob("*/bin"), reverse=True)
    )
    extra = ";".join([str(p) for p in qgis_bins + pg_bins if p.is_dir()])
    if extra:
        os.environ["PATH"] = extra + ";" + os.environ.get("PATH", "")

def need_tool(name):
    if not shutil.which(name):
        print(f"ERROR: required tool '{name}' not found in PATH")
        return False
    return True

def run(cmd, dry=False):
    """Run a command and report failure.

    A str goes through the shell (ogr2ogr and the raster2pgsql|psql pipeline need it).
    A list is executed directly, which is required for any command that *ends* in a
    quoted argument: cmd.exe strips the outermost quote pair of the whole line, so
    `psql "URL" -c "SQL"` arrives at psql as `-c SQL` split in two and the SQL is
    silently ignored ("extra command-line argument ... ignored").
    """
    printable = cmd if isinstance(cmd, str) else " ".join(
        f'"{c}"' if " " in str(c) else str(c) for c in cmd
    )
    print(f"$ {printable}")
    if dry: return True
    r=subprocess.run(cmd, shell=isinstance(cmd, str))
    if r.returncode != 0:
        print(f"WARN command failed with code {r.returncode}: {printable}")
    return r.returncode==0

def main(dry=False):
    print("[load_postgis] Module 3 -- Store & Organize")
    if dry: print("[dry-run] printing commands only")
    else:
        for tool in ["ogr2ogr","raster2pgsql","psql"]:
            need_tool(tool)
        # Options before the URL (psql <= 16 stops option parsing at the first positional
        # argument) and argv instead of a string, so the SQL survives cmd.exe quoting.
        psql = shutil.which("psql") or "psql"
        run([psql, "-c", "CREATE EXTENSION IF NOT EXISTS postgis;", DB], dry)
    vectors=[
        ("buildings","buildings.geojson"),
        ("highway","highway.geojson"),
        ("natural_water","natural_water.geojson"),
        ("waterway","waterway.geojson"),
        ("rainfall_stations","rainfall_stations.geojson"),
        ("chennai2015_inundation","chennai2015_inundation.geojson"),
        ("chennai2015_hotspots","chennai2015_hotspots.geojson"),
        ("chennai2015_flooded_streets","chennai2015_flooded_streets.geojson"),
        # 2026-10 dataset expansion — raw in data/vectors (no processed copy yet).
        # Keep in sync with floin_expected_layers (db/schema.sql) + db/bootstrap-load.sh.
        ("chennai_basin_buckingham_canal_map_1bb30ede","chennai_basin_buckingham_canal_map_1bb30ede.geojson"),
        ("chennai_basin_macro_drains_map_80b07b87","chennai_basin_macro_drains_map_80b07b87.geojson"),
        ("chennai_basin_micro_drains_map_4d6437e5","chennai_basin_micro_drains_map_4d6437e5.geojson"),
        ("chennai_basin_rivers_and_streams_map_9434de03","chennai_basin_rivers_and_streams_map_9434de03.geojson"),
        ("chennai_flood_hazard_zones_map_7f29da20","chennai_flood_hazard_zones_map_7f29da20.geojson"),
        ("chennai_flooding_points_in_2015_93d2905a","chennai_flooding_points_in_2015_93d2905a.geojson"),
        ("chennai_flows_10_years_return_period_1bfef958","chennai_flows_10_years_return_period_1bfef958.geojson"),
        ("chennai_flows_100_years_return_period_994a99a1","chennai_flows_100_years_return_period_994a99a1.geojson"),
        ("chennai_flows_200_years_return_period_61f1f06f","chennai_flows_200_years_return_period_61f1f06f.geojson"),
        ("chennai_flows_25_year_return_period_a6b4f2b1","chennai_flows_25_year_return_period_a6b4f2b1.geojson"),
        ("chennai_flows_50_years_return_period_a6b20b7c","chennai_flows_50_years_return_period_a6b20b7c.geojson"),
        ("chennai_flows_5_year_return_period_ef3286de","chennai_flows_5_year_return_period_ef3286de.geojson"),
        ("chennai_gcc_flood_extent_2005_c49407c8","chennai_gcc_flood_extent_2005_c49407c8.geojson"),
        ("chennai_gcc_flood_hostspots_2020_3a141c21","chennai_gcc_flood_hostspots_2020_3a141c21.geojson"),
        ("chennai_inundation_points_with_depth_of_inundation_814ca028","chennai_inundation_points_with_depth_of_inundation_814ca028.geojson"),
        ("chennai_neighbourhood_parks_map_81043b6d","chennai_neighbourhood_parks_map_81043b6d.geojson"),
        ("chennai_rivers_map_c6393f3d","chennai_rivers_map_c6393f3d.geojson"),
        ("chennai_slum_boundaries_map_5959f0f4","chennai_slum_boundaries_map_5959f0f4.geojson"),
        ("chennai_slums_map_02144a0c","chennai_slums_map_02144a0c.geojson"),
        ("chennai_storm_water_drains_swd_map_2023_c4907fed","chennai_storm_water_drains_swd_map_2023_c4907fed.geojson"),
        ("chennai_uchcs_map_a604ea86","chennai_uchcs_map_a604ea86.geojson"),
        ("chennai_uphcs_map_a33b403b","chennai_uphcs_map_a33b403b.geojson"),
        ("chennai_water_census_map_2023_7e357cf5","chennai_water_census_map_2023_7e357cf5.geojson"),
        ("chennai_waterbodies_map_2019_8d557090","chennai_waterbodies_map_2019_8d557090.geojson"),
        ("fl20151123ind_shp_ls8_20151014_preflood","fl20151123ind_shp_ls8_20151014_preflood.geojson"),
        ("fl20151123ind_shp_s1_20150901_preflood","fl20151123ind_shp_s1_20150901_preflood.geojson"),
        ("fl20151123ind_shp_s1_20151112_flood","fl20151123ind_shp_s1_20151112_flood.geojson"),
        ("fl20151123ind_shp_s1_20151124_flood","fl20151123ind_shp_s1_20151124_flood.geojson"),
        ("sewage_ventilating_columns_5d31106a","sewage_ventilating_columns_5d31106a.geojson"),
        ("sewerage_command_area_b186696c","sewerage_command_area_b186696c.geojson"),
    ]
    for table, fname in vectors:
        src = VEC/fname
        if not src.exists(): src = VEC_FALLBACK/fname
        if not src.exists():
            print(f"skip {fname} not found"); continue
        cmd = f'ogr2ogr -f PostgreSQL PG:"{DB_PG}" "{src}" -nln {table} -overwrite -lco GEOMETRY_NAME=geom -lco FID=id -lco SPATIAL_INDEX=GIST'
        run(cmd, dry)
    rasters={
        "dem": RAST_COP/"DEM.tif",
        "flow_direction": RAST/"Flow_Direction.tif",
        "flow_accumulation": RAST/"Flow_Accumulation.tif",
        "watershed": RAST/"Watershed.tif",
        "streams": RAST/"Streams.tif",
    }
    for table, src in rasters.items():
        if not src.exists():
            print(f"skip raster {table} not found: {src}"); continue
        cmd = f'raster2pgsql -s 4326 -I -C -M -t 256x256 "{src}" public.{table} | psql "{DB}"'
        run(cmd, dry)
    print("\nVector tables -> PostGIS geometry(geom), Raster tables -> raster(rast) + spatial index")
    print("Verify: psql floin -c \"\\d buildings; SELECT postgis_full_version();\"")

if __name__=="__main__":
    dry="--dry-run" in sys.argv or "-n" in sys.argv
    main(dry)
