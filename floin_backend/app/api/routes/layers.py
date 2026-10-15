"""Read-only map data: catalog vector layers as GeoJSON, raster previews, terrain grid, rainfall."""
import json
import os

import numpy as np
from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from rasterio.warp import transform_bounds
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.core.errors import DataValidationError, NotFoundError
from app.db.database import get_connection
from app.db.repositories import get_dataset, list_datasets
from app.gis.grid import ModelGrid
from app.gis.raster import read_band, read_float
from app.services import display_service as ds
from app.services.dataset_service import fetch_raster, resolve

router = APIRouter(tags=["map data"])

# Columns exposed per reference table (geometry and ids are always included).
LAYER_COLUMNS = {
    "admin_boundaries": ["boundary_type", "code", "name", "zone"],
    "buildings": ["source_id", "building_type"],
    "roads": ["source_id", "name", "highway"],
    "railways": ["source_id", "name", "railway", "is_metro"],
    "rivers": ["name", "waterway_type"],
    "drainage": ["name", "drain_class"],
    "water_bodies": ["name", "water_type"],
    "flood_references": ["reference_type", "event_name", "event_date", "return_period_years",
                         "observation_type", "depth_class", "depth_min_m", "depth_max_m"],
}
MAX_FEATURES = 50000


@router.get("/layers")
def layers(conn: Connection = Depends(get_connection)):
    """Vector datasets that can be drawn on a map (usable PostGIS layers only)."""
    out = []
    for d in list_datasets(conn):
        if d["dataset_type"] != "vector" or d["storage_kind"] != "postgis" or d["status"] not in ("available", "limited"):
            continue
        out.append({k: d[k] for k in ("name", "title", "category", "status", "feature_count", "geometry_type",
                                      "source", "licence", "quality_notes", "footprint")})
    return out


@router.get("/layers/{name}/geojson")
def layer_geojson(name: str,
                  bbox: str | None = Query(None, description="west,south,east,north in degrees (EPSG:4326)"),
                  simplify_m: float = Query(0, ge=0, le=200),
                  limit: int = Query(5000, ge=1, le=MAX_FEATURES),
                  conn: Connection = Depends(get_connection)):
    record = resolve(conn, name)
    if record["dataset_type"] != "vector" or not record["table_name"]:
        raise DataValidationError(f"{name} is not a vector layer")
    table = record["table_name"].split(".")[1]
    if table not in LAYER_COLUMNS:
        raise DataValidationError(f"{name} is not exposed as a map layer")
    params = {"id": record["id"], "tol": simplify_m, "row_limit": limit + 1}
    where = "dataset_id = :id"
    if bbox:
        try:
            w, s, e, n = (float(v) for v in bbox.split(","))
        except ValueError as exc:
            raise DataValidationError("bbox must be west,south,east,north") from exc
        where += " AND geom && ST_Transform(ST_MakeEnvelope(:w, :s, :e, :n, 4326), 32644)"
        params.update(w=w, s=s, e=e, n=n)
    columns = ", ".join(LAYER_COLUMNS[table])
    rows = conn.execute(text(f"""
        SELECT id, {columns},
               ST_AsGeoJSON(ST_Transform(CASE WHEN :tol > 0 THEN ST_SimplifyPreserveTopology(geom, :tol) ELSE geom END, 4326), 6) AS g
        FROM floin.{table} WHERE {where} ORDER BY id LIMIT :row_limit
    """), params).mappings().all()
    truncated = len(rows) > limit
    features = []
    for r in rows[:limit]:
        props = {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in r.items() if k != "g"}
        features.append({"type": "Feature", "id": r["id"], "properties": props, "geometry": json.loads(r["g"])})
    return {
        "type": "FeatureCollection",
        "properties": {"dataset": name, "title": record["title"], "status": record["status"], "crs": "EPSG:4326",
                       "returned": len(features), "truncated": truncated, "bbox": bbox, "simplify_m": simplify_m},
        "features": features,
    }


def _preview_style(name: str) -> str:
    if name not in ds.DATASET_STYLES:
        raise DataValidationError(f"no map preview is defined for {name}")
    return ds.DATASET_STYLES[name]


