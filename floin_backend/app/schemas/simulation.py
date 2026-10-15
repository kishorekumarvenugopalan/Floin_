from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.simulation.flood_extent import DEFAULT_CLASS_BREAKS, DEFAULT_MIN_DEPTH_M


class SimulationRequest(BaseModel):
    """One event simulation. Give exactly one of rainfall_mm (uniform depth over the
    domain) or rainfall_dataset (a registered rainfall raster on the model grid)."""

    scenario: str = Field("custom", min_length=1, max_length=80)
    rainfall_mm: float | None = Field(None, gt=0, le=2000, description="Uniform event rainfall depth (mm)")
    rainfall_dataset: str | None = Field(None, description="Catalog name of a rainfall raster on the model grid")
    duration_hours: float = Field(..., gt=0, le=240, description="Event duration; recorded (the model is event-total based)")
    antecedent_moisture: Literal["I", "II", "III"] = "II"
    ia_ratio: float = Field(0.2, gt=0, le=0.3, description="Initial abstraction ratio, Ia = ratio x S")
    min_flood_depth_m: float = Field(DEFAULT_MIN_DEPTH_M, gt=0, le=1.0)
    depth_class_breaks_m: list[float] = Field(list(DEFAULT_CLASS_BREAKS), min_length=1, max_length=6)

    @model_validator(mode="after")
    def one_rainfall_source(self):
        if (self.rainfall_mm is None) == (self.rainfall_dataset is None):
            raise ValueError("give exactly one of rainfall_mm or rainfall_dataset")
        breaks = self.depth_class_breaks_m
        if breaks != sorted(breaks) or breaks[0] <= self.min_flood_depth_m:
            raise ValueError("depth_class_breaks_m must increase and start above min_flood_depth_m")
        return self


class SimulationAccepted(BaseModel):
    simulation_id: str
    status: str
    links: dict[str, str]
