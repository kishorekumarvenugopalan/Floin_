"""Build the aligned model raster stack from the stored source datasets.

All outputs share one grid: EPSG:32644, 30 m, snapped to whole metres, inside the DEM
footprint. Resampling is chosen by data type and recorded in each dataset's lineage:
  DEM (continuous)            bilinear
  land cover (categorical)    mode (majority of 10 m pixels)
  soil sand/clay (continuous) bilinear, after filling SoilGrids gaps on its native grid
  rainfall (continuous)       bilinear
  channels (vector)           rasterised (all touched)

Terrain products (static, rainfall-independent):
  conditioned DEM (channels burned) -> priority-flood filled DEM -> D8 directions,
  flood order rank, topographic flow accumulation.

Usage:  python scripts/prepare_rasters.py [--burn-depth 2.0]
"""
import argparse
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app  # noqa: F401
import numpy as np
import rasterio
import shapely
from rasterio import features
from rasterio.fill import fillnodata
from rasterio.warp import Resampling
from sqlalchemy import text

from app.core.config import MODEL_AREA_WGS84, get_settings
from app.core.errors import DataValidationError
from app.core.logging import configure_logging, get_logger
from app.db.database import connect
from app.gis.grid import ModelGrid
from app.gis.raster import read_band, reproject_to_grid, write_raster
from app.services.dataset_service import fetch_raster, register_raster, resolve
from app.services.validation_events import CHENNAI_2015
from app.simulation import MODEL_VERSION
from app.simulation.accumulation import accumulate
from app.simulation.cn import HSG_LABELS, hsg_from_texture, most_restrictive_hsg, usda_texture_class
from app.simulation.d8 import d8_receivers, priority_flood
from app.simulation.dem import burn_channels, model_domain, repair_artifacts

log = get_logger("prepare_rasters")
SOIL_FILL_DISTANCE_PX = 20   # SoilGrids gap filling search radius: 20 x 250 m = 5 km
DEM_FLOOR_M = -2.0           # land cells below this are DEM artefacts (see app/simulation/dem.py)


def lineage(inputs: dict, method: str, **parameters) -> dict:
    return {
        "inputs": {role: {"dataset": r["name"], "sha256": r["checksum_sha256"]} for role, r in inputs.items()},
        "method": method, "parameters": parameters, "model_version": MODEL_VERSION,
    }


def model_grid() -> ModelGrid:
    s = get_settings()
    return ModelGrid.from_bounds(MODEL_AREA_WGS84, s.model_crs, s.model_resolution_m)


def soil_texture_on_grid(records: dict, grid: ModelGrid, depth: str) -> tuple[np.ndarray, np.ndarray, float]:
    """Sand and clay (%) on the model grid for one depth, plus the share of filled cells."""
    out, filled_share = [], 0.0
    for prop in ("sand", "clay"):
        path = fetch_raster(records[f"{prop}_{depth}"])
        with rasterio.open(path) as src:
            data = src.read(1).astype("float32")
            profile = src.profile.copy()
        missing = data == profile["nodata"]
        filled = fillnodata(data, mask=(~missing).astype("uint8"), max_search_distance=SOIL_FILL_DISTANCE_PX)
        filled_share = max(filled_share, float(missing.mean()))
        profile.update(dtype="float32", nodata=-9999.0)
        filled[filled == profile["nodata"]] = -9999.0
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp) / "soil.tif"
            with rasterio.open(tmp_path, "w", **profile) as dst:
                dst.write(filled, 1)
            gridded = reproject_to_grid(tmp_path, grid, Resampling.bilinear)
        gridded = np.where(gridded == -9999.0, np.nan, gridded / 10.0)  # g/kg -> %
        out.append(gridded)
    return out[0], out[1], filled_share


def event_rainfall(day_records: list[dict], grid: ModelGrid) -> np.ndarray:
    """Sum daily CHIRPS rasters at native resolution, fill the coastal ocean gap, warp to the grid."""
    total, profile = None, None
    for record in day_records:
        data, profile = read_band(fetch_raster(record))
        data = data.astype("float32")
        if (data[data != profile["nodata"]] < 0).any():
            raise DataValidationError(f"{record['name']} has negative rainfall")
        total = data if total is None else np.where((total == profile["nodata"]) | (data == profile["nodata"]),
                                                    profile["nodata"], total + data)
    valid = total != profile["nodata"]
    total = fillnodata(total, mask=valid.astype("uint8"), max_search_distance=4)
    profile.update(dtype="float32")
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp) / "rain.tif"
        with rasterio.open(tmp_path, "w", **profile) as dst:
            dst.write(total, 1)
        gridded = reproject_to_grid(tmp_path, grid, Resampling.bilinear)
    return np.where(gridded == -9999.0, np.nan, gridded)


