"""Load the real FLOIN vector layers into PostGIS and register them in floin.datasets.

Pipeline per dataset:
  source file -> read -> validate (non-empty, CRS) -> drop empty geometries -> repair
  (make_valid) -> coerce to the table's geometry type -> reproject to EPSG:32644 ->
  keep features intersecting the model area (optionally clip) -> COPY into PostGIS ->
  recompute catalog stats from the database -> verify (count, SRID, type, validity, extent)

Reloading a dataset replaces its rows (same catalog id). Files judged to be placeholders
are registered with status 'rejected' and are never loaded.

Usage:
  python scripts/load_vectors.py              # all datasets
  python scripts/load_vectors.py roads wards  # selected dataset names
  python scripts/load_vectors.py --list
"""
import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app  # noqa: F401
import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from sqlalchemy import text

from app.core.config import MODEL_AREA_WGS84, get_settings
from app.core.errors import DataValidationError, DatasetMissingError
from app.core.logging import configure_logging, get_logger
from app.db.database import connect
from app.db.repositories import refresh_vector_stats, upsert_dataset
from app.gis.raster import sha256_file
from app.gis.vector import LINEAR, POLYGONAL, coerce_geometry, model_area_box, read_osm_extract, read_vector

log = get_logger("load_vectors")
SRID = 32644

TABLE_COLUMNS = {
    "admin_boundaries": ["boundary_type", "code", "name", "zone"],
    "buildings": ["source_id", "building_type"],
    "roads": ["source_id", "name", "highway"],
    "railways": ["source_id", "name", "railway", "is_metro"],
    "rivers": ["source_id", "name", "waterway_type"],
    "drainage": ["source_id", "name", "drain_class"],
    "water_bodies": ["source_id", "name", "water_type"],
    "flood_references": ["reference_type", "event_name", "event_date", "return_period_years",
                         "observation_type", "depth_class", "depth_min_m", "depth_max_m"],
}
TABLE_GEOMETRY = {
    "admin_boundaries": POLYGONAL, "buildings": POLYGONAL, "water_bodies": POLYGONAL,
    "roads": LINEAR, "railways": LINEAR, "rivers": LINEAR, "drainage": LINEAR,
    "flood_references": None,
}

FT = 0.3048
HOTSPOT_DEPTHS = {  # GCC 2015 hotspot inundation classes, feet -> metres
    "<2ft": ("<2 ft", 0.0, 2 * FT),
    "2 to 3 ft": ("2-3 ft", 2 * FT, 3 * FT),
    "3 to 5 ft": ("3-5 ft", 3 * FT, 5 * FT),
    ">5ft": (">5 ft", 5 * FT, None),
}
METRO_RAILWAY_TYPES = {"subway", "light_rail", "monorail"}


@dataclass
class VectorDataset:
    name: str
    title: str
    category: str
    table: str
    files: list[str]
    source: str
    licence: str | None
    builder: Callable[[dict], dict]
    source_url: str | None = None
    osm_kind: str | None = None          # "line" / "polygon" for Overpass extracts
    clip: bool = False                   # clip geometries to the model area
    status: str = "available"
    quality_notes: str | None = None
    row_filter: Callable[[dict], bool] = field(default=lambda props: True)
    geometry: str | None = None          # overrides the table's geometry target

    @property
    def target_geometry(self):
        return self.geometry or TABLE_GEOMETRY[self.table]


def osm_tags(props):
    return props.get("tags") or {}


def ward_row(p):
    return {"boundary_type": "gcc_ward", "code": str(p.get("Ward_No")), "name": f"Ward {p.get('Ward_No')}",
            "zone": p.get("Zone_Name")}


def osm_road_row(p):
    tags = osm_tags(p)
    return {"source_id": p["source_id"], "name": tags.get("name"), "highway": tags["highway"]}


