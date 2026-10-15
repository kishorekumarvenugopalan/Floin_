"""Inventory every data file FLOIN can see, before anything is loaded.

For vectors: format, CRS, geometry types, feature count, extent, attributes, and two
placeholder signals (very few features; coordinates with <= 3 decimals and simple
shapes, which is how the hand-drawn rectangles in the supplied archive look).
For rasters: CRS, resolution, size, extent, NoData, value range.
Also reports whether each file is registered in floin.datasets (if a database is configured).

Writes data/reports/dataset_inventory.csv and prints a summary.

Usage:  python scripts/inspect_data.py
"""
import csv
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app  # noqa: F401
import numpy as np
import rasterio
from rasterio.warp import transform_bounds
from sqlalchemy import text

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.database import connect
from app.gis.raster import sha256_file

FIELDS = ["path", "kind", "format", "crs", "geometry_types", "features", "null_geometries", "max_coordinate_decimals",
          "vertices_per_feature", "placeholder_signals", "resolution", "size", "nodata", "value_range",
          "extent_wgs84", "attributes", "sha256", "catalog_status", "error"]


def _coords(geometry):
    if geometry is None:
        return
    if geometry["type"] == "GeometryCollection":
        for g in geometry["geometries"]:
            yield from _coords(g)
        return

    def walk(c):
        if c and isinstance(c[0], (int, float)):
            yield c
        else:
            for x in c:
                yield from walk(x)
    yield from walk(geometry.get("coordinates") or [])


def inspect_geojson(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    features = payload.get("features") if isinstance(payload, dict) else None
    if not isinstance(features, list) or (features and not isinstance(features[0], dict)):
        return {"error": "not a valid GeoJSON FeatureCollection"}
    types, keys, xs, ys, null_geom, vertices, decimals = Counter(), set(), [], [], 0, 0, 0
    for f in features:
        g = f.get("geometry")
        keys |= set((f.get("properties") or {}).keys())
        if not g:
            null_geom += 1
            continue
        types[g["type"]] += 1
        for c in _coords(g):
            vertices += 1
            xs.append(c[0])
            ys.append(c[1])
            for v in c[:2]:
                text_value = repr(float(v))
                decimals = max(decimals, len(text_value.split(".")[1].rstrip("0")) if "." in text_value else 0)
    n = len(features)
    signals = []
    if n <= 3:
        signals.append("<=3 features")
    if xs and decimals <= 3 and vertices <= 40 * max(n, 1):
        signals.append("round coordinates, simple shapes")
    crs = (payload.get("crs") or {}).get("properties", {}).get("name", "unspecified (WGS 84 per RFC 7946)")
    return {
        "format": "GeoJSON", "crs": crs, "geometry_types": dict(types), "features": n, "null_geometries": null_geom,
        "max_coordinate_decimals": decimals, "vertices_per_feature": round(vertices / max(n, 1), 1),
        "placeholder_signals": "; ".join(signals),
        "extent_wgs84": [round(min(xs), 4), round(min(ys), 4), round(max(xs), 4), round(max(ys), 4)] if xs else None,
        "attributes": ", ".join(sorted(keys))[:200],
    }


def inspect_raster(path: Path) -> dict:
    with rasterio.open(path) as src:
        data = src.read(1, masked=True)
        valid = data.compressed()
        return {
            "format": src.driver, "crs": src.crs.to_string()[:60] if src.crs else None,
            "resolution": [abs(src.res[0]), abs(src.res[1])], "size": [src.width, src.height], "nodata": src.nodata,
            "value_range": [float(valid.min()), float(valid.max())] if valid.size else None,
            "extent_wgs84": [round(v, 4) for v in transform_bounds(src.crs, "EPSG:4326", *src.bounds)] if src.crs else None,
        }


def main() -> None:
    configure_logging("WARNING")
    s = get_settings()
    roots = [s.raw_dir, *s.vector_source_dirs]
    files = sorted({p.resolve() for root in roots if root.exists() for p in root.rglob("*")
                    if p.is_file() and p.suffix.lower() in (".geojson", ".json", ".tif", ".csv", ".gz")
                    and "tiles" not in p.parts})
    registered = {}
    try:
        with connect() as conn:
            for name, status, lineage, title in conn.execute(text("SELECT name, status, lineage, title FROM floin.datasets")):
                for src in (lineage or {}).get("sources", []):
                    registered[src["file"]] = status
                registered[title] = status
                registered[Path(str((lineage or {}).get("file") or "")).name] = status
    except Exception as exc:
        print(f"(database not available: {exc}; catalog status omitted)")

    rows = []
    for path in files:
        row = {"path": str(path), "sha256": sha256_file(path)[:16]}
        try:
            if path.suffix.lower() == ".geojson":
                row.update(kind="vector", **inspect_geojson(path))
            elif path.suffix.lower() == ".tif":
                row.update(kind="raster", **inspect_raster(path))
            else:
                row.update(kind="table/archive", format=path.suffix.lstrip("."))
        except Exception as exc:
            row["error"] = str(exc)[:200]
        row["catalog_status"] = registered.get(path.name, "")
        rows.append(row)

    out = s.data_dir / "reports" / "dataset_inventory.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: (json.dumps(v) if isinstance(v, (list, dict)) else v) for k, v in row.items() if k in FIELDS})

    vectors = [r for r in rows if r.get("kind") == "vector"]
    print(f"Files inspected: {len(rows)} ({len(vectors)} vector, {sum(r.get('kind') == 'raster' for r in rows)} raster)")
    print(f"Vector files with placeholder signals: {sum(bool(r.get('placeholder_signals')) for r in vectors)}")
    print(f"Unreadable files: {sum(bool(r.get('error')) for r in rows)}")
    print(f"Registered in catalog: {sum(bool(r['catalog_status']) for r in rows)}")
    print(f"Inventory: {out}")


if __name__ == "__main__":
    main()
