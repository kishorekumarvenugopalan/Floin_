from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[2]

# Model area: the footprint of the project DEM (COP30 1 arc-second clip), lon/lat.
MODEL_AREA_WGS84 = (80.0498611, 12.8501389, 80.3998611, 13.3001389)


class Settings(BaseSettings):
    app_name: str = "FLOIN - Flood Intelligence & Prediction System for Chennai"
    app_env: str = "development"
    log_level: str = "INFO"

    # PostgreSQL / PostGIS (Supabase in production). Never hardcode credentials.
    database_url: str | None = None

    # Raster storage. "supabase" uses Supabase Storage; "local" uses LOCAL_STORAGE_DIR
    # with the same bucket layout. The backend never switches between them silently.
    storage_backend: Literal["supabase", "local"] = "supabase"
    local_storage_dir: Path = Path("data/storage")
    supabase_url: str | None = None
    supabase_service_role_key: str | None = None
    supabase_storage_bucket: str = "floin-rasters"

    # Model grid
    model_crs: str = "EPSG:32644"
    model_resolution_m: float = 30.0

    data_dir: Path = Path("data")
    work_dir: Path = Path("outputs")
    # Folders searched (in order) for supplied vector source files.
    vector_source_dirs: list[Path] = [Path("data/raw/vectors"), Path("../vectors")]

    model_config = SettingsConfigDict(env_file=BACKEND_ROOT / ".env", env_file_encoding="utf-8", extra="ignore")

    @field_validator("database_url")
    @classmethod
    def use_psycopg3_driver(cls, value: str | None) -> str | None:
        # SQLAlchemy maps a bare postgresql:// URL to psycopg2; this project ships psycopg 3.
        if value and value.startswith("postgresql://"):
            return "postgresql+psycopg://" + value[len("postgresql://"):]
        if value and value.startswith("postgres://"):
            return "postgresql+psycopg://" + value[len("postgres://"):]
        return value

    @field_validator("local_storage_dir", "data_dir", "work_dir")
    @classmethod
    def anchor_to_backend(cls, value: Path) -> Path:
        return value if value.is_absolute() else BACKEND_ROOT / value

    @field_validator("vector_source_dirs")
    @classmethod
    def anchor_dirs(cls, value: list[Path]) -> list[Path]:
        return [p if p.is_absolute() else (BACKEND_ROOT / p).resolve() for p in value]

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def processed_dir(self) -> Path:
        return self.data_dir / "processed"

    @property
    def model_srid(self) -> int:
        return int(self.model_crs.split(":")[1])


@lru_cache
def get_settings() -> Settings:
    return Settings()
