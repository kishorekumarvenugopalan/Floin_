"""Historical validation: run FLOIN with observed event rainfall and compare with observations.

Comparisons are made on the model grid inside the comparison mask (model land domain,
excluding permanent water bodies and mapped channels, which the model never reports as
flood). Metrics:
  extent       cell-wise IoU, precision, recall, F1 and areas vs an observed extent layer,
               with a naive 'ground below 5 m' baseline for context
  streets      share of observed flooded-street length inside predicted flood polygons
  depth points share of observed hotspots predicted wet, and depth-class agreement
  points       share of observed stagnation points predicted wet
"""
import json
import secrets
from datetime import datetime, timezone

import numpy as np
import rasterio
import shapely
from rasterio import features
from scipy import ndimage
from sqlalchemy import text

from app.core.config import get_settings
from app.core.errors import DatasetMissingError, NotFoundError
from app.core.logging import get_logger
from app.db.database import connect
from app.gis.grid import ModelGrid
from app.gis.raster import read_band, read_float
from app.schemas.simulation import SimulationRequest
from app.services import simulation_service
from app.services.dataset_service import fetch_raster, resolve
from app.services.storage_service import get_storage
from app.services.validation_events import EVENTS
from app.simulation.dem import WORLDCOVER_WATER

log = get_logger("validation")
BASELINE_ELEVATION_M = 5.0


def create_validation_runs(event_name: str, conditions: list[str]) -> list[str]:
    if event_name not in EVENTS:
        raise NotFoundError(f"unknown validation event {event_name}")
    ids = []
    with connect() as conn:
        for amc in conditions:
            vid = f"VAL-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-{secrets.token_hex(2)}-AMC{amc}"
            conn.execute(text("""
                INSERT INTO floin.validation_runs (id, event_name, status, parameters)
                VALUES (:id, :event, 'queued', CAST(:p AS jsonb))
            """), {"id": vid, "event": event_name, "p": json.dumps({"antecedent_moisture": amc})})
            ids.append(vid)
    return ids


def run_validation(vid: str) -> dict:
    try:
        with connect() as conn:
            row = conn.execute(text("SELECT event_name, parameters FROM floin.validation_runs WHERE id = :id"),
                               {"id": vid}).mappings().first()
            if row is None:
                raise NotFoundError(f"validation run {vid} not found")
            conn.execute(text("UPDATE floin.validation_runs SET status = 'running' WHERE id = :id"), {"id": vid})
        event = EVENTS[row["event_name"]]
        amc = row["parameters"]["antecedent_moisture"]
        request = SimulationRequest(
            scenario=f"validation_{event['event_name']}_amc{amc}", rainfall_dataset=event["rainfall_dataset"],
            duration_hours=24.0 * len(event["rainfall_days"]), antecedent_moisture=amc,
        )
        sid = simulation_service.create_run(request)
        with connect() as conn:
            conn.execute(text("UPDATE floin.validation_runs SET simulation_id = :sid WHERE id = :id"), {"sid": sid, "id": vid})
        simulation_service.run_simulation(sid)
        metrics = compare(vid, sid, event)
        with connect() as conn:
            conn.execute(text("UPDATE floin.validation_runs SET status = 'completed', completed_at = now() WHERE id = :id"),
                         {"id": vid})
        return {"validation_id": vid, "simulation_id": sid, "metrics": metrics}
    except Exception as exc:
        with connect() as conn:
            conn.execute(text("""
                UPDATE floin.validation_runs SET status = 'failed', completed_at = now(), error = :e WHERE id = :id
            """), {"id": vid, "e": f"{type(exc).__name__}: {exc}"})
        log.exception("validation %s failed", vid)
        raise


def _json_default(value):
    """Serialise NumPy scalars that slip into metric dictionaries."""
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(f"{type(value).__name__} is not JSON serializable")


def binary_metrics(predicted: np.ndarray, observed: np.ndarray, cell_area_m2: float) -> dict:
    tp = int((predicted & observed).sum())
    fp = int((predicted & ~observed).sum())
    fn = int((~predicted & observed).sum())
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {
        "iou": float(tp / (tp + fp + fn)) if tp + fp + fn else 0.0,
        "precision": precision,
        "recall": recall,
        "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
        "predicted_area_km2": (tp + fp) * cell_area_m2 / 1e6,
        "observed_area_km2": (tp + fn) * cell_area_m2 / 1e6,
        "area_difference_km2": (fp - fn) * cell_area_m2 / 1e6,
        "true_positive_cells": tp, "false_positive_cells": fp, "false_negative_cells": fn,
    }


def chance_extent_metrics(predicted: np.ndarray, observed: np.ndarray, mask: np.ndarray, cell_area_m2: float) -> dict:
    """Expected scores of a map that floods the same area as the prediction but at random
    locations. Precision equal to the observed prevalence, or IoU near the chance IoU,
    means the prediction places flooding no better than chance."""
    n = int(mask.sum())
    p = predicted.sum() / n if n else 0.0          # predicted share of the comparison area
    q = observed.sum() / n if n else 0.0           # observed share (prevalence)
    return {
        "comparison_area_km2": n * cell_area_m2 / 1e6,
        "observed_prevalence": float(q),
        "predicted_share": float(p),
        "chance_precision": float(q),
        "chance_recall": float(p),
        "chance_iou": float(p * q / (p + q - p * q)) if p + q else 0.0,
    }


