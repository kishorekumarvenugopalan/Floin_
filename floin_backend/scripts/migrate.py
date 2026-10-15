"""Apply database/migrations/*.sql in order and record them in floin.schema_migrations.

Safe to re-run: applied migrations are skipped, and a changed file that was already
applied is an error (write a new migration instead of editing an old one).

If the database still has the pre-migration FLOIN schema (floin.dataset_registry from
the old sql/001_schema.sql), that schema is renamed to floin_legacy, not dropped.

Usage:  python scripts/migrate.py [--status]
"""
import argparse
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app  # noqa: F401
from sqlalchemy import text

from app.core.logging import configure_logging, get_logger
from app.db.database import connect

log = get_logger("migrate")
MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "database" / "migrations"


def table_exists(conn, schema, table) -> bool:
    return conn.execute(
        text("SELECT to_regclass(:name) IS NOT NULL"), {"name": f"{schema}.{table}"}
    ).scalar_one()


def preserve_legacy_schema(conn) -> None:
    if table_exists(conn, "floin", "dataset_registry") and not table_exists(conn, "floin", "schema_migrations"):
        if conn.execute(text("SELECT 1 FROM pg_namespace WHERE nspname = 'floin_legacy'")).first():
            raise RuntimeError("Legacy floin schema found but floin_legacy already exists; resolve manually")
        conn.execute(text("ALTER SCHEMA floin RENAME TO floin_legacy"))
        log.warning("Legacy FLOIN schema renamed to floin_legacy (data kept, not dropped)")


def bootstrap(conn) -> None:
    conn.execute(text("CREATE SCHEMA IF NOT EXISTS floin"))
    conn.execute(text(
        "CREATE TABLE IF NOT EXISTS floin.schema_migrations ("
        " version text PRIMARY KEY, checksum text NOT NULL, applied_at timestamptz NOT NULL DEFAULT now())"
    ))


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser()
    parser.add_argument("--status", action="store_true", help="list migrations without applying")
    args = parser.parse_args()

    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    with connect() as conn:
        preserve_legacy_schema(conn)
        bootstrap(conn)
        applied = dict(conn.execute(text("SELECT version, checksum FROM floin.schema_migrations")).all())

    for path in files:
        sql = path.read_text(encoding="utf-8")
        checksum = hashlib.sha256(sql.encode()).hexdigest()
        version = path.stem
        if version in applied:
            if applied[version] != checksum:
                raise RuntimeError(f"{path.name} changed after it was applied; add a new migration instead")
            log.info("%-28s applied", version)
            continue
        if args.status:
            log.info("%-28s PENDING", version)
            continue
        with connect() as conn:  # one transaction per migration
            # Raw cursor with no parameters, so '%' in format() strings is not a placeholder.
            conn.connection.dbapi_connection.cursor().execute(sql)
            conn.execute(
                text("INSERT INTO floin.schema_migrations(version, checksum) VALUES (:v, :c)"),
                {"v": version, "c": checksum},
            )
        log.info("%-28s APPLIED", version)


if __name__ == "__main__":
    main()
