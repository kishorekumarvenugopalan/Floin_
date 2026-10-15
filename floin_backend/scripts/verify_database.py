"""Verify the FLOIN database, storage and every catalogued dataset against reality.

Every number printed is queried from the database or recomputed from the stored files.
Writes docs/DATA_VALIDATION_REPORT.md and data/reports/database_verification.json.
Exit code 1 if any check fails.

Usage:  python scripts/verify_database.py
"""
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app  # noqa: F401
import numpy as np
import rasterio
from sqlalchemy import text

from app.core.config import BACKEND_ROOT, MODEL_AREA_WGS84, get_settings
from app.core.logging import configure_logging
from app.db.database import connect, postgis_version
from app.db.repositories import list_datasets
from app.gis.grid import ModelGrid
from app.gis.raster import sha256_file
from app.services.simulation_service import REQUIRED_DATASETS, REQUIRED_VECTOR_DATASETS
from app.services.storage_service import get_storage
from app.services.validation_events import CHENNAI_2015

EXPECTED_TABLES = [
    "datasets", "schema_migrations", "admin_boundaries", "buildings", "roads", "railways", "rivers", "drainage",
    "water_bodies", "flood_references", "simulation_runs", "simulation_inputs", "simulation_outputs",
    "simulation_results", "simulation_flood_polygons", "simulation_ward_summary", "validation_runs", "validation_metrics",
]
CRITICAL = {**REQUIRED_DATASETS, **REQUIRED_VECTOR_DATASETS, "rainfall_2015": CHENNAI_2015["rainfall_dataset"],
            "flood_2015": "flood_2015_inundation", "rivers": "gcc_basin_rivers", "drainage": "gcc_storm_water_drains_2023"}


class Checks:
    def __init__(self):
        self.results = []

    def add(self, name, ok, detail=""):
        self.results.append({"check": name, "ok": bool(ok), "detail": detail})
        print(f"  {'PASS' if ok else 'FAIL'}  {name}{': ' + str(detail) if detail else ''}")
        return ok

    @property
    def ok(self):
        return all(r["ok"] for r in self.results)