def osm_railway_row(p):
    tags = osm_tags(p)
    operator = (tags.get("operator") or "") + " " + (tags.get("name") or "")
    is_metro = tags.get("railway") in METRO_RAILWAY_TYPES or "metro" in operator.lower() or "cmrl" in operator.lower()
    return {"source_id": p["source_id"], "name": tags.get("name"), "railway": tags["railway"], "is_metro": is_metro}


def osm_building_row(p):
    return {"source_id": p["source_id"], "building_type": osm_tags(p).get("building")}


def named(kind_field, kind_value):
    return lambda p: {"source_id": None, "name": p.get("name"), kind_field: kind_value}


def river_row(p):
    name = (p.get("name") or "")
    lowered = name.lower()
    kind = "river" if "river" in lowered or lowered.startswith("r.") else "channel" if name else "stream"
    return {"source_id": None, "name": p.get("name") or None, "waterway_type": kind}


def osm_water_row(p):
    return {"source_id": p.get("full_id") or p.get("osm_id"), "name": p.get("name"),
            "water_type": p.get("water") or p.get("natural") or p.get("landuse")}


def flood_ref(reference_type, event, observation, event_date=None, return_period=None):
    def build(p):
        return {"reference_type": reference_type, "event_name": event, "event_date": event_date,
                "return_period_years": return_period, "observation_type": observation,
                "depth_class": None, "depth_min_m": None, "depth_max_m": None}
    return build


def hotspot_row(p):
    label, lo, hi = HOTSPOT_DEPTHS[p["inundation_ft"]]
    return {"reference_type": "observed", "event_name": "chennai_2015_dec", "event_date": None,
            "return_period_years": None, "observation_type": "depth_point",
            "depth_class": label, "depth_min_m": lo, "depth_max_m": hi}


