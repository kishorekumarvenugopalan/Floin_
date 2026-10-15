"""End-to-end test through the real HTTP API with the real stored datasets.

Starts uvicorn, POSTs a simulation, polls until it finishes, then checks every
intermediate output independently (files re-read from storage, values re-derived)
and the database rows the run wrote. Writes docs/E2E_RESULT.md.

Usage:  python scripts/run_e2e.py [--rainfall-mm 300] [--duration-hours 24] [--port 8765]
"""
import argparse
import json
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app  # noqa: F401
import httpx
import numpy as np
import rasterio
from sqlalchemy import text

from app.core.config import BACKEND_ROOT
from app.db.database import connect
from app.services.dataset_service import fetch_raster, resolve
from app.services.storage_service import get_storage
from app.simulation.scs_cn import runoff_depth_mm

EXPECTED_OUTPUTS = {"cn", "runoff", "runoff_accumulation", "flood_depth", "water_surface", "flood_extent",
                    "flood_extent_geojson", "metadata"}


class Report:
    def __init__(self):
        self.lines, self.ok = [], True

    def check(self, name, condition, detail=""):
        self.ok &= bool(condition)
        line = f"{'PASS' if condition else 'FAIL'}  {name}" + (f" - {detail}" if detail else "")
        print("  " + line)
        self.lines.append(line)


def start_server(port: int) -> subprocess.Popen:
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port), "--log-level", "warning"],
                            cwd=BACKEND_ROOT)
    for _ in range(60):
        try:
            if httpx.get(f"http://127.0.0.1:{port}/", timeout=2).status_code == 200:
                return proc
        except httpx.HTTPError:
            time.sleep(1)
    proc.kill()
    raise RuntimeError("API server did not start")


