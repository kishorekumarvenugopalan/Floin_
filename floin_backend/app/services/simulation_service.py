"""Simulation orchestrator: catalog datasets -> runoff -> routing -> flood -> exposure -> stored results.

Every stage either produces a verified intermediate result or raises. A failed run is
marked 'failed' with the stage and reason; no partial or substitute result is returned.
"""
import json
import secrets
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import rasterio
from rasterio.warp import Resampling, reproject
from sqlalchemy import text

from app.core.config import get_settings
from app.core.errors import DataValidationError, NotFoundError, SimulationError
from app.core.logging import get_logger
from app.db.database import connect
from app.gis.grid import ModelGrid
from app.gis.raster import read_band, read_float, sha256_file, write_raster
from app.schemas.simulation import SimulationRequest
from app.services import exposure_service
from app.services.dataset_service import fetch_raster, resolve
from app.services.storage_service import get_storage
from app.simulation import MODEL_VERSION
from app.simulation.accumulation import accumulate
from app.simulation.cn import adjust_amc, curve_number
from app.simulation.d8 import NEIGHBOURS, NODATA_CODE, OUTLET_CODE
from app.simulation.dem import WORLDCOVER_WATER
from app.simulation.flood_depth import fill_and_spill, flood_depth, identify_depressions
from app.simulation.flood_extent import DEFAULT_CLASS_NAMES, classify, polygonize, summarize
from app.simulation.scs_cn import retention_mm, runoff_depth_mm, runoff_volume_m3

log = get_logger("simulation")

# Catalog datasets every run needs, by role.
REQUIRED_DATASETS = {
    "dem": "dem_30m",
    "domain": "model_domain_30m",
    "landcover_10m": "landcover_worldcover_2021_10m",
    "landcover_30m": "landcover_30m",
    "soil_hsg": "hsg_30m",
    "channels": "channels_30m",
    "dem_conditioned": "terrain_dem_conditioned_30m",
    "dem_filled": "terrain_dem_filled_30m",
    "flow_direction": "terrain_flow_direction_30m",
    "flow_rank": "terrain_flow_rank_30m",
    "flow_accumulation_topographic": "terrain_flow_accumulation_30m",
}
# Vector layers (PostGIS) used for exposure; a run stops if any is missing.
REQUIRED_VECTOR_DATASETS = {
    "buildings": "osm_buildings",
    "roads": "osm_roads",
    "railways": "osm_railways",
    "wards": "wards_gcc",
}
MASS_BALANCE_TOLERANCE = 1e-6


def new_simulation_id() -> str:
    return f"SIM-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"


def class_names(breaks: list[float]) -> list[str]:
    if list(breaks) == [0.3, 1.0, 2.0]:
        return list(DEFAULT_CLASS_NAMES)
    edges = list(breaks)
    return [f"<{edges[0]} m"] + [f"{a}-{b} m" for a, b in zip(edges, edges[1:])] + [f">{edges[-1]} m"]


def create_run(request: SimulationRequest) -> str:
    sid = new_simulation_id()
    with connect() as conn:
        conn.execute(text("""
            INSERT INTO floin.simulation_runs (id, status, scenario, rainfall_source, rainfall_mm, rainfall_dataset,
                duration_hours, parameters, model_version)
            VALUES (:id, 'queued', :scenario, :source, :mm, :ds, :dur, CAST(:params AS jsonb), :mv)
        """), {"id": sid, "scenario": request.scenario,
               "source": "uniform" if request.rainfall_mm is not None else "dataset",
               "mm": request.rainfall_mm, "ds": request.rainfall_dataset, "dur": request.duration_hours,
               "params": request.model_dump_json(), "mv": MODEL_VERSION})
    return sid


def _set_stage(sid: str, stage: str, status: str = "running") -> None:
    with connect() as conn:
        conn.execute(text("""
            UPDATE floin.simulation_runs SET status = :status, current_stage = :stage,
                   started_at = COALESCE(started_at, now()) WHERE id = :id
        """), {"id": sid, "stage": stage, "status": status})
    log.info("%s: %s", sid, stage)


