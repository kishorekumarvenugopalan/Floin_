import json
import os

import numpy as np
from fastapi import APIRouter, BackgroundTasks, Depends, Query
from fastapi.responses import Response
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.core.errors import DataValidationError, NotFoundError
from app.core.logging import get_logger
from app.db.database import get_connection
from app.schemas.simulation import SimulationAccepted, SimulationRequest
from app.gis.grid import ModelGrid
from app.gis.raster import read_band, read_float
from app.services import display_service, simulation_service
from app.services.dataset_service import fetch_raster

router = APIRouter(tags=["simulations"])
log = get_logger("api.simulations")


def _run_in_background(sid: str) -> None:
    try:
        simulation_service.run_simulation(sid)
    except Exception:  # already recorded as 'failed' on the run row
        log.error("background simulation %s failed", sid)


@router.post("/simulations", status_code=202, response_model=SimulationAccepted)
def create_simulation(request: SimulationRequest, background: BackgroundTasks):
    sid = simulation_service.create_run(request)
    background.add_task(_run_in_background, sid)
    base = f"/api/v1/simulations/{sid}"
    return SimulationAccepted(simulation_id=sid, status="queued",
                              links={"status": base, "results": f"{base}/results", "flood": f"{base}/flood",
                                     "risk": f"{base}/risk"})


@router.get("/simulations")
def list_simulations(limit: int = Query(20, ge=1, le=200), conn: Connection = Depends(get_connection)):
    rows = conn.execute(text("""
        SELECT id, status, scenario, rainfall_source, rainfall_mm, rainfall_dataset, duration_hours,
               current_stage, error, created_at, completed_at, runtime_seconds
        FROM floin.simulation_runs ORDER BY created_at DESC LIMIT :n
    """), {"n": limit}).mappings().all()
    return [_jsonable(r) for r in rows]


@router.get("/simulations/{sid}")
def get_simulation(sid: str, conn: Connection = Depends(get_connection)):
    run = conn.execute(text("SELECT * FROM floin.simulation_runs WHERE id = :id"), {"id": sid}).mappings().first()
    if run is None:
        raise NotFoundError(f"simulation {sid} not found")
    inputs = conn.execute(text(
        "SELECT role, dataset_name, dataset_version, checksum_sha256 FROM floin.simulation_inputs WHERE simulation_id = :id"
    ), {"id": sid}).mappings().all()
    outputs = conn.execute(text(
        "SELECT name, storage_path, format, size_bytes, checksum_sha256, stats FROM floin.simulation_outputs "
        "WHERE simulation_id = :id ORDER BY id"), {"id": sid}).mappings().all()
    return {**_jsonable(run), "inputs": [dict(i) for i in inputs], "outputs": [dict(o) for o in outputs]}


@router.get("/simulations/{sid}/results")
def get_results(sid: str, conn: Connection = Depends(get_connection)):
    return _results(conn, sid)


@router.get("/simulations/{sid}/risk")
def get_risk(sid: str, conn: Connection = Depends(get_connection)):
    r = _results(conn, sid)
    return {"simulation_id": sid, "hazard": r["hazard"], "exposure": r["exposure"], "risk": r["risk"]}


@router.get("/simulations/{sid}/flood")
def get_flood(sid: str, simplify_m: float = Query(0, ge=0, le=100, description="Douglas-Peucker tolerance (m)"),
              min_class: int = Query(1, ge=1, le=7), conn: Connection = Depends(get_connection)):
    """Flood extent polygons as a GeoJSON FeatureCollection in EPSG:4326."""
    _results(conn, sid)
    rows = conn.execute(text("""
        SELECT depth_class,
               ST_AsGeoJSON(ST_Transform(CASE WHEN :tol > 0 THEN ST_SimplifyPreserveTopology(geom, :tol) ELSE geom END, 4326), 6)
        FROM floin.simulation_flood_polygons
        WHERE simulation_id = :sid AND depth_class >= :min_class
    """), {"sid": sid, "tol": simplify_m, "min_class": min_class}).all()
    return {
        "type": "FeatureCollection",
        "properties": {"simulation_id": sid, "crs": "EPSG:4326", "simplify_m": simplify_m},
        "features": [{"type": "Feature", "properties": {"depth_class": c}, "geometry": json.loads(g)} for c, g in rows],
    }


def _results(conn: Connection, sid: str) -> dict:
    run = conn.execute(text("SELECT status, error FROM floin.simulation_runs WHERE id = :id"), {"id": sid}).first()
    if run is None:
        raise NotFoundError(f"simulation {sid} not found")
    row = conn.execute(text("SELECT * FROM floin.simulation_results WHERE simulation_id = :id"), {"id": sid}).mappings().first()
    if row is None:
        raise NotFoundError(f"simulation {sid} has no results (status: {run[0]}{', error: ' + run[1] if run[1] else ''})")
    return _jsonable(row)


def _jsonable(row) -> dict:
    return {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in dict(row).items()}


# ------------------------------------------------------------------ read-only views of stored outputs

def _output_record(conn: Connection, sid: str, name: str) -> dict:
    row = conn.execute(text("""
        SELECT name, storage_path, checksum_sha256 FROM floin.simulation_outputs WHERE simulation_id = :sid AND name = :n
    """), {"sid": sid, "n": name}).mappings().first()
    if row is None:
        raise NotFoundError(f"simulation {sid} has no stored output '{name}'")
    return {"name": f"{sid}/{name}", "storage_kind": "storage", "storage_path": row["storage_path"],
            "checksum_sha256": row["checksum_sha256"]}


