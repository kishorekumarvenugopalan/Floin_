from fastapi import APIRouter
from sqlalchemy import text

from app.core.errors import FloinError
from app.db.database import connect, postgis_version
from app.services.storage_service import get_storage

router = APIRouter(tags=["health"])


@router.get("/health")
def health():
    report = {"status": "ok", "database": None, "postgis": None, "storage": None, "datasets": None}
    try:
        with connect() as conn:
            report["database"] = conn.execute(text("SELECT version()")).scalar_one()
            report["postgis"] = postgis_version(conn)
            rows = conn.execute(text("SELECT status, count(*) FROM floin.datasets GROUP BY status")).all()
            report["datasets"] = {status: n for status, n in rows}
    except FloinError as exc:
        report.update(status="degraded", database=f"unavailable: {exc.message}")
    except Exception as exc:  # report, don't crash the health endpoint
        report.update(status="degraded", database=f"error: {exc}")
    try:
        storage = get_storage()
        report["storage"] = {"backend": storage.kind, "bucket": storage.bucket,
                             "objects": len(storage.list("processed"))}
    except Exception as exc:
        report.update(status="degraded", storage=f"unavailable: {exc}")
    return report