def read_output(storage_path: str, tmp: Path):
    key = storage_path.partition("/")[2]
    local = get_storage().download(key, tmp / Path(key).name)
    with rasterio.open(local) as src:
        data = src.read(1, masked=True)
        return data.filled(np.nan).astype("float64") if data.dtype.kind == "f" else data.filled(0), src.profile


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rainfall-mm", type=float, default=300.0)
    parser.add_argument("--duration-hours", type=float, default=24.0)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    r = Report()
    base = f"http://127.0.0.1:{args.port}/api/v1"
    request = {"scenario": "custom", "rainfall_mm": args.rainfall_mm, "duration_hours": args.duration_hours}

    print("FLOIN END-TO-END TEST")
    print("Request:", json.dumps(request))
    server = start_server(args.port)
    try:
        health = httpx.get(f"{base}/health", timeout=30).json()
        r.check("API health", health["status"] == "ok", f"PostGIS {health['postgis'][:12]}..., storage {health['storage']}")
        accepted = httpx.post(f"{base}/simulations", json=request, timeout=30)
        r.check("POST /simulations accepted", accepted.status_code == 202, accepted.text[:120])
        sid = accepted.json()["simulation_id"]
        started = time.time()
        while True:
            run = httpx.get(f"{base}/simulations/{sid}", timeout=30).json()
            if run["status"] in ("completed", "failed"):
                break
            if time.time() - started > 900:
                raise RuntimeError("simulation did not finish in 15 minutes")
            time.sleep(3)
        r.check("simulation completed", run["status"] == "completed", run.get("error") or f"{run['runtime_seconds']:.1f} s")
        if run["status"] != "completed":
            return finish(r, sid, request, None, run)
        results = httpx.get(f"{base}/simulations/{sid}/results", timeout=60).json()
        risk = httpx.get(f"{base}/simulations/{sid}/risk", timeout=60).json()
        flood_geojson = httpx.get(f"{base}/simulations/{sid}/flood", params={"simplify_m": 5}, timeout=300).json()
    finally:
        server.terminate()
        server.wait(timeout=30)

    print("\nInputs resolved from the catalog")
    roles = {i["role"]: i for i in run["inputs"]}
    for role in ("dem", "landcover_10m", "soil_hsg", "flow_direction", "buildings", "roads"):
        r.check(f"input {role}", role in roles, roles.get(role, {}).get("dataset_name", "missing"))

    print("\nIntermediate outputs (re-read from storage)")
    outputs = {o["name"]: o for o in run["outputs"]}
    r.check("all outputs stored", EXPECTED_OUTPUTS <= set(outputs), sorted(set(outputs)))
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        cn, profile = read_output(outputs["cn"]["storage_path"], tmp)
        runoff, _ = read_output(outputs["runoff"]["storage_path"], tmp)
        depth, _ = read_output(outputs["flood_depth"]["storage_path"], tmp)
        classes, _ = read_output(outputs["flood_extent"]["storage_path"], tmp)
        acc, _ = read_output(outputs["runoff_accumulation"]["storage_path"], tmp)
    land = np.isfinite(cn)
    area = abs(profile["transform"].a * profile["transform"].e)
    r.check("CN in (0, 100]", (cn[land] > 0).all() and (cn[land] <= 100).all(),
            f"min {np.nanmin(cn):.1f}, mean {np.nanmean(cn):.1f}, max {np.nanmax(cn):.1f}")
    expected_q = runoff_depth_mm(args.rainfall_mm, cn[land])
    r.check("runoff equals SCS-CN recomputed from stored CN", np.allclose(runoff[land], expected_q, atol=1e-3),
            f"max |diff| {np.nanmax(np.abs(runoff[land] - expected_q)):.2e} mm")
    r.check("0 <= runoff <= rainfall", (runoff[land] >= 0).all() and (runoff[land] <= args.rainfall_mm + 1e-6).all(),
            f"mean runoff {np.nanmean(runoff[land]):.1f} mm of {args.rainfall_mm} mm")
    volume = np.nansum(runoff[land]) / 1000 * area
    hyd = results["hydrology"]
    r.check("runoff volume consistent", abs(volume - hyd["runoff_volume_m3"]) / volume < 1e-5, f"{volume / 1e6:.2f} Mm3")
    with connect() as conn:
        codes_path = fetch_raster(resolve(conn, "terrain_flow_direction_30m"))
    with rasterio.open(codes_path) as src:
        codes = src.read(1)
    outlet_total = np.nansum(acc[(codes == 0) & land])
    r.check("routing conserves volume: sum of accumulation at outlets = total runoff",
            abs(outlet_total - volume) / volume < 1e-5,
            f"outlets {outlet_total / 1e6:.3f} Mm3 vs runoff {volume / 1e6:.3f} Mm3")
    r.check("runoff accumulation >= local runoff", (acc[land] + 1e-3 >= runoff[land] / 1000 * area).all(),
            f"max {np.nanmax(acc) / 1e6:.2f} Mm3")
    wb = results["flood"]["water_balance"]
    r.check("water balance closes", wb["relative_error"] < 1e-6,
            f"runoff {wb['runoff_volume_m3'] / 1e6:.1f} = stored {wb['stored_in_depressions_m3'] / 1e6:.1f} + outflow {wb['left_domain_m3'] / 1e6:.1f} Mm3")
    stored_from_depth = np.nansum(depth) * area
    r.check("depth raster volume equals stored volume", abs(stored_from_depth - wb["stored_in_depressions_m3"]) / stored_from_depth < 1e-4,
            f"{stored_from_depth / 1e6:.2f} Mm3")
    r.check("depth >= 0", np.nanmin(depth) >= 0, f"max {np.nanmax(depth):.2f} m")
    flooded = (classes > 0) & (classes != 255)
    r.check("extent = depth >= threshold (outside water/channels)",
            (depth[flooded] >= results["flood"]["min_flood_depth_m"] - 1e-6).all(),
            f"{flooded.sum() * area / 1e6:.1f} km2 vs reported {results['flood']['flooded_area_km2']:.1f} km2")
    r.check("flood GeoJSON features", len(flood_geojson["features"]) == results["flood"]["polygon_count"],
            f"{len(flood_geojson['features'])} polygons")

    print("\nExposure (recomputed in PostGIS)")
    with connect() as conn:
        n_buildings = conn.execute(text("""
            SELECT count(DISTINCT b.id) FROM floin.buildings b JOIN floin.simulation_flood_polygons f
            ON f.simulation_id = :sid AND ST_Intersects(b.geom, f.geom)"""), {"sid": sid}).scalar_one()
        n_polys = conn.execute(text("SELECT count(*) FROM floin.simulation_flood_polygons WHERE simulation_id = :sid"),
                               {"sid": sid}).scalar_one()
        wards = conn.execute(text("SELECT count(*) FROM floin.simulation_ward_summary WHERE simulation_id = :sid"),
                             {"sid": sid}).scalar_one()
    exp = results["exposure"]
    r.check("flood polygons stored in PostGIS", n_polys == results["flood"]["polygon_count"], n_polys)
    r.check("affected buildings match ST_Intersects", n_buildings == exp["buildings"]["affected"],
            f"{n_buildings:,} of {exp['buildings']['total_in_layer']:,}")
    r.check("affected roads reported", exp["roads"]["affected_km"] > 0, f"{exp['roads']['affected_km']:.1f} km of {exp['roads']['total_km']:.0f} km")
    r.check("ward summary written", wards == exp["wards"]["wards_with_flooding"], f"{wards} wards")
    r.check("risk not overstated", risk["risk"]["status"] == "not_computed", risk["risk"]["reason"][:70])
    finish(r, sid, request, results, run)