GCC_OPENCITY = "Greater Chennai Corporation via OpenCity (data.opencity.in)"
DATASETS = [
    VectorDataset("wards_gcc", "Greater Chennai Corporation wards (200)", "admin_boundaries", "admin_boundaries",
                  ["chennai_wards_200.geojson"], "Greater Chennai Corporation (supplied project file)", None, ward_row,
                  quality_notes="201 polygons, unique Ward_No. AREA/PERIMETER attributes are in degrees and kept only as source attributes."),
    VectorDataset("osm_buildings", "OpenStreetMap building footprints", "buildings", "buildings",
                  ["osm/osm_buildings_chennai.json.gz"], "OpenStreetMap contributors", "ODbL 1.0", osm_building_row,
                  source_url="https://overpass-api.de", osm_kind="polygon", status="limited",
                  quality_notes="Volunteered data with uneven completeness: median 808 buildings/km2 per GCC ward, "
                                "but 59 of 201 wards have < 500/km2 (10th percentile 25/km2). Building exposure "
                                "counts are lower bounds."),
    VectorDataset("osm_roads", "OpenStreetMap road network (vehicle roads)", "roads", "roads",
                  ["osm/osm_roads_chennai.json.gz"], "OpenStreetMap contributors", "ODbL 1.0", osm_road_row,
                  source_url="https://overpass-api.de", osm_kind="line"),
    VectorDataset("osm_railways", "OpenStreetMap railways, suburban rail and metro", "railways", "railways",
                  ["osm/osm_railways_chennai.json.gz"], "OpenStreetMap contributors", "ODbL 1.0", osm_railway_row,
                  source_url="https://overpass-api.de", osm_kind="line"),
    VectorDataset("gcc_basin_rivers", "Chennai basin rivers, streams and surplus channels", "rivers", "rivers",
                  ["chennai_basin_rivers_and_streams_map_9434de03.geojson"], GCC_OPENCITY, None, river_row),
    VectorDataset("gcc_buckingham_canal", "Buckingham Canal", "rivers", "rivers",
                  ["chennai_basin_buckingham_canal_map_1bb30ede.geojson"], GCC_OPENCITY, None, named("waterway_type", "canal")),
    VectorDataset("gcc_storm_water_drains_2023", "GCC storm water drains (SWD map 2023)", "drainage", "drainage",
                  ["chennai_storm_water_drains_swd_map_2023_c4907fed.geojson"], GCC_OPENCITY, None,
                  named("drain_class", "storm_water_drain"),
                  quality_notes="Geometry only: no capacity, size or invert levels in the source."),
    VectorDataset("gcc_basin_macro_drains", "Chennai basin macro drains", "drainage", "drainage",
                  ["chennai_basin_macro_drains_map_80b07b87.geojson"], GCC_OPENCITY, None, named("drain_class", "macro_drain")),
    VectorDataset("gcc_basin_micro_drains", "Chennai basin micro drains", "drainage", "drainage",
                  ["chennai_basin_micro_drains_map_4d6437e5.geojson"], GCC_OPENCITY, None, named("drain_class", "micro_drain")),
    VectorDataset("osm_natural_water", "OpenStreetMap water bodies", "water_bodies", "water_bodies",
                  ["natural_water.geojson"], "OpenStreetMap contributors (supplied project file)", "ODbL 1.0", osm_water_row),
    VectorDataset("gcc_waterbodies_2019", "GCC water bodies map 2019", "water_bodies", "water_bodies",
                  ["chennai_waterbodies_map_2019_8d557090.geojson"], GCC_OPENCITY, None,
                  lambda p: {"source_id": None, "name": None, "water_type": "waterbody"}),
    # Flood references (validation only)
    VectorDataset("flood_2015_inundation", "Chennai December 2015 observed inundation extent", "historical_flood",
                  "flood_references", ["chennai2015_inundation.geojson"], "Supplied project file (provenance undocumented)", None,
                  flood_ref("observed", "chennai_2015_dec", "extent"), clip=True, geometry=POLYGONAL, status="limited",
                  quality_notes="4001 polygons with no attributes; producer and observation date are not documented."),
    VectorDataset("flood_2015_unosat_s1_20151112", "UNOSAT Sentinel-1 flood extent 2015-11-12 (FL20151123IND)",
                  "historical_flood", "flood_references", ["fl20151123ind_shp_s1_20151112_flood.geojson"],
                  "UNITAR-UNOSAT via HDX", "UNOSAT terms of use", flood_ref("observed", "chennai_2015_nov12", "extent", "2015-11-12"),
                  clip=True, geometry=POLYGONAL),
    VectorDataset("flood_2015_unosat_s1_20151124", "UNOSAT Sentinel-1 flood extent 2015-11-24 (FL20151123IND)",
                  "historical_flood", "flood_references", ["fl20151123ind_shp_s1_20151124_flood.geojson"],
                  "UNITAR-UNOSAT via HDX", "UNOSAT terms of use", flood_ref("observed", "chennai_2015_nov24", "extent", "2015-11-24"),
                  clip=True, geometry=POLYGONAL),
    VectorDataset("flood_2015_flooded_streets", "Chennai 2015 crowd-mapped flooded streets", "historical_flood",
                  "flood_references", ["chennai2015_flooded_streets.geojson"], "Supplied project file (OSM-based crowd map)", None,
                  flood_ref("observed", "chennai_2015_dec", "street"), geometry=LINEAR, status="limited",
                  row_filter=lambda p: str(p.get("is_flooded")) == "1",
                  quality_notes="Only segments with is_flooded = 1 are loaded (7884 of 7894)."),
    VectorDataset("flood_2015_gcc_hotspots", "GCC 2015 flood hotspots with inundation depth class", "historical_flood",
                  "flood_references", ["chennai2015_hotspots.geojson"], "Greater Chennai Corporation (supplied project file)", None,
                  hotspot_row),
    VectorDataset("flood_2015_gcc_stagnation", "GCC 2015 water stagnation points", "historical_flood",
                  "flood_references", ["chennai2015_stagnation.geojson"], "Greater Chennai Corporation (supplied project file)", None,
                  flood_ref("observed", "chennai_2015_dec", "point")),
    VectorDataset("flood_2005_gcc_extent", "GCC 2005 flood extent", "historical_flood", "flood_references",
                  ["chennai_gcc_flood_extent_2005_c49407c8.geojson"], GCC_OPENCITY, None,
                  flood_ref("observed", "chennai_2005", "extent"), clip=True, geometry=POLYGONAL),
    VectorDataset("gcc_flood_hazard_zones", "GCC flood hazard zones map", "design_flood", "flood_references",
                  ["chennai_flood_hazard_zones_map_7f29da20.geojson"], GCC_OPENCITY, None,
                  flood_ref("modelled_design", "gcc_flood_hazard_zones", "extent"), clip=True, geometry=POLYGONAL),
] + [
    VectorDataset(f"gcc_design_flood_{rp}y", f"GCC modelled flood extent, {rp}-year return period", "design_flood",
                  "flood_references", [f], GCC_OPENCITY, None,
                  flood_ref("modelled_design", f"gcc_design_flood_{rp}y", "extent", None, rp), clip=True,
                  geometry=POLYGONAL)
    for rp, f in [(5, "chennai_flows_5_year_return_period_ef3286de.geojson"),
                  (10, "chennai_flows_10_years_return_period_1bfef958.geojson"),
                  (25, "chennai_flows_25_year_return_period_a6b4f2b1.geojson"),
                  (50, "chennai_flows_50_years_return_period_a6b20b7c.geojson"),
                  (100, "chennai_flows_100_years_return_period_994a99a1.geojson"),
                  (200, "chennai_flows_200_years_return_period_61f1f06f.geojson")]
]