def _simulation_raster(conn, sid: str, name: str):
    storage_path = conn.execute(text(
        "SELECT storage_path FROM floin.simulation_outputs WHERE simulation_id = :sid AND name = :n"),
        {"sid": sid, "n": name}).scalar()
    if storage_path is None:
        raise NotFoundError(f"{sid} has no output {name}")
    local = get_settings().data_dir / "cache" / sid / f"{name}.tif"
    get_storage().download(storage_path.partition("/")[2], local)
    return local


def _reference_geometries(conn, name: str):
    record = resolve(conn, name)
    rows = conn.execute(text("SELECT ST_AsBinary(geom), depth_min_m, depth_max_m, depth_class FROM floin.flood_references "
                             "WHERE dataset_id = :id"), {"id": record["id"]}).all()
    if not rows:
        raise DatasetMissingError(f"reference dataset {name} has no features")
    return record, [(shapely.from_wkb(bytes(r[0])), r[1], r[2], r[3]) for r in rows]


def compare(vid: str, sid: str, event: dict) -> list[dict]:
    with connect() as conn:
        depth_path = _simulation_raster(conn, sid, "flood_depth")
        extent_path = _simulation_raster(conn, sid, "flood_extent")
        params = conn.execute(text("SELECT parameters FROM floin.simulation_runs WHERE id = :id"), {"id": sid}).scalar_one()
        dem_rec = resolve(conn, "dem_30m")
        dom_rec = resolve(conn, "model_domain_30m")
        lc_rec = resolve(conn, "landcover_30m")
        ch_rec = resolve(conn, "channels_30m")
        wards = [shapely.from_wkb(bytes(r[0])) for r in conn.execute(text(
            "SELECT ST_AsBinary(geom) FROM floin.admin_boundaries WHERE boundary_type = 'gcc_ward'")).all()]
        references = {name: _reference_geometries(conn, name) for name in event["extent_references"]}
        benchmark = _reference_geometries(conn, event["benchmark_reference"])
        streets = _reference_geometries(conn, event["street_reference"])
        hotspots = _reference_geometries(conn, event["depth_point_reference"])
        points = _reference_geometries(conn, event["point_reference"])
        # Flood polygons do not overlap, so per-polygon intersection lengths can be summed.
        street_hits = conn.execute(text("""
            SELECT (SELECT sum(ST_Length(geom)) FROM floin.flood_references WHERE dataset_id = :ds),
                   (SELECT sum(ST_Length(ST_Intersection(s.geom, f.geom)))
                    FROM floin.flood_references s
                    JOIN floin.simulation_flood_polygons f ON f.simulation_id = :sid AND ST_Intersects(s.geom, f.geom)
                    WHERE s.dataset_id = :ds)
        """), {"ds": streets[0]["id"], "sid": sid}).one()

    with rasterio.open(depth_path) as src:
        grid = ModelGrid.from_profile(src.profile)
    area = grid.cell_area_m2
    depth = np.nan_to_num(read_float(depth_path, grid, "flood_depth"))
    predicted = read_band(extent_path, grid, "flood_extent")[0]
    predicted = (predicted > 0) & (predicted != 255)
    dem = read_float(fetch_raster(dem_rec), grid, "dem")
    domain = read_band(fetch_raster(dom_rec), grid, "domain")[0] == 1
    water = read_band(fetch_raster(lc_rec), grid, "landcover")[0] == WORLDCOVER_WATER
    channels = read_band(fetch_raster(ch_rec), grid, "channels")[0] == 1
    compare_mask = domain & ~water & ~channels
    ward_mask = features.rasterize(((w, 1) for w in wards), out_shape=grid.shape, transform=grid.transform,
                                   fill=0, dtype="uint8").astype(bool)
    baseline = (dem < BASELINE_ELEVATION_M) & compare_mask
    benchmark_mask = features.rasterize(((g, 1) for g, *_ in benchmark[1]), out_shape=grid.shape,
                                        transform=grid.transform, fill=0, dtype="uint8").astype(bool)
    min_depth = params["min_flood_depth_m"]

    rows = []
    for name, (record, geoms) in references.items():
        observed = features.rasterize(((g, 1) for g, *_ in geoms), out_shape=grid.shape, transform=grid.transform,
                                      fill=0, dtype="uint8").astype(bool)
        for domain_name, mask in (("model_domain", compare_mask), ("gcc_wards", compare_mask & ward_mask)):
            m = binary_metrics(predicted & mask, observed & mask, area)
            m_base = binary_metrics(baseline & mask, observed & mask, area)
            m_bench = binary_metrics(benchmark_mask & mask, observed & mask, area)
            rows.append({"reference": record, "domain": domain_name, "type": "extent", "metrics": m,
                         "details": {"baseline_ground_below_5m": m_base,
                                     f"benchmark_{benchmark[0]['name']}": m_bench,
                                     "chance": chance_extent_metrics(predicted & mask, observed & mask, mask, area)}})

    total_len, hit_len = (float(v or 0) for v in street_hits)
    rows.append({"reference": streets[0], "domain": "model_domain", "type": "line_detection",
                 "metrics": {"recall": hit_len / total_len if total_len else 0.0},
                 "details": {"observed_length_km": total_len / 1000, "inside_predicted_flood_km": hit_len / 1000}})

    # Chance level for the point checks: share of evaluable GCC-ward cells that would count as
    # "wet" with the same 3x3-cell tolerance. A detection rate near this value has no skill.
    wet_near = ndimage.maximum_filter(depth, size=3) >= min_depth
    chance = float(wet_near[compare_mask & ward_mask].mean())
    for reference, with_classes in ((hotspots, True), (points, False)):
        row = _point_metrics(reference, depth, compare_mask, grid, min_depth, with_classes=with_classes)
        row["details"]["chance_detection_rate_gcc_wards"] = chance
        rows.append(row)

    with connect() as conn:
        for r in rows:
            m = r["metrics"]
            conn.execute(text("""
                INSERT INTO floin.validation_metrics (validation_run_id, reference_dataset_id, reference_name,
                    comparison_domain, metric_type, iou, precision, recall, f1, predicted_area_km2,
                    observed_area_km2, area_difference_km2, details)
                VALUES (:vid, :rid, :rname, :dom, :type, :iou, :p, :r, :f1, :pa, :oa, :ad, CAST(:details AS jsonb))
            """), {"vid": vid, "rid": r["reference"]["id"], "rname": r["reference"]["name"], "dom": r["domain"],
                   "type": r["type"], "iou": m.get("iou"), "p": m.get("precision"), "r": m.get("recall"),
                   "f1": m.get("f1"), "pa": m.get("predicted_area_km2"), "oa": m.get("observed_area_km2"),
                   "ad": m.get("area_difference_km2"), "details": json.dumps({**m, **r["details"]}, default=_json_default)})
    return [{"reference": r["reference"]["name"], "domain": r["domain"], "type": r["type"],
             **r["metrics"], "details": r["details"]} for r in rows]