def rasterize_channels(conn, grid: ModelGrid) -> np.ndarray:
    rows = conn.execute(text("SELECT ST_AsBinary(geom) FROM floin.rivers")).scalars().all()
    if not rows:
        raise DataValidationError("floin.rivers is empty; load the river/canal layers first")
    geoms = [shapely.from_wkb(bytes(r)) for r in rows]
    return features.rasterize(((g, 1) for g in geoms), out_shape=grid.shape, transform=grid.transform,
                              fill=0, all_touched=True, dtype="uint8").astype(bool)


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser()
    parser.add_argument("--burn-depth", type=float, default=2.0, help="channel burn depth (m)")
    args = parser.parse_args()
    settings = get_settings()
    grid = model_grid()
    out_dir = settings.processed_dir
    log.info("model grid: %s", grid.as_dict())

    with connect() as conn:
        dem_src = resolve(conn, "dem_cop30_source")
        lc_src = resolve(conn, "landcover_worldcover_2021_10m")
        soil = {f"{p}_{d}": resolve(conn, f"soil_soilgrids_{p}_{d}") for p in ("sand", "clay") for d in ("0_5cm", "30_60cm")}
        rain_days = [resolve(conn, f"rainfall_chirps_{d}") for d in CHENNAI_2015["rainfall_days"]]
        channels = rasterize_channels(conn, grid)
        river_count = conn.execute(text("SELECT count(*) FROM floin.rivers")).scalar_one()

    # DEM and land cover
    dem = reproject_to_grid(fetch_raster(dem_src), grid, Resampling.bilinear)
    dem = np.where(dem == -9999.0, np.nan, dem.astype("float64"))
    landcover = reproject_to_grid(fetch_raster(lc_src), grid, Resampling.mode, dst_dtype="uint8", dst_nodata=0)
    domain = model_domain(dem, landcover)
    log.info("domain: %d land cells (%.1f km2), %d sea/outside", domain.sum(), domain.sum() * grid.cell_area_m2 / 1e6, (~domain).sum())
    dem_model, repaired = repair_artifacts(np.where(domain, dem, np.nan), domain, DEM_FLOOR_M)
    log.info("DEM artefacts below %.1f m repaired by interpolation: %d cells", DEM_FLOOR_M, repaired)

    # Soil -> hydrologic soil group (most restrictive of 0-5 and 30-60 cm)
    groups, fill_shares = [], {}
    for depth in ("0_5cm", "30_60cm"):
        sand, clay, share = soil_texture_on_grid(soil, grid, depth)
        fill_shares[depth] = share
        groups.append(hsg_from_texture(usda_texture_class(sand, clay)))
    hsg = most_restrictive_hsg(*groups)
    hsg[~domain] = 0
    missing_hsg = domain & (hsg == 0)
    if missing_hsg.any():
        raise DataValidationError(f"{missing_hsg.sum()} domain cells have no soil group after gap filling")
    hsg_counts = {HSG_LABELS[g]: int((hsg == g).sum()) for g in HSG_LABELS}
    log.info("HSG distribution (cells): %s", hsg_counts)

    rain = event_rainfall(rain_days, grid)
    rain[~domain] = np.nan
    log.info("2015 event rainfall on land: min %.1f mean %.1f max %.1f mm", np.nanmin(rain), np.nanmean(rain), np.nanmax(rain))

    # Terrain conditioning and routing network
    channels &= domain
    conditioned = burn_channels(dem_model, channels, args.burn_depth)
    t0 = time.time()
    filled, order, flood_receiver = priority_flood(conditioned, domain)
    receiver, codes = d8_receivers(filled, domain, flood_receiver, grid.resolution)
    rank = np.full(grid.shape, -1, dtype=np.int32)
    rank.ravel()[order] = np.arange(order.size, dtype=np.int32)
    topo_acc, _ = accumulate(order, receiver, domain.astype("float64"))
    topo_acc[~domain] = np.nan
    log.info("priority-flood + D8 + accumulation: %.1f s; max contributing area %.1f km2",
             time.time() - t0, np.nanmax(topo_acc) * grid.cell_area_m2 / 1e6)
    if order.size != domain.sum():
        raise DataValidationError("flood order does not cover every domain cell")

    outputs = [
        ("dem_30m", "processed/dem/dem_30m.tif", dem_model, "float32", -9999.0, "dem",
         "Model DEM, 30 m (bilinear from 1 arc-second; sea masked; artefact pits repaired)", {"source": dem_src},
         "bilinear reprojection; land cells below floor treated as voids and filled by inverse-distance interpolation",
         {"artefact_floor_m": DEM_FLOOR_M, "repaired_cells": repaired}),
        ("model_domain_30m", "processed/dem/model_domain_30m.tif", domain.astype("uint8"), "uint8", 255, "dem",
         "Model domain mask (1 = land cell in model, 0 = open sea)", {"dem": dem_src, "landcover": lc_src},
         "valid DEM and not permanent water/no-data connected to the eastern (Bay of Bengal) edge", {}),
        ("landcover_30m", "processed/landcover/landcover_30m.tif", landcover, "uint8", 0, "landcover",
         "ESA WorldCover 2021 on the model grid (majority of 10 m pixels)", {"landcover": lc_src}, "mode resampling", {}),
        ("hsg_30m", "processed/soil/hsg_30m.tif", hsg, "uint8", 0, "soil",
         "Hydrologic soil group (1=A,2=B,3=C,4=D) from SoilGrids texture", soil,
         "fill SoilGrids gaps (inverse distance, 5 km) -> bilinear -> USDA texture -> HSG (Ross et al. 2018 Table 1) "
         "-> most restrictive of 0-5 cm and 30-60 cm",
         {"gap_fill_max_distance_m": SOIL_FILL_DISTANCE_PX * 250, "native_missing_share": fill_shares, "hsg_cells": hsg_counts}),
        ("channels_30m", "processed/hydrography/channels_30m.tif", channels.astype("uint8"), "uint8", 255, "hydrography",
         "Mapped rivers and canals rasterised to the model grid", {}, f"rasterize floin.rivers ({river_count} lines), all touched", {}),
        (CHENNAI_2015["rainfall_dataset"], "processed/rainfall/chirps_2015_event_30m.tif", rain, "float32", -9999.0, "rainfall",
         "CHIRPS rainfall total 30 Nov - 2 Dec 2015 (mm) on the model grid",
         {d["name"]: d for d in rain_days}, "sum of daily rasters, coastal gap fill (4 px), bilinear", {}),
        ("terrain_dem_conditioned_30m", "processed/terrain/dem_conditioned_30m.tif", conditioned, "float32", -9999.0, "terrain",
         "DEM with mapped channels burned in", {"dem": dem_src}, "stream burning", {"burn_depth_m": args.burn_depth}),
        ("terrain_dem_filled_30m", "processed/terrain/dem_filled_30m.tif", np.where(domain, filled, np.nan), "float32", -9999.0,
         "terrain", "Depression-filled conditioned DEM", {"dem": dem_src}, "Priority-Flood (Barnes et al. 2014)", {}),
        ("terrain_flow_direction_30m", "processed/terrain/flow_direction_30m.tif", codes, "uint8", 255, "terrain",
         "D8 flow direction (ESRI codes 1..128, 0 = leaves domain)", {"dem": dem_src},
         "steepest descent on filled DEM; flats/depressions follow the priority-flood path", {}),
        ("terrain_flow_rank_30m", "processed/terrain/flow_rank_30m.tif", rank, "int32", -1, "terrain",
         "Priority-flood processing rank (downstream cells have lower rank)", {"dem": dem_src}, "Priority-Flood order", {}),
        ("terrain_flow_accumulation_30m", "processed/terrain/flow_accumulation_topographic_30m.tif", topo_acc, "float32",
         -9999.0, "terrain", "Topographic flow accumulation (number of upstream cells incl. itself)", {"dem": dem_src},
         "D8 accumulation of cell counts", {}),
    ]

    with connect() as conn:
        for name, key, array, dtype, nodata, category, title, inputs, method, params in outputs:
            path = write_raster(out_dir / Path(key).relative_to("processed"), array, grid, dtype, nodata)
            with rasterio.open(path) as src:
                grid.require_aligned(src.profile, name)
            register_raster(conn, name=name, title=title, category=category, stage="processed", path=path,
                            storage_key=key, source="FLOIN preprocessing (scripts/prepare_rasters.py)",
                            lineage={**lineage(inputs, method, **params), "grid": grid.as_dict()})
    log.info("%d processed rasters aligned, stored and registered", len(outputs))


if __name__ == "__main__":
    main()