# Supplied files that are placeholders or unusable. Registered so the exclusion is on record.
REJECTED = {
    "chennai_lulc.geojson": ("landcover", "5 hand-drawn rectangles with typed-in CN values; replaced by ESA WorldCover 2021"),
    "chennai_soil.geojson": ("soil", "3 rectangles with an invented cn_factor and no hydrologic soil group; replaced by SoilGrids-derived HSG"),
    "chennai_soil_infiltration.geojson": ("soil", "3 identical squares with no attributes"),
    "chennai_drainage.geojson": ("drainage", "5 hand-drawn lines with invented capacity_cusecs"),
    "chennai_sentinel1_flood_extent.geojson": ("historical_flood", "single rectangle labelled 264 km2; real UNOSAT Sentinel-1 extents are used instead"),
    "chennai_building_flooddepth_2015.geojson": ("historical_flood", "3 identical 0.005 deg squares"),
    "chennai_ward_flooddepth_2015.geojson": ("historical_flood", "3 identical 0.005 deg squares"),
    "chennai_economic_losses_2015.geojson": ("historical_flood", "3 identical 0.005 deg squares"),
    "chennai_catchment_response.geojson": ("catchments", "3 identical 0.005 deg squares"),
    "chennai_river_cross_sections.geojson": ("rivers", "6 two-point lines on round coordinates with generic Manning n"),
    "chennai_river_gauge_adyar.geojson": ("gauges", "generated points named '... 1/2/3' without observations"),
    "chennai_river_gauge_cooum.geojson": ("gauges", "generated points without observations"),
    "chennai_river_gauge_kosasthalaiyar.geojson": ("gauges", "generated points without observations"),
    "chennai_hospitals_relief.geojson": ("infrastructure", "12 points with 15-decimal random coordinates and template attributes"),
    "chennai_fire_stations.geojson": ("infrastructure", "4 generated points named 'chennai_fire_stations 1..4'"),
    "chennai_police_stations.geojson": ("infrastructure", "4 generated points"),
    "rainfall_stations.geojson": ("rainfall", "8 points, one date (2024-12-03), non-standard cn_zone field; provenance unverified"),
    "chennai_population_grid_100m.geojson": ("population", "invalid GeoJSON (no features member)"),
    "highway.geojson": ("roads", "28 OSM pedestrian-area polygons, not a road network; replaced by OSM road extract"),
    "buildings.geojson": ("buildings", "1811 OSM building relations only; superseded by full OSM building extract"),
}