def finish(r: Report, sid, request, results, run):
    print(f"\nOverall: {'PASS' if r.ok else 'FAIL'}")
    out = BACKEND_ROOT / "docs" / "E2E_RESULT.md"
    out.parent.mkdir(exist_ok=True)
    body = [
        "# FLOIN end-to-end result", "",
        f"Run {datetime.now(timezone.utc).isoformat(timespec='seconds')} by `scripts/run_e2e.py` through the HTTP API.", "",
        f"- Simulation: `{sid}`", f"- Request: `{json.dumps(request)}`", f"- Status: {run['status']}",
        f"- Runtime: {run.get('runtime_seconds') or 0:.1f} s", f"- Overall: **{'PASS' if r.ok else 'FAIL'}**", "",
        "## Checks", "", "```", *r.lines, "```", "",
    ]
    if results:
        f, h, e = results["flood"], results["hydrology"], results["exposure"]
        body += [
            "## Key results", "",
            f"- Mean curve number: {h['curve_number']['mean']:.1f} (AMC {h['curve_number']['antecedent_moisture']})",
            f"- Mean runoff: {h['runoff_mm']['mean']:.1f} mm; runoff volume {h['runoff_volume_m3'] / 1e6:.1f} million m3",
            f"- Stored in depressions: {f['water_balance']['stored_in_depressions_m3'] / 1e6:.1f} million m3; "
            f"left the domain: {f['water_balance']['left_domain_m3'] / 1e6:.1f} million m3",
            f"- Flooded area (depth >= {f['min_flood_depth_m']} m): {f['flooded_area_km2']:.1f} km2; "
            f"max depth {f['max_depth_m']:.2f} m; mean depth {f['mean_depth_m']:.2f} m",
            f"- By depth class (km2): {json.dumps({k: round(v['area_km2'], 1) for k, v in f['by_class'].items()})}",
            f"- Buildings affected: {e['buildings']['affected']:,} of {e['buildings']['total_in_layer']:,} OSM footprints",
            f"- At-grade roads inside flood polygons: {e['roads']['affected_km']:.1f} km of {e['roads']['total_km']:.0f} km "
            f"(bridges/tunnels excluded: {e['roads']['excluded_bridge_or_tunnel_km']:.1f} km)",
            f"- At-grade track inside flood polygons: {e['railways']['affected_rail_km']:.2f} km rail, "
            f"{e['railways']['affected_metro_km']:.2f} km metro (elevated/underground excluded: "
            f"{e['railways']['excluded_bridge_or_tunnel_rail_km']:.2f} km rail, "
            f"{e['railways']['excluded_bridge_or_tunnel_metro_km']:.2f} km metro)",
            "",
        ]
    out.write_text("\n".join(body), encoding="utf-8")
    print(f"Report: {out}")
    sys.exit(0 if r.ok else 1)


if __name__ == "__main__":
    main()
