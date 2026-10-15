"""SQL for the dataset catalog. Simulation/validation SQL lives with those services."""
import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

DATASET_COLUMNS = [
    "name", "title", "dataset_type", "category", "stage", "description", "source", "source_url",
    "licence", "format", "storage_kind", "storage_path", "table_name", "crs", "srid",
    "resolution_x", "resolution_y", "width", "height", "min_x", "min_y", "max_x", "max_y",
    "dtype", "nodata_value", "min_value", "max_value", "feature_count", "geometry_type",
    "checksum_sha256", "size_bytes", "version", "status", "quality_notes", "lineage",
]

# Reference-layer tables that a vector dataset may be loaded into.
VECTOR_TABLES = {
    "admin_boundaries", "buildings", "roads", "railways", "rivers",
    "drainage", "water_bodies", "flood_references",
}


def upsert_dataset(conn: Connection, record: dict[str, Any]) -> str:
    """Insert or update a catalog row by name; returns its id. `footprint_wgs84` may be a bbox."""
    values = {col: record.get(col) for col in DATASET_COLUMNS}
    values["lineage"] = json.dumps(record.get("lineage") or {})
    values["version"] = values["version"] or "1"
    bbox = record.get("footprint_wgs84")
    values.update(fx0=None, fy0=None, fx1=None, fy1=None)
    if bbox:
        values.update(fx0=bbox[0], fy0=bbox[1], fx1=bbox[2], fy1=bbox[3])
    columns = ", ".join(DATASET_COLUMNS + ["footprint"])
    params = ", ".join(
        [f"CAST(:{c} AS jsonb)" if c == "lineage" else f":{c}" for c in DATASET_COLUMNS]
        + ["CASE WHEN CAST(:fx0 AS float8) IS NULL THEN NULL ELSE ST_MakeEnvelope(:fx0, :fy0, :fx1, :fy1, 4326) END"]
    )
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in DATASET_COLUMNS[1:] + ["footprint"])
    sql = f"INSERT INTO floin.datasets ({columns}) VALUES ({params}) ON CONFLICT (name) DO UPDATE SET {updates} RETURNING id"
    return str(conn.execute(text(sql), values).scalar_one())


def get_dataset(conn: Connection, name: str) -> dict | None:
    row = conn.execute(
        text("SELECT *, ST_AsGeoJSON(footprint) AS footprint_geojson FROM floin.datasets WHERE name = :n"),
        {"n": name},
    ).mappings().first()
    return _clean(row) if row else None


def list_datasets(conn: Connection, category: str | None = None, status: str | None = None) -> list[dict]:
    sql = "SELECT *, ST_AsGeoJSON(footprint) AS footprint_geojson FROM floin.datasets WHERE TRUE"
    params = {}
    if category:
        sql += " AND category = :category"
        params["category"] = category
    if status:
        sql += " AND status = :status"
        params["status"] = status
    rows = conn.execute(text(sql + " ORDER BY category, name"), params).mappings().all()
    return [_clean(r) for r in rows]


def refresh_vector_stats(conn: Connection, dataset_id: str, table: str) -> dict:
    """Recompute feature count, extent, SRID and geometry types from the loaded rows."""
    if table not in VECTOR_TABLES:
        raise ValueError(f"unknown reference table {table}")
    stats = conn.execute(text(f"""
        SELECT count(*) AS n,
               ST_XMin(ST_Extent(geom)) AS min_x, ST_YMin(ST_Extent(geom)) AS min_y,
               ST_XMax(ST_Extent(geom)) AS max_x, ST_YMax(ST_Extent(geom)) AS max_y,
               string_agg(DISTINCT GeometryType(geom), ',') AS types,
               array_agg(DISTINCT ST_SRID(geom)) AS srids,
               count(*) FILTER (WHERE NOT ST_IsValid(geom)) AS invalid
        FROM floin.{table} WHERE dataset_id = :id
    """), {"id": dataset_id}).mappings().one()
    conn.execute(text("""
        UPDATE floin.datasets SET feature_count = :n, geometry_type = :types, srid = 32644, crs = 'EPSG:32644',
               min_x = :min_x, min_y = :min_y, max_x = :max_x, max_y = :max_y,
               footprint = CASE WHEN CAST(:min_x AS float8) IS NULL THEN NULL ELSE
                   ST_Envelope(ST_Transform(ST_MakeEnvelope(:min_x, :min_y, :max_x, :max_y, 32644), 4326)) END
        WHERE id = :id
    """), {**stats, "id": dataset_id})
    return dict(stats)


def _clean(row) -> dict:
    out = dict(row)
    out["id"] = str(out["id"])
    out.pop("footprint", None)
    geojson = out.pop("footprint_geojson", None)
    out["footprint"] = json.loads(geojson) if geojson else None
    for key in ("created_at", "updated_at"):
        if out.get(key) is not None:
            out[key] = out[key].isoformat()
    return out