def run_simulation(sid: str) -> dict:
    """Execute a queued run. Returns the stored result summary or raises."""
    started = time.time()
    try:
        with connect() as conn:
            row = conn.execute(text("SELECT parameters FROM floin.simulation_runs WHERE id = :id"), {"id": sid}).first()
        if row is None:
            raise NotFoundError(f"simulation {sid} not found")
        request = SimulationRequest.model_validate(row[0])
        result = _execute(sid, request)
        with connect() as conn:
            conn.execute(text("""
                UPDATE floin.simulation_runs SET status = 'completed', current_stage = 'done', completed_at = now(),
                       runtime_seconds = :rt WHERE id = :id
            """), {"id": sid, "rt": time.time() - started})
        log.info("%s completed in %.1f s", sid, time.time() - started)
        return result
    except Exception as exc:
        with connect() as conn:
            stage = conn.execute(text("SELECT current_stage FROM floin.simulation_runs WHERE id = :id"), {"id": sid}).scalar()
            conn.execute(text("""
                UPDATE floin.simulation_runs SET status = 'failed', completed_at = now(), runtime_seconds = :rt,
                       error = :err WHERE id = :id
            """), {"id": sid, "rt": time.time() - started, "err": f"[{stage}] {type(exc).__name__}: {exc}"})
        log.exception("%s failed at stage %s", sid, stage)
        raise