def _point_metrics(reference, depth, mask, grid, min_depth, with_classes):
    record, items = reference
    rows_, cols_ = rasterio.transform.rowcol(grid.transform, [g.x for g, *_ in items], [g.y for g, *_ in items])
    detected_exact = detected_near = evaluated = 0
    agreement = 0
    confusion = {}
    for (geom, lo, hi, label), r, c in zip(items, rows_, cols_):
        if not (0 <= r < grid.height and 0 <= c < grid.width) or not mask[r, c]:
            continue
        evaluated += 1
        d_exact = float(depth[r, c])
        d_near = float(depth[max(r - 1, 0):r + 2, max(c - 1, 0):c + 2].max())   # 3x3 cells: ~45 m positional tolerance
        detected_exact += int(d_exact >= min_depth)
        detected_near += int(d_near >= min_depth)
        if with_classes:
            # Agreement needs a wet prediction: a dry cell is not "<2 ft of flooding".
            ok = bool(d_near >= min_depth and d_near >= (lo or 0) and (hi is None or d_near < hi))
            agreement += int(ok)
            bucket = confusion.setdefault(label, {"n": 0, "predicted_wet": 0, "depth_in_class": 0})
            bucket["n"] += 1
            bucket["predicted_wet"] += int(d_near >= min_depth)
            bucket["depth_in_class"] += int(ok)
    metrics = {"recall": detected_near / evaluated if evaluated else 0.0}
    details = {"points_total": len(items), "points_evaluated": evaluated,
               "detected_exact_cell": detected_exact, "detected_within_1_cell": detected_near,
               "note": "points on permanent water/channels or outside the domain are not evaluated"}
    if with_classes:
        details["depth_class_agreement"] = agreement / evaluated if evaluated else 0.0
        details["by_observed_class"] = confusion
    return {"reference": record, "domain": "model_domain",
            "type": "point_depth_class" if with_classes else "point_detection", "metrics": metrics, "details": details}


def get_validation(vid: str) -> dict:
    with connect() as conn:
        run = conn.execute(text("SELECT * FROM floin.validation_runs WHERE id = :id"), {"id": vid}).mappings().first()
        if run is None:
            raise NotFoundError(f"validation run {vid} not found")
        metrics = conn.execute(text("""
            SELECT reference_name, comparison_domain, metric_type, iou, precision, recall, f1,
                   predicted_area_km2, observed_area_km2, area_difference_km2, details
            FROM floin.validation_metrics WHERE validation_run_id = :id ORDER BY id
        """), {"id": vid}).mappings().all()
    out = {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in dict(run).items()}
    out["metrics"] = [dict(m) for m in metrics]
    return out


def list_validations(limit: int = 20) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(text("""
            SELECT id, event_name, status, parameters, simulation_id, error, created_at, completed_at
            FROM floin.validation_runs ORDER BY created_at DESC LIMIT :n
        """), {"n": limit}).mappings().all()
    return [{k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in dict(r).items()} for r in rows]
