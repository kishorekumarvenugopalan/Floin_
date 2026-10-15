from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Query
from pydantic import BaseModel, Field

from app.core.logging import get_logger
from app.services import validation_service

router = APIRouter(tags=["validation"])
log = get_logger("api.validation")


class Validation2015Request(BaseModel):
    antecedent_conditions: list[Literal["I", "II", "III"]] = Field(["II", "III"], min_length=1, max_length=3)


def _run_all(ids: list[str]) -> None:
    for vid in ids:
        try:
            validation_service.run_validation(vid)
        except Exception:
            log.error("validation %s failed", vid)


@router.post("/validation/2015", status_code=202)
def validate_2015(request: Validation2015Request, background: BackgroundTasks):
    """Run FLOIN with CHIRPS 30 Nov - 2 Dec 2015 rainfall and compare with 2015 observations."""
    ids = validation_service.create_validation_runs("chennai_2015_dec", request.antecedent_conditions)
    background.add_task(_run_all, ids)
    return {"validation_ids": ids, "status": "queued", "links": [f"/api/v1/validation/{v}" for v in ids]}


@router.get("/validation")
def list_validations(limit: int = Query(20, ge=1, le=200)):
    """Recent validation runs (newest first)."""
    return validation_service.list_validations(limit)


@router.get("/validation/{vid}")
def get_validation(vid: str):
    return validation_service.get_validation(vid)