def _execute(sid: str, req: SimulationRequest) -> dict:
    settings = get_settings()
    work = settings.work_dir / sid
    work.mkdir(parents=True, exist_ok=True)
    outputs: dict[str, Path] = {}

    # 1. Resolve and fetch catalog datasets; record exactly which versions are used
    _set_stage(sid, "resolve_datasets")
    roles = dict(REQUIRED_DATASETS)
    if req.rainfall_dataset:
        roles["rainfall"] = req.rainfall_dataset
    roles.update(REQUIRED_VECTOR_DATASETS)
    with connect() as conn:
        records = {role: resolve(conn, name) for role, name in roles.items()}
        for role, rec in records.items():
            conn.execute(text("""
                INSERT INTO floin.simulation_inputs (simulation_id, role, dataset_id, dataset_name, dataset_version, checksum_sha256)
                VALUES (:sid, :role, :id, :name, :version, :sha)
            """), {"sid": sid, "role": role, "id": rec["id"], "name": rec["name"], "version": rec["version"],
                   "sha": rec["checksum_sha256"]})
    paths = {role: fetch_raster(rec) for role, rec in records.items() if rec["dataset_type"] == "raster"}

    _, dem_profile = read_band(paths["dem"])
    grid = ModelGrid.from_profile(dem_profile)
    area = grid.cell_area_m2
    domain = read_band(paths["domain"], grid, "model_domain")[0] == 1
    n_domain = int(domain.sum())

    # 2. Rainfall
    _set_stage(sid, "rainfall")
    if req.rainfall_mm is not None:
        rainfall = np.where(domain, req.rainfall_mm, np.nan)
    else:
        rainfall = read_float(paths["rainfall"], grid, req.rainfall_dataset)
        rainfall[~domain] = np.nan
        if np.isnan(rainfall[domain]).any():
            raise DataValidationError(f"rainfall dataset {req.rainfall_dataset} has gaps inside the model domain")
    if (rainfall[domain] < 0).any():
        raise DataValidationError("rainfall contains negative values")

    # 3. Curve number from land cover (10 m) and hydrologic soil group
    _set_stage(sid, "curve_number")
    cn, cn_report = _curve_number(paths["landcover_10m"], paths["soil_hsg"], grid, domain, req.antecedent_moisture)
    outputs["cn"] = write_raster(work / "cn.tif", cn, grid, "float32", -9999.0)

    # 4. SCS-CN runoff depth and volume
    _set_stage(sid, "runoff")
    runoff_mm = runoff_depth_mm(np.where(domain, rainfall, 0.0), cn, req.ia_ratio)
    runoff_mm[~domain] = np.nan
    if np.isnan(runoff_mm[domain]).any():
        raise SimulationError("runoff is undefined for some domain cells")
    volume = np.nan_to_num(runoff_volume_m3(runoff_mm, area), nan=0.0)
    outputs["runoff"] = write_raster(work / "runoff.tif", runoff_mm, grid, "float32", -9999.0)
    hydrology = {
        "rainfall_mm": _stats(rainfall[domain]),
        "rainfall_volume_m3": float(np.nansum(rainfall[domain]) / 1000.0 * area),
        "curve_number": {**_stats(cn[domain]), "antecedent_moisture": req.antecedent_moisture, **cn_report},
        "retention_s_mm": _stats(retention_mm(cn[domain])),
        "initial_abstraction_ratio": req.ia_ratio,
        "runoff_mm": _stats(runoff_mm[domain]),
        "runoff_volume_m3": float(volume.sum()),
        "runoff_coefficient": float(np.nansum(runoff_mm[domain]) / np.nansum(rainfall[domain])),
        "duration_hours": req.duration_hours,
        "mean_intensity_mm_per_hour": float(np.nanmean(rainfall[domain]) / req.duration_hours),
        "note": "SCS-CN uses event-total rainfall; duration does not change runoff depth in this model.",
    }

    # 5. Terrain network (static products) and accumulation
    _set_stage(sid, "routing")
    ground = read_float(paths["dem_conditioned"], grid, "dem_conditioned")
    filled = read_float(paths["dem_filled"], grid, "dem_filled")
    codes = read_band(paths["flow_direction"], grid, "flow_direction")[0]
    rank = read_band(paths["flow_rank"], grid, "flow_rank")[0]
    receiver = _receivers_from_codes(codes, domain)
    order = _order_from_rank(rank, domain)
    runoff_acc, runoff_outflow = accumulate(order, receiver, volume)
    runoff_acc[~domain] = np.nan
    outputs["runoff_accumulation"] = write_raster(work / "runoff_accumulation.tif", runoff_acc, grid, "float32", -9999.0)
    topo_acc = read_float(paths["flow_accumulation_topographic"], grid, "flow_accumulation_topographic")
    terrain = {
        "grid": grid.as_dict(),
        "domain_cells": n_domain,
        "domain_area_km2": n_domain * area / 1e6,
        "max_topographic_accumulation_km2": float(np.nanmax(topo_acc) * area / 1e6),
        "max_runoff_accumulation_m3": float(np.nanmax(runoff_acc)),
        "runoff_reaching_outlets_without_storage_m3": float(runoff_outflow),
    }

    # 6. Drainage / rivers: mapped channels are burned into the conditioned DEM (static);
    #    storm-water drain capacity is not modelled because no capacity data exists.
    channels = read_band(paths["channels"], grid, "channels")[0] == 1
    landcover30 = read_band(paths["landcover_30m"], grid, "landcover_30m")[0]
    permanent_water = landcover30 == WORLDCOVER_WATER

    # 7. Depression storage (fill and spill) and flood depth
    _set_stage(sid, "flood_depth")
    labels, capacity, spill = identify_depressions(ground, filled, domain, area)
    stored, outflow, through = fill_and_spill(order, receiver, volume, labels, capacity)
    balance_error = abs(stored.sum() + outflow - volume.sum()) / max(volume.sum(), 1.0)
    if balance_error > MASS_BALANCE_TOLERANCE:
        raise SimulationError(f"water balance error {balance_error:.2e} exceeds tolerance")
    surface, depth = flood_depth(labels, ground, stored, spill, area)
    depth[~domain] = np.nan
    stored_by_depth = float(np.nansum(depth) * area)
    if abs(stored_by_depth - stored.sum()) > 1e-6 * max(stored.sum(), 1.0):
        raise SimulationError("flood depth volume does not match stored volume")
    outputs["flood_depth"] = write_raster(work / "flood_depth.tif", depth, grid, "float32", -9999.0)
    outputs["water_surface"] = write_raster(work / "water_surface.tif", surface, grid, "float32", -9999.0)

    # 8. Flood extent (excluding permanent water bodies and mapped channels)
    _set_stage(sid, "flood_extent")
    flood_mask = domain & ~permanent_water & ~channels
    classes = classify(np.nan_to_num(depth), flood_mask, req.min_flood_depth_m, req.depth_class_breaks_m)
    names = class_names(req.depth_class_breaks_m)
    outputs["flood_extent"] = write_raster(work / "flood_extent.tif", classes, grid, "uint8", 255)
    polygons = polygonize(classes, grid.transform)
    flood = {
        **summarize(np.nan_to_num(depth), classes, area, names),
        "min_flood_depth_m": req.min_flood_depth_m,
        "class_breaks_m": req.depth_class_breaks_m,
        "class_names": names,
        "polygon_count": len(polygons),
        "water_balance": {
            "runoff_volume_m3": float(volume.sum()),
            "stored_in_depressions_m3": float(stored.sum()),
            "left_domain_m3": float(outflow),
            "relative_error": float(balance_error),
            "stored_in_permanent_water_or_channels_m3": float(np.nansum(depth[~flood_mask & domain]) * area),
        },
        "depressions": {"count": int(capacity.size), "capacity_m3": float(capacity.sum()),
                        "filled_to_spill": int((stored >= capacity * (1 - 1e-9)).sum() if capacity.size else 0)},
        "drainage": {
            "rivers_and_canals": "burned into the conditioned DEM; water reaching them is conveyed downstream",
            "storm_water_drains": "not modelled: the GCC drain layer has no capacity, size or invert data",
        },
        "model_type": "event-based SCS-CN runoff + D8 routing + depression fill-and-spill storage",
        "hydraulic_simulation": False,
    }
    outputs["flood_extent_geojson"] = _write_geojson(work / "flood_extent.geojson", polygons, names, grid)

    # 9. Exposure (PostGIS spatial overlays) and hazard
    _set_stage(sid, "exposure")
    with connect() as conn:
        exposure_service.store_flood_polygons(conn, sid, polygons)
        exposure = exposure_service.compute_exposure(conn, sid, names)
    hazard = {
        "definition": "flood depth classes from the fill-and-spill model",
        "area_km2_by_class": {k: v["area_km2"] for k, v in flood["by_class"].items()},
        "max_depth_m": flood["max_depth_m"],
    }
    risk = {
        "status": "not_computed",
        "reason": "No vulnerability data (depth-damage curves, building typology, population vulnerability) is "
                  "available, so FLOIN reports hazard and exposure only.",
        "available": ["hazard", "exposure"],
    }

    # 10. Store outputs and results
    _set_stage(sid, "store_outputs")
    metadata = {"simulation_id": sid, "model_version": MODEL_VERSION, "request": req.model_dump(),
                "inputs": {r: {"dataset": rec["name"], "version": rec["version"], "sha256": rec["checksum_sha256"]}
                           for r, rec in records.items()},
                "hydrology": hydrology, "terrain": terrain, "flood": flood, "exposure": exposure,
                "hazard": hazard, "risk": risk}
    outputs["metadata"] = work / "metadata.json"
    outputs["metadata"].write_text(json.dumps(metadata, indent=2, default=str), encoding="utf-8")
    _upload_outputs(sid, outputs)
    with connect() as conn:
        conn.execute(text("""
            INSERT INTO floin.simulation_results (simulation_id, hydrology, terrain, flood, exposure, hazard, risk)
            VALUES (:sid, CAST(:h AS jsonb), CAST(:t AS jsonb), CAST(:f AS jsonb), CAST(:e AS jsonb),
                    CAST(:z AS jsonb), CAST(:r AS jsonb))
        """), {"sid": sid, "h": json.dumps(hydrology), "t": json.dumps(terrain), "f": json.dumps(flood),
               "e": json.dumps(exposure), "z": json.dumps(hazard), "r": json.dumps(risk)})
    shutil.rmtree(work, ignore_errors=True)  # every output is now in storage and registered
    return metadata


