"""Validate source rasters, upload them to storage and register them in floin.datasets.

For each raster: open -> CRS present -> resolution/extent -> NoData declared -> value range
-> covers the Chennai model area -> upload (storage source/...) -> download again, compare
SHA-256 and reopen -> catalog row.

Usage:  python scripts/load_rasters.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app  # noqa: F401
import numpy as np
import rasterio
from rasterio.warp import transform_bounds

from app.core.config import MODEL_AREA_WGS84, get_settings
from app.core.errors import DataValidationError
from app.core.logging import configure_logging, get_logger
from app.db.database import connect
from app.services.dataset_service import register_raster

log = get_logger("load_rasters")

CHIRPS_NODATA = -9999.0  # CHIRPS v2.0 documented missing value (ocean)


def manifest_entry(key: str) -> dict:
    manifest = json.loads((get_settings().raw_dir / "MANIFEST.json").read_text(encoding="utf-8"))
    return manifest[key]


def covers_model_area(path: Path, tolerance_deg: float = 0.001) -> None:
    with rasterio.open(path) as src:
        w, s, e, n = transform_bounds(src.crs, "EPSG:4326", *src.bounds, densify_pts=21)
    mw, ms, me, mn = MODEL_AREA_WGS84
    if w > mw + tolerance_deg or s > ms + tolerance_deg or e < me - tolerance_deg or n < mn - tolerance_deg:
        raise DataValidationError(f"{path.name} does not cover the model area: {(w, s, e, n)} vs {MODEL_AREA_WGS84}")


def check_values(path: Path, low: float, high: float, allowed: set | None = None) -> None:
    with rasterio.open(path) as src:
        if src.crs is None:
            raise DataValidationError(f"{path.name} has no CRS")
        data = src.read(1, masked=True).compressed()
    if data.size == 0:
        raise DataValidationError(f"{path.name} has no valid cells")
    if allowed is not None:
        unexpected = set(np.unique(data).tolist()) - allowed
        if unexpected:
            raise DataValidationError(f"{path.name} has unexpected class values {sorted(unexpected)}")
    elif data.min() < low or data.max() > high:
        raise DataValidationError(f"{path.name} values {data.min()}..{data.max()} outside {low}..{high}")


def declare_nodata(path: Path, value: float) -> None:
    with rasterio.open(path, "r+") as dst:
        if dst.nodata is None:
            dst.nodata = value
            log.info("%s: declared NoData = %s", path.name, value)


def main() -> None:
    configure_logging()
    raw = get_settings().raw_dir
    jobs = []

    dem = raw / "rasters" / "COP30_SRTM_TNM_N13E080_30m.tif"
    check_values(dem, -100, 500)
    covers_model_area(dem)
    jobs.append(dict(
        name="dem_cop30_source", title="Copernicus GLO-30 DEM (1 arc-second), Chennai clip", category="dem",
        path=dem, storage_key="source/dem/cop30_n13e080_chennai.tif",
        source="Supplied project file (Copernicus DEM GLO-30, ESA/Airbus)", licence="Copernicus DEM licence",
        source_url="https://copernicus-dem-30m.s3.amazonaws.com/",
        quality_notes="Digital SURFACE model: includes buildings and trees. No NoData declared; sea cells are 0 or "
                      "negative (min -65.5 m artefacts). The model masks the sea using land cover.",
    ))

    wc = manifest_entry("esa_worldcover_2021")
    wc_path = raw / wc["files"][0]["path"]
    check_values(wc_path, 0, 100, allowed={10, 20, 30, 40, 50, 60, 70, 80, 90, 95, 100})
    covers_model_area(wc_path)
    jobs.append(dict(
        name="landcover_worldcover_2021_10m", title=wc["title"], category="landcover", path=wc_path,
        storage_key="source/landcover/esa_worldcover_2021_v200_chennai.tif", source=wc["publisher"],
        source_url=wc["source_url"], licence=wc["licence"], lineage={"manifest": wc},
    ))

    soil = manifest_entry("soilgrids_texture")
    for f in soil["files"]:
        p = raw / f["path"]
        check_values(p, 0, 1000)
        covers_model_area(p)
        prop, depth = p.stem.split("_")[1:3]
        jobs.append(dict(
            name=f"soil_soilgrids_{prop}_{depth.replace('-', '_')}", title=f"SoilGrids 2.0 {prop} content (g/kg), {depth}",
            category="soil", path=p, storage_key=f"source/soil/{p.name}", source=soil["publisher"],
            source_url=soil["source_url"], licence=soil["licence"], lineage={"manifest_key": "soilgrids_texture"},
            quality_notes="Model predictions at 250 m; SoilGrids leaves most built-up and water pixels empty.",
        ))

    chirps = manifest_entry("chirps_2015_event")
    for f in chirps["files"]:
        p = raw / f["path"]
        if not p.name.endswith("_chennai.tif"):
            continue
        declare_nodata(p, CHIRPS_NODATA)
        check_values(p, 0, 1000)
        covers_model_area(p)
        day = p.stem.split("_")[1]
        jobs.append(dict(
            name=f"rainfall_chirps_{day.replace('-', '')}", title=f"CHIRPS v2.0 daily precipitation {day} (mm)",
            category="rainfall", path=p, storage_key=f"source/rainfall/chirps/{p.name}", source=chirps["publisher"],
            source_url=chirps["source_url"], licence=chirps["licence"], lineage={"manifest_key": "chirps_2015_event", "date": day},
            quality_notes="0.05 deg (~5.5 km) satellite-gauge blend; known to underestimate extreme coastal rainfall.",
        ))

    with connect() as conn:
        for job in jobs:
            register_raster(conn, stage="source", **job)
    log.info("%d source rasters validated, stored and registered", len(jobs))


if __name__ == "__main__":
    main()
