from fastapi import APIRouter, Depends, Query
from sqlalchemy.engine import Connection

from app.core.errors import NotFoundError
from app.db.database import get_connection
from app.db.repositories import get_dataset, list_datasets

router = APIRouter(tags=["datasets"])


@router.get("/datasets")
def datasets(category: str | None = Query(None), status: str | None = Query(None),
             conn: Connection = Depends(get_connection)):
    return list_datasets(conn, category, status)


@router.get("/datasets/{name}")
def dataset(name: str, conn: Connection = Depends(get_connection)):
    record = get_dataset(conn, name)
    if record is None:
        raise NotFoundError(f"dataset {name} not found")
    return record