def resolve_source(relative: str) -> Path:
    settings = get_settings()
    candidates = [settings.raw_dir / relative] + [d / relative for d in settings.vector_source_dirs]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise DatasetMissingError(f"Source file not found: {relative}", searched=[str(c) for c in candidates])


def json_safe(value):
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if np.isnan(value) else float(value)
    if isinstance(value, float) and np.isnan(value):
        return None
    if isinstance(value, (dict, list, str, int, float, bool)) or value is None:
        return value
    return str(value)


def prepare(ds: VectorDataset) -> tuple[gpd.GeoDataFrame, dict]:
    paths = [resolve_source(f) for f in ds.files]
    frames, lineage = [], {"sources": [], "steps": []}
    for path in paths:
        gdf = read_osm_extract(path, ds.osm_kind) if ds.osm_kind else read_vector(path)
        lineage["sources"].append({"file": path.name, "sha256": sha256_file(path), "features": len(gdf),
                                   "crs": str(gdf.crs), "osm_base": gdf.attrs.get("osm_base")})
        frames.append(gdf)
    gdf = frames[0] if len(frames) == 1 else gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs=frames[0].crs)
    if len(gdf) == 0:
        raise DataValidationError(f"{ds.name}: source has no features")

    n_source = len(gdf)
    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()
    n_with_geom = len(gdf)
    props = [{k: json_safe(v) for k, v in row.items() if k != "geometry"} for row in gdf.to_dict("records")]
    keep = [ds.row_filter(p) for p in props]
    gdf, props = gdf[keep].copy(), [p for p, k in zip(props, keep) if k]
    n_filtered = len(gdf)

    gdf = gdf.to_crs(SRID)
    target = ds.target_geometry
    gdf["geometry"] = [coerce_geometry(g, target) for g in gdf.geometry]
    usable = gdf.geometry.notna().to_numpy()
    gdf, props = gdf[usable].copy(), [p for p, u in zip(props, usable) if u]

    area = model_area_box(MODEL_AREA_WGS84, f"EPSG:{SRID}")
    inside = gdf.geometry.intersects(area).to_numpy()
    gdf, props = gdf[inside].copy(), [p for p, i in zip(props, inside) if i]
    if ds.clip:
        gdf["geometry"] = [coerce_geometry(g.intersection(area), target) for g in gdf.geometry]
        ok = gdf.geometry.notna().to_numpy()
        gdf, props = gdf[ok].copy(), [p for p, k in zip(props, ok) if k]

    rows = []
    for geom, p in zip(gdf.geometry, props):
        columns = ds.builder(p)
        attributes = {k: v for k, v in p.items() if k not in ("tags",)}
        attributes.update(p.get("tags") or {})
        rows.append((columns, attributes, geom))
    lineage["steps"] = [
        f"read {n_source} features", f"{n_source - n_with_geom} without geometry dropped",
        f"{n_with_geom - n_filtered} removed by row filter", "make_valid + coerce to " + (target or "source type"),
        f"reprojected to EPSG:{SRID}", f"{len(rows)} intersect the model area" + (" (clipped)" if ds.clip else ""),
    ]
    if not rows:
        raise DataValidationError(f"{ds.name}: no usable features inside the model area")
    return rows, lineage


def copy_rows(conn, table: str, dataset_id: str, rows) -> None:
    columns = ["dataset_id"] + TABLE_COLUMNS[table] + ["attributes", "geom"]
    cursor = conn.connection.dbapi_connection.cursor()
    with cursor.copy(f"COPY floin.{table} ({', '.join(columns)}) FROM STDIN") as copy:
        for values, attributes, geom in rows:
            ewkb = shapely.to_wkb(shapely.set_srid(geom, SRID), hex=True, include_srid=True)
            copy.write_row([dataset_id] + [values.get(c) for c in TABLE_COLUMNS[table]]
                           + [json.dumps(attributes, default=str), ewkb])