def verify_database(c: Checks, conn) -> None:
    print("\nDatabase")
    c.add("PostgreSQL connection", True, conn.execute(text("SELECT version()")).scalar_one().split(",")[0])
    c.add("PostGIS", True, postgis_version(conn).split('"')[1] if '"' in postgis_version(conn) else postgis_version(conn))
    fn = conn.execute(text("""
        WITH a AS (SELECT ST_Transform(ST_GeomFromText('POLYGON((80.2 13.0,80.21 13.0,80.21 13.01,80.2 13.01,80.2 13.0))', 4326), 32644) g),
             b AS (SELECT ST_Transform(ST_GeomFromText('POINT(80.205 13.005)', 4326), 32644) p,
                          ST_Transform(ST_GeomFromText('LINESTRING(80.19 13.005,80.22 13.005)', 4326), 32644) l)
        SELECT ST_Intersects(a.g, b.p), ST_Contains(a.g, b.p), ST_Within(b.p, a.g),
               round(ST_Length(ST_Intersection(a.g, b.l))), round(ST_Area(a.g))
        FROM a, b
    """)).one()
    c.add("spatial functions (ST_GeomFromText/Transform/Intersects/Contains/Within/Intersection/Length/Area)",
          fn[0] and fn[1] and fn[2] and 1000 < fn[3] < 1150 and 1.1e6 < fn[4] < 1.3e6, f"length {fn[3]} m, area {fn[4]} m2")

    files = sorted(p.stem for p in (BACKEND_ROOT / "database" / "migrations").glob("*.sql"))
    applied = [r[0] for r in conn.execute(text("SELECT version FROM floin.schema_migrations ORDER BY version")).all()]
    c.add("migrations applied", files == applied, f"{len(applied)}/{len(files)}")

    existing = {r[0] for r in conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'floin'")).all()}
    c.add("tables exist", set(EXPECTED_TABLES) <= existing, f"missing: {sorted(set(EXPECTED_TABLES) - existing)}" if set(EXPECTED_TABLES) - existing else f"{len(existing)} tables")

    geom_cols = conn.execute(text("""
        SELECT f_table_name, f_geometry_column, srid, type FROM geometry_columns WHERE f_table_schema = 'floin'
    """)).all()
    gist = {(r[0], r[1]) for r in conn.execute(text("""
        SELECT t.relname, a.attname FROM pg_index i
        JOIN pg_class t ON t.oid = i.indrelid JOIN pg_class ix ON ix.oid = i.indexrelid
        JOIN pg_am am ON am.oid = ix.relam JOIN pg_namespace n ON n.oid = t.relnamespace
        JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(i.indkey)
        WHERE n.nspname = 'floin' AND am.amname = 'gist'
    """)).all()}
    missing_gist = [f"{t}.{col}" for t, col, _, _ in geom_cols if (t, col) not in gist]
    c.add("spatial (GIST) index on every geometry column", not missing_gist, missing_gist or f"{len(geom_cols)} columns")
    bad_srid = [f"{t}.{col}={srid}" for t, col, srid, _ in geom_cols if srid not in (32644, 4326)]
    c.add("geometry SRIDs", not bad_srid, bad_srid or "32644 (layers) / 4326 (catalog footprints)")
    rls = conn.execute(text("SELECT count(*) FROM pg_tables WHERE schemaname = 'floin' AND NOT rowsecurity")).scalar_one()
    c.add("row level security enabled on floin tables", rls <= 1, f"{rls} table(s) without RLS (schema_migrations is created before 007)")

    print("\nTable row counts")
    for t in EXPECTED_TABLES:
        if t in existing:
            print(f"  {t:28} {conn.execute(text(f'SELECT count(*) FROM floin.{t}')).scalar_one():>9,}")


def verify_vector(c: Checks, conn, d: dict) -> dict:
    table = d["table_name"].split(".")[1]
    stats = conn.execute(text(f"""
        SELECT count(*), count(*) FILTER (WHERE NOT ST_IsValid(geom)), array_agg(DISTINCT ST_SRID(geom)),
               count(*) FILTER (WHERE NOT ST_Intersects(geom, ST_Transform(ST_MakeEnvelope(:w,:s,:e,:n,4326), 32644)))
        FROM floin.{table} WHERE dataset_id = :id
    """), {"id": d["id"], "w": MODEL_AREA_WGS84[0], "s": MODEL_AREA_WGS84[1], "e": MODEL_AREA_WGS84[2],
           "n": MODEL_AREA_WGS84[3]}).one()
    n, invalid, srids, outside = stats
    ok = n == d["feature_count"] and n > 0 and invalid == 0 and srids == [32644] and outside == 0
    c.add(f"vector {d['name']}", ok, f"{n:,} rows in {d['table_name']}, invalid {invalid}, SRID {srids}, outside area {outside}")
    return {"rows": n, "invalid": invalid, "srids": srids, "outside_model_area": outside, "readable": True, "usable": ok}


def verify_raster(c: Checks, d: dict) -> dict:
    storage = get_storage()
    key = d["storage_path"].partition("/")[2]
    if not storage.exists(key):
        c.add(f"raster {d['name']}", False, f"storage object missing: {d['storage_path']}")
        return {"readable": False, "usable": False}
    with tempfile.TemporaryDirectory() as tmp:
        local = storage.download(key, Path(tmp) / Path(key).name)
        checksum_ok = sha256_file(local) == d["checksum_sha256"]
        with rasterio.open(local) as src:
            data = src.read(1, masked=True)
            valid = data.compressed()
            facts = {
                "crs": src.crs.to_string(), "resolution": [abs(src.res[0]), abs(src.res[1])],
                "bounds": list(src.bounds), "nodata": src.nodata, "dtype": src.dtypes[0],
                "min": float(valid.min()) if valid.size else None, "max": float(valid.max()) if valid.size else None,
                "valid_fraction": float(valid.size / data.size), "profile": src.profile,
            }
    same = (checksum_ok and facts["crs"] == d["crs"] and np.allclose(facts["resolution"], [d["resolution_x"], d["resolution_y"]])
            and facts["nodata"] == d["nodata_value"] and facts["min"] == d["min_value"] and facts["max"] == d["max_value"]
            and facts["valid_fraction"] > 0)
    c.add(f"raster {d['name']}", same,
          f"{d['storage_path']} sha256 {'ok' if checksum_ok else 'MISMATCH'}, {facts['dtype']}, "
          f"res {facts['resolution'][0]:.6g}, nodata {facts['nodata']}, range {facts['min']:.4g}..{facts['max']:.4g}")
    facts["readable"] = True
    facts["usable"] = same
    return facts


def main() -> None:
    configure_logging("WARNING")
    c = Checks()
    print("FLOIN DATABASE VERIFICATION")
    print("===========================")
    details = {}
    with connect() as conn:
        verify_database(c, conn)
        datasets = list_datasets(conn)
        counts = {s: sum(d["status"] == s for d in datasets) for s in ("available", "limited", "rejected")}
        print(f"\nDataset catalog: {len(datasets)} entries {counts}")
        by_name = {d["name"]: d for d in datasets}
        for role, name in CRITICAL.items():
            d = by_name.get(name)
            c.add(f"required dataset {role}", d is not None and d["status"] in ("available", "limited"),
                  f"{name}: {d['status'] if d else 'NOT REGISTERED'}")
        print("\nVector datasets (PostGIS)")
        for d in datasets:
            if d["storage_kind"] == "postgis" and d["status"] != "rejected":
                details[d["name"]] = verify_vector(c, conn, d)

    print("\nRaster datasets (storage)")
    storage = get_storage()
    c.add("storage connectivity", True, f"{storage.kind} bucket '{storage.bucket}', {len(storage.list(''))} objects")
    profiles = {}
    for d in datasets:
        if d["storage_kind"] == "storage" and d["status"] != "rejected":
            details[d["name"]] = verify_raster(c, d)
            if d["stage"] == "processed" and "profile" in details[d["name"]]:
                profiles[d["name"]] = details[d["name"]].pop("profile")
            else:
                details[d["name"]].pop("profile", None)

    grid = ModelGrid.from_profile(profiles["dem_30m"]) if "dem_30m" in profiles else None
    misaligned = []
    for name, profile in profiles.items():
        try:
            grid.require_aligned(profile, name)
        except Exception as exc:
            misaligned.append(str(exc))
    c.add("processed rasters share one grid (CRS, transform, shape)", grid is not None and not misaligned,
          misaligned or (f"{len(profiles)} rasters on {grid.crs.to_string()} {grid.resolution} m {grid.height}x{grid.width}" if grid else "no grid"))

    # A dataset that cannot be retrieved or does not match its catalog entry must not stay
    # marked usable: downgrade it so the model refuses it with a clear reason.
    unusable = [d for d in datasets if d["name"] in details and not details[d["name"]].get("usable")]
    if unusable:
        with connect() as conn:
            for d in unusable:
                conn.execute(text("""
                    UPDATE floin.datasets SET status = 'missing',
                           quality_notes = concat_ws(' ', quality_notes, CAST(:note AS text)) WHERE id = :id
                """), {"id": d["id"], "note": f"[verify_database {datetime.now(timezone.utc):%Y-%m-%d}: failed retrieval/consistency check]"})
                print(f"  catalog: {d['name']} downgraded to 'missing'")

    overall = "PASS" if c.ok else "FAIL"
    print(f"\nOverall: {overall}  ({sum(r['ok'] for r in c.results)}/{len(c.results)} checks passed)")
    write_reports(c, datasets, details, overall)
    sys.exit(0 if c.ok else 1)


def write_reports(c: Checks, datasets, details, overall) -> None:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    reports = get_settings().data_dir / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "database_verification.json").write_text(
        json.dumps({"generated": now, "overall": overall, "checks": c.results, "datasets": details}, indent=2, default=str),
        encoding="utf-8")
    lines = [
        "# FLOIN Data Validation Report", "",
        f"Generated {now} by `scripts/verify_database.py` from the live database and storage. Overall: **{overall}**.", "",
    ]
    for d in datasets:
        f = details.get(d["name"], {})
        lines += [f"## {d['title']}", "", "| Field | Value |", "|---|---|"]
        rows = [
            ("Catalog name", f"`{d['name']}`"), ("Status", d["status"]), ("Type / stage", f"{d['dataset_type']} / {d['stage']}"),
            ("Category", d["category"]), ("Source", d.get("source") or ""), ("Licence", d.get("licence") or ""),
            ("Storage", d["storage_path"] or d["table_name"] or "not stored"),
            ("CRS", (d.get("crs") or "")[:60]), ("SRID", d.get("srid")),
        ]
        if d["dataset_type"] == "raster":
            rows += [("Resolution", f"{d['resolution_x']:.6g} x {d['resolution_y']:.6g}" if d.get("resolution_x") else ""),
                     ("Size (cols x rows)", f"{d.get('width')} x {d.get('height')}"),
                     ("Bounds", f"{d.get('min_x'):.6g}, {d.get('min_y'):.6g}, {d.get('max_x'):.6g}, {d.get('max_y'):.6g}" if d.get("min_x") is not None else ""),
                     ("NoData", d.get("nodata_value")), ("Minimum", d.get("min_value")), ("Maximum", d.get("max_value")),
                     ("Valid-cell fraction", f"{f['valid_fraction']:.3f}" if "valid_fraction" in f else "")]
        else:
            rows += [("Features", d.get("feature_count")), ("Geometry", d.get("geometry_type")),
                     ("Invalid geometries", f.get("invalid", "")),
                     ("Extent (EPSG:32644)", f"{d.get('min_x'):.0f}, {d.get('min_y'):.0f}, {d.get('max_x'):.0f}, {d.get('max_y'):.0f}" if d.get("min_x") is not None else "")]
        rows += [("Readable", "YES" if f.get("readable") else ("n/a" if d["status"] == "rejected" else "NO")),
                 ("Usable", "YES" if f.get("usable") else ("NO (rejected)" if d["status"] == "rejected" else "NO")),
                 ("Notes", (d.get("quality_notes") or "").replace("|", "/"))]
        lines += [f"| {k} | {v if v is not None else ''} |" for k, v in rows] + [""]
    out = BACKEND_ROOT / "docs" / "DATA_VALIDATION_REPORT.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"Report: {out}")


if __name__ == "__main__":
    main()