def _curve_number(landcover_path: Path, hsg_path: Path, grid: ModelGrid, domain: np.ndarray, amc: str):
    """CN at native 10 m land-cover resolution, then area-averaged onto the 30 m grid
    (the TR-55 area-weighted composite CN)."""
    with rasterio.open(landcover_path) as src:
        landcover = src.read(1)
        lc_transform, lc_crs = src.transform, src.crs
    hsg30, _ = read_band(hsg_path, grid, "hsg")
    hsg10 = np.zeros(landcover.shape, dtype="uint8")
    reproject(hsg30, hsg10, src_transform=grid.transform, src_crs=grid.crs, src_nodata=0,
              dst_transform=lc_transform, dst_crs=lc_crs, dst_nodata=0, resampling=Resampling.nearest)
    cn10, report = curve_number(landcover, hsg10)
    cn10 = adjust_amc(cn10, amc).astype("float32")
    cn30 = np.full(grid.shape, np.nan, dtype="float32")
    reproject(cn10, cn30, src_transform=lc_transform, src_crs=lc_crs, src_nodata=np.nan,
              dst_transform=grid.transform, dst_crs=grid.crs, dst_nodata=np.nan, resampling=Resampling.average)
    cn30[~domain] = np.nan
    missing = domain & ~np.isfinite(cn30)
    if missing.any():
        raise DataValidationError(f"{int(missing.sum())} domain cells have no curve number (land cover or soil missing)")
    if (cn30[domain] <= 0).any() or (cn30[domain] > 100).any():
        raise DataValidationError("curve numbers outside (0, 100]")
    report = {"lookup": "TR-55 (see app/simulation/cn.py)", "pixels_10m_without_soil": report["soil_missing_pixels"],
              "unmapped_pixels_10m": report["unmapped_pixels"], "aggregation": "area-average of 10 m CN onto 30 m grid"}
    return cn30.astype("float64"), report


