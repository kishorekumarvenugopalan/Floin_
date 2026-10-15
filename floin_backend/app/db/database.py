from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import OperationalError

from app.core.config import get_settings
from app.core.errors import DatabaseUnavailableError

_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        url = get_settings().database_url
        if not url or "<PASSWORD>" in url:
            raise DatabaseUnavailableError("DATABASE_URL is not configured; copy .env.example to .env and fill it in")
        _engine = create_engine(url, pool_pre_ping=True, pool_recycle=300)
    return _engine


@contextmanager
def connect() -> Iterator[Connection]:
    """Transactional connection: commits on success, rolls back on any exception."""
    try:
        with get_engine().begin() as conn:
            yield conn
    except OperationalError as exc:
        raise DatabaseUnavailableError(f"Database connection failed: {exc.orig}") from exc


def get_connection() -> Iterator[Connection]:
    """FastAPI dependency."""
    with connect() as conn:
        yield conn


def postgis_version(conn: Connection) -> str:
    return conn.execute(text("SELECT PostGIS_Full_Version()")).scalar_one()
