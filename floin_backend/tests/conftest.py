import pytest
from sqlalchemy import text

import app  # noqa: F401  (GDAL/PROJ isolation before rasterio is imported)
from app.core.errors import FloinError
from app.db.database import connect


def _database_ready() -> bool:
    try:
        with connect() as conn:
            return conn.execute(text("SELECT to_regclass('floin.datasets') IS NOT NULL")).scalar_one()
    except FloinError:
        return False
    except Exception:
        return False


DATABASE_READY = _database_ready()
requires_db = pytest.mark.skipif(not DATABASE_READY, reason="DATABASE_URL not configured or migrations not applied")


@pytest.fixture
def conn():
    with connect() as c:
        yield c
