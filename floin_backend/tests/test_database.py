"""Integration tests against the configured database (skipped when it is not available)."""
from pathlib import Path

import pytest
from sqlalchemy import text

from app.services.dataset_service import fetch_raster, resolve
from app.core.errors import DatasetMissingError
from tests.conftest import requires_db

pytestmark = requires_db


def test_postgis_functions(conn):
    row = conn.execute(text("""
        SELECT PostGIS_Version(),
               ST_Area(ST_Transform(ST_MakeEnvelope(80.2, 13.0, 80.21, 13.01, 4326), 32644)) BETWEEN 1.1e6 AND 1.3e6
    """)).one()
    assert row[0] and row[1]


def test_all_migrations_applied(conn):
    files = sorted(p.stem for p in (Path(__file__).parents[1] / "database" / "migrations").glob("*.sql"))
    applied = [r[0] for r in conn.execute(text("SELECT version FROM floin.schema_migrations ORDER BY version"))]
    assert applied == files


def test_every_geometry_column_has_a_gist_index(conn):
    missing = conn.execute(text("""
        SELECT g.f_table_name FROM geometry_columns g
        WHERE g.f_table_schema = 'floin' AND NOT EXISTS (
            SELECT 1 FROM pg_indexes i WHERE i.schemaname = 'floin' AND i.tablename = g.f_table_name
              AND i.indexdef ILIKE '%gist%' AND i.indexdef ILIKE '%' || g.f_geometry_column || '%')
    """)).scalars().all()
    assert missing == []


def test_catalog_vector_counts_match_tables(conn):
    rows = conn.execute(text("""
        SELECT name, table_name, feature_count FROM floin.datasets
        WHERE storage_kind = 'postgis' AND status <> 'rejected'
    """)).all()
    assert rows, "no vector datasets loaded"
    for name, table, expected in rows:
        actual = conn.execute(text(f"SELECT count(*) FROM {table} d JOIN floin.datasets c ON c.id = d.dataset_id "
                                   "WHERE c.name = :n"), {"n": name}).scalar_one()
        assert actual == expected, name


def test_reference_layers_are_valid_and_projected(conn):
    for table in ("admin_boundaries", "rivers", "drainage", "water_bodies", "flood_references"):
        bad = conn.execute(text(f"SELECT count(*) FROM floin.{table} WHERE NOT ST_IsValid(geom) OR ST_SRID(geom) <> 32644")).scalar_one()
        assert bad == 0, table


def test_spatial_query_wards_intersect_drains(conn):
    n = conn.execute(text("""
        SELECT count(DISTINCT w.id) FROM floin.admin_boundaries w
        JOIN floin.drainage d ON ST_Intersects(w.geom, d.geom)
    """)).scalar_one()
    assert n > 150    # storm-water drains exist in most of the 200 GCC wards


def test_raster_retrieval_matches_catalog(conn):
    record = resolve(conn, "dem_30m")
    path = fetch_raster(record)
    assert path.exists()


def test_unknown_and_rejected_datasets_are_refused(conn):
    with pytest.raises(DatasetMissingError):
        resolve(conn, "does_not_exist")
    rejected = conn.execute(text("SELECT name FROM floin.datasets WHERE status = 'rejected' LIMIT 1")).scalar()
    if rejected:
        with pytest.raises(DatasetMissingError):
            resolve(conn, rejected)