def _run_parameters(conn: Connection, sid: str) -> dict:
    params = conn.execute(text("SELECT parameters FROM floin.simulation_runs WHERE id = :id"), {"id": sid}).scalar()
    if params is None:
        raise NotFoundError(f"simulation {sid} not found")
    return params


def _preview(conn: Connection, sid: str, output: str, max_size: int):
    if output not in display_service.OUTPUT_STYLES:
        raise DataValidationError(f"no map preview is defined for output '{output}'")
    params = _run_parameters(conn, sid)
    path = fetch_raster(_output_record(conn, sid, output))
    style = display_service.OUTPUT_STYLES[output]
    extra = {}
    if style == "depth":
        extra = {"breaks": tuple(params["depth_class_breaks_m"]), "min_depth": params["min_flood_depth_m"]}
    return display_service.render_preview(str(path), os.path.getmtime(path), style, max_size, **extra)


@router.get("/simulations/{sid}/outputs/{output}/preview")
def output_preview_meta(sid: str, output: str, max_size: int = Query(1600, ge=128, le=4096),
                        conn: Connection = Depends(get_connection)):
    _, bounds, legend = _preview(conn, sid, output, max_size)
    return {"simulation_id": sid, "output": output, "bounds": bounds, "legend": legend, "crs_of_image": "EPSG:3857",
            "png": f"/api/v1/simulations/{sid}/outputs/{output}/preview.png?max_size={max_size}"}


@router.get("/simulations/{sid}/outputs/{output}/preview.png")
def output_preview_png(sid: str, output: str, max_size: int = Query(1600, ge=128, le=4096),
                       conn: Connection = Depends(get_connection)):
    png, _, _ = _preview(conn, sid, output, max_size)
    return Response(png, media_type="image/png", headers={"Cache-Control": "max-age=3600"})


@router.get("/simulations/{sid}/terrain-overlay")
def terrain_overlay(sid: str, max_size: int = Query(256, ge=32, le=640), conn: Connection = Depends(get_connection)):
    """Flood depth on the same block grid as /terrain/grid: block-mean depth and flooded share."""
    params = _run_parameters(conn, sid)
    path = fetch_raster(_output_record(conn, sid, "flood_depth"))
    _, profile = read_band(path)
    grid = ModelGrid.from_profile(profile)
    depth = read_float(path, grid, "flood_depth")
    flooded = np.where(np.isfinite(depth), (depth >= params["min_flood_depth_m"]).astype("float64"), np.nan)
    factor = display_service.grid_factor(grid.shape, max_size)
    return {
        "simulation_id": sid, "unit": "m", "downsample_factor": factor, "cell_size_m": grid.resolution * factor,
        "min_flood_depth_m": params["min_flood_depth_m"],
        "depth_mean": display_service.to_json_grid(display_service.block_reduce(depth, factor), 2),
        "depth_max": display_service.to_json_grid(display_service.block_reduce(depth, factor, "max"), 2),
        "flooded_share": display_service.to_json_grid(display_service.block_reduce(flooded, factor), 2),
        "note": "Block statistics of the stored 30 m flood_depth raster; includes water held in permanent water bodies and channels.",
    }


@router.get("/simulations/{sid}/wards")
def simulation_wards(sid: str, simplify_m: float = Query(20, ge=0, le=200), conn: Connection = Depends(get_connection)):
    """GCC wards with this run's stored ward summary. Wards without a row had no flooded area in the run."""
    _results(conn, sid)
    rows = conn.execute(text("""
        SELECT w.id, w.code, w.zone, ST_Area(w.geom) AS ward_area_m2,
               coalesce(s.flooded_area_m2, 0) AS flooded_area_m2, coalesce(s.buildings_affected, 0) AS buildings_affected,
               coalesce(s.road_length_m, 0) AS road_length_m, (s.simulation_id IS NOT NULL) AS has_flooding,
               ST_AsGeoJSON(ST_Transform(CASE WHEN :tol > 0 THEN ST_SimplifyPreserveTopology(w.geom, :tol) ELSE w.geom END, 4326), 6) AS g
        FROM floin.admin_boundaries w
        LEFT JOIN floin.simulation_ward_summary s ON s.boundary_id = w.id AND s.simulation_id = :sid
        WHERE w.boundary_type = 'gcc_ward' ORDER BY w.code
    """), {"sid": sid, "tol": simplify_m}).mappings().all()
    features = [{
        "type": "Feature", "id": r["id"], "geometry": json.loads(r["g"]),
        "properties": {
            "ward": r["code"], "zone": r["zone"], "ward_area_km2": r["ward_area_m2"] / 1e6,
            "flooded_area_km2": r["flooded_area_m2"] / 1e6, "flooded_share": r["flooded_area_m2"] / r["ward_area_m2"],
            "buildings_affected": r["buildings_affected"], "road_km": r["road_length_m"] / 1000.0,
            "has_flooding": r["has_flooding"],
        },
    } for r in rows]
    return {"type": "FeatureCollection", "properties": {"simulation_id": sid, "crs": "EPSG:4326"}, "features": features}