@router.get("/rasters")
def rasters():
    """Catalog rasters that have a map preview style."""
    return [{"name": n, "style": s} for n, s in ds.DATASET_STYLES.items()]


@router.get("/rasters/{name}/preview")
def raster_preview_meta(name: str, max_size: int = Query(1600, ge=128, le=4096), conn: Connection = Depends(get_connection)):
    style = _preview_style(name)
    record = resolve(conn, name)
    path = fetch_raster(record)
    _, bounds, legend = ds.render_preview(str(path), os.path.getmtime(path), style, max_size)
    return {"name": name, "title": record["title"], "bounds": bounds, "legend": legend, "crs_of_image": "EPSG:3857",
            "png": f"/api/v1/rasters/{name}/preview.png?max_size={max_size}", "source": record["source"]}


@router.get("/rasters/{name}/preview.png")
def raster_preview_png(name: str, max_size: int = Query(1600, ge=128, le=4096), conn: Connection = Depends(get_connection)):
    style = _preview_style(name)
    path = fetch_raster(resolve(conn, name))
    png, _, _ = ds.render_preview(str(path), os.path.getmtime(path), style, max_size)
    return Response(png, media_type="image/png", headers={"Cache-Control": "max-age=300"})


@router.get("/terrain/grid")
def terrain_grid(max_size: int = Query(256, ge=32, le=640), conn: Connection = Depends(get_connection)):
    """Block-averaged model DEM (sea = null) for 3D rendering. Cell size grows with downsampling."""
    dem_path = fetch_raster(resolve(conn, "dem_30m"))
    dom_path = fetch_raster(resolve(conn, "model_domain_30m"))
    _, profile = read_band(dem_path)
    grid = ModelGrid.from_profile(profile)
    dem = read_float(dem_path, grid, "dem_30m")
    dem[read_band(dom_path, grid, "domain")[0] != 1] = np.nan
    factor = ds.grid_factor(grid.shape, max_size)
    reduced = ds.block_reduce(dem, factor)
    west, south, east, north = transform_bounds(grid.crs, "EPSG:4326", *grid.bounds)
    return {
        "dataset": "dem_30m", "crs": grid.crs.to_string(), "unit": "m",
        "source_resolution_m": grid.resolution, "downsample_factor": factor, "cell_size_m": grid.resolution * factor,
        "width": reduced.shape[1], "height": reduced.shape[0], "bounds_projected": list(grid.bounds),
        "bounds_wgs84": [west, south, east, north],
        "min": float(np.nanmin(reduced)), "max": float(np.nanmax(reduced)),
        "note": "Copernicus GLO-30 surface model (includes buildings/trees), block mean; null = open sea",
        "values": ds.to_json_grid(reduced, 1),
    }


@router.get("/rainfall/chirps")
def rainfall_chirps(conn: Connection = Depends(get_connection)):
    """Daily CHIRPS rainfall statistics over the model area from the stored source rasters."""
    days = []
    for d in list_datasets(conn, category="rainfall"):
        if d["stage"] != "source" or not d["name"].startswith("rainfall_chirps_") or d["status"] not in ("available", "limited"):
            continue
        date = (d.get("lineage") or {}).get("date") or d["name"].rsplit("_", 1)[1]
        stats = ds.chirps_window_stats(fetch_raster(d))
        days.append({"date": date, "dataset": d["name"], **stats})
    if not days:
        raise NotFoundError("no CHIRPS rainfall datasets are registered")
    event = get_dataset(conn, "rainfall_chirps_2015_event_30m")
    return {
        "source": "CHIRPS v2.0 daily (UCSB Climate Hazards Center), 0.05 deg, satellite-gauge estimate",
        "area": "cells whose centres lie inside the FLOIN model area",
        "note": "Satellite estimates; known to underestimate the extreme gauge totals of 1 Dec 2015.",
        "days": sorted(days, key=lambda x: x["date"]),
        "event_total_dataset": {"name": event["name"], "min_mm": event["min_value"], "max_mm": event["max_value"]} if event else None,
    }