def verify(conn, ds: VectorDataset, dataset_id: str, expected: int) -> dict:
    stats = refresh_vector_stats(conn, dataset_id, ds.table)
    problems = []
    if stats["n"] != expected:
        problems.append(f"row count {stats['n']} != {expected}")
    if stats["srids"] != [SRID]:
        problems.append(f"SRIDs {stats['srids']}")
    if stats["invalid"]:
        problems.append(f"{stats['invalid']} invalid geometries")
    expected_type = ds.target_geometry
    if expected_type and stats["types"] != expected_type.upper():
        problems.append(f"geometry types {stats['types']}")
    hit = conn.execute(text(f"""
        SELECT count(*) FROM floin.{ds.table}
        WHERE dataset_id = :id AND ST_Intersects(geom, ST_Transform(ST_MakeEnvelope(:w, :s, :e, :n, 4326), {SRID}))
    """), {"id": dataset_id, "w": MODEL_AREA_WGS84[0], "s": MODEL_AREA_WGS84[1],
           "e": MODEL_AREA_WGS84[2], "n": MODEL_AREA_WGS84[3]}).scalar_one()
    if hit != expected:
        problems.append(f"spatial query found {hit} of {expected} features in the model area")
    if problems:
        raise DataValidationError(f"{ds.name} failed verification: " + "; ".join(problems))
    return stats


def load_dataset(ds: VectorDataset) -> dict:
    rows, lineage = prepare(ds)
    record = {
        "name": ds.name, "title": ds.title, "dataset_type": "vector", "category": ds.category, "stage": "processed",
        "source": ds.source, "source_url": ds.source_url, "licence": ds.licence,
        "format": "PostGIS table", "storage_kind": "postgis", "table_name": f"floin.{ds.table}",
        "crs": f"EPSG:{SRID}", "srid": SRID, "status": ds.status, "quality_notes": ds.quality_notes,
        "version": lineage["sources"][0]["sha256"][:12], "checksum_sha256": lineage["sources"][0]["sha256"],
        "lineage": lineage,
    }
    with connect() as conn:
        dataset_id = upsert_dataset(conn, record)
        conn.execute(text(f"DELETE FROM floin.{ds.table} WHERE dataset_id = :id"), {"id": dataset_id})
        copy_rows(conn, ds.table, dataset_id, rows)
        stats = verify(conn, ds, dataset_id, len(rows))
    log.info("%-32s %7d rows -> floin.%-17s %s  OK", ds.name, stats["n"], ds.table, stats["types"])
    return stats


def register_rejected() -> None:
    with connect() as conn:
        for filename, (category, reason) in REJECTED.items():
            try:
                path = resolve_source(filename)
                checksum = sha256_file(path)
            except DatasetMissingError:
                path, checksum = None, None
            upsert_dataset(conn, {
                "name": "rejected:" + filename.removesuffix(".geojson"), "title": filename,
                "dataset_type": "vector", "category": category, "stage": "source", "storage_kind": "none",
                "format": "GeoJSON", "status": "rejected", "quality_notes": reason, "checksum_sha256": checksum,
                "source": "supplied project file", "lineage": {"file": str(path) if path else None},
            })
    log.info("registered %d rejected placeholder files", len(REJECTED))


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser()
    parser.add_argument("names", nargs="*")
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()
    if args.list:
        for ds in DATASETS:
            print(f"{ds.name:34} -> floin.{ds.table}")
        return
    selected = [d for d in DATASETS if not args.names or d.name in args.names]
    failures = []
    for ds in selected:
        try:
            load_dataset(ds)
        except Exception as exc:  # report every failure, then exit non-zero
            failures.append((ds.name, str(exc)))
            log.error("%s FAILED: %s", ds.name, exc)
    if not args.names:
        register_rejected()
    if failures:
        log.error("%d dataset(s) failed: %s", len(failures), ", ".join(n for n, _ in failures))
        sys.exit(1)


if __name__ == "__main__":
    main()