def _receivers_from_codes(codes: np.ndarray, domain: np.ndarray) -> np.ndarray:
    rows, cols = codes.shape
    flat = np.arange(rows * cols).reshape(rows, cols)
    receiver = np.full(rows * cols, -1, dtype=np.int64)
    for dr, dc, code in NEIGHBOURS:
        sel = codes == code
        receiver[flat[sel]] = flat[sel] + dr * cols + dc
    bad = domain & ~np.isin(codes, [c for _, _, c in NEIGHBOURS] + [OUTLET_CODE])
    if bad.any() or (codes[~domain] != NODATA_CODE).any():
        raise DataValidationError("flow direction raster does not match the model domain")
    return receiver


def _order_from_rank(rank: np.ndarray, domain: np.ndarray) -> np.ndarray:
    cells = np.flatnonzero(domain.ravel())
    ranks = rank.ravel()[cells]
    if (ranks < 0).any():
        raise DataValidationError("flow rank missing for domain cells")
    return cells[np.argsort(ranks, kind="stable")]


def _stats(values: np.ndarray) -> dict:
    values = values[np.isfinite(values)]
    if values.size == 0:
        return {"min": None, "mean": None, "max": None}
    return {"min": float(values.min()), "mean": float(values.mean()), "max": float(values.max())}


def _write_geojson(path: Path, polygons, names, grid: ModelGrid) -> Path:
    import geopandas as gpd
    gdf = gpd.GeoDataFrame(
        {"depth_class": [c for _, c in polygons], "class_name": [names[c - 1] for _, c in polygons]},
        geometry=[g for g, _ in polygons], crs=grid.crs,
    ).to_crs(4326)
    gdf.to_file(path, driver="GeoJSON")
    return path


def _upload_outputs(sid: str, outputs: dict[str, Path]) -> None:
    storage = get_storage()
    content_types = {".tif": "image/tiff", ".geojson": "application/geo+json", ".json": "application/json"}
    with connect() as conn:
        for name, path in outputs.items():
            key = f"simulations/{sid}/{path.name}"
            storage.upload(path, key, content_types.get(path.suffix, "application/octet-stream"))
            stats = {}
            if path.suffix == ".tif":
                with rasterio.open(path) as src:
                    data = src.read(1, masked=True)
                    stats = {"min": float(data.min()), "max": float(data.max()), "dtype": src.dtypes[0],
                             "nodata": src.nodata} if data.count() else {"empty": True}
            conn.execute(text("""
                INSERT INTO floin.simulation_outputs (simulation_id, name, storage_path, format, size_bytes, checksum_sha256, stats)
                VALUES (:sid, :name, :sp, :fmt, :size, :sha, CAST(:stats AS jsonb))
            """), {"sid": sid, "name": name, "sp": f"{storage.bucket}/{key}", "fmt": path.suffix.lstrip("."),
                   "size": path.stat().st_size, "sha": sha256_file(path), "stats": json.dumps(stats)})
