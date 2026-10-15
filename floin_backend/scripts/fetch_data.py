"""Download the public source datasets FLOIN needs, clipped to the Chennai model area.

Every file written here is recorded in data/raw/MANIFEST.json with its source URL,
licence, retrieval time and SHA-256, so the dataset catalog can cite provenance.

Sources (all public, approved for download):
  landcover  ESA WorldCover 2021 v200, 10 m        (windowed read of a cloud-optimised GeoTIFF)
  soil       ISRIC SoilGrids 2.0 sand/clay, 250 m   (windowed read of the global VRT)
  rainfall   CHIRPS v2.0 daily, 0.05 deg, 2015-11-28 .. 2015-12-05
  osm        OpenStreetMap roads, railways and buildings via the Overpass API

Usage:
  python scripts/fetch_data.py                 # everything
  python scripts/fetch_data.py landcover soil  # selected sources
"""
import argparse
import gzip
import hashlib
import json
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app  # noqa: F401  (isolates GDAL/PROJ environment before rasterio is imported)
import httpx
import rasterio
from rasterio.io import MemoryFile
from rasterio.warp import transform_bounds
from rasterio.windows import from_bounds

from app.core.config import MODEL_AREA_WGS84, get_settings
from app.core.logging import configure_logging, get_logger

log = get_logger("fetch_data")

# Model area = footprint of the project DEM, plus a small buffer so later
# reprojection onto the UTM model grid has no empty edges.
AOI_WGS84 = MODEL_AREA_WGS84
BUFFER_DEG = 0.02

WORLDCOVER_URL = (
    "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/"
    "ESA_WorldCover_10m_2021_v200_N12E078_Map.tif"
)
SOILGRIDS_URL = "https://files.isric.org/soilgrids/latest/data/{prop}/{prop}_{depth}_mean.vrt"
SOILGRIDS_LAYERS = [(p, d) for p in ("sand", "clay") for d in ("0-5cm", "30-60cm")]
CHIRPS_URL = "https://data.chc.ucsb.edu/products/CHIRPS-2.0/global_daily/tifs/p05/{y}/chirps-v2.0.{y}.{m:02d}.{d:02d}.tif.gz"
CHIRPS_DATES = [date(2015, 11, 28) + timedelta(days=i) for i in range(8)]
OVERPASS_ENDPOINTS = ["https://overpass-api.de/api/interpreter"]

GDAL_REMOTE_OPTIONS = {
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
    "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif,.vrt",
    "GDAL_HTTP_MAX_RETRY": "4",
    "GDAL_HTTP_RETRY_DELAY": "2",
}


def buffered_aoi():
    w, s, e, n = AOI_WGS84
    return (w - BUFFER_DEG, s - BUFFER_DEG, e + BUFFER_DEG, n + BUFFER_DEG)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class Manifest:
    def __init__(self, path: Path):
        self.path = path
        self.entries = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def record(self, key, *, title, source_url, publisher, licence, files, notes=""):
        root = self.path.parent
        self.entries[key] = {
            "title": title,
            "source_url": source_url,
            "publisher": publisher,
            "licence": licence,
            "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "notes": notes,
            "files": [
                {"path": f.relative_to(root).as_posix(), "bytes": f.stat().st_size, "sha256": sha256(f)}
                for f in files
            ],
        }
        self.path.write_text(json.dumps(self.entries, indent=2), encoding="utf-8")


def windowed_copy(url: str, out_path: Path, bounds_wgs84) -> Path:
    """Read only the AOI window of a remote (cloud-optimised) raster and save it unchanged."""
    with rasterio.Env(**GDAL_REMOTE_OPTIONS):
        with rasterio.open(f"/vsicurl/{url}") as src:
            bounds = transform_bounds("EPSG:4326", src.crs, *bounds_wgs84, densify_pts=21)
            window = from_bounds(*bounds, transform=src.transform).round_offsets().round_lengths()
            data = src.read(1, window=window)
            profile = src.profile.copy()
            profile.update(
                driver="GTiff", width=data.shape[1], height=data.shape[0],
                transform=src.window_transform(window), compress="deflate",
            )
            for key in ("tiled", "blockxsize", "blockysize", "interleave"):
                profile.pop(key, None)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(out_path, "w", **profile) as dst:
        dst.write(data, 1)
    log.info("saved %s (%d x %d, %s)", out_path.name, data.shape[1], data.shape[0], profile["dtype"])
    return out_path


def fetch_landcover(raw: Path, manifest: Manifest):
    out = windowed_copy(WORLDCOVER_URL, raw / "landcover" / "esa_worldcover_2021_v200_chennai.tif", buffered_aoi())
    manifest.record(
        "esa_worldcover_2021",
        title="ESA WorldCover 10 m 2021 v200 (tile N12E078), Chennai window",
        source_url=WORLDCOVER_URL,
        publisher="European Space Agency / WorldCover consortium",
        licence="CC-BY 4.0",
        files=[out],
        notes="Windowed read of the COG; pixel values and grid are unchanged from the source tile.",
    )


def fetch_soil(raw: Path, manifest: Manifest):
    files = []
    for prop, depth in SOILGRIDS_LAYERS:
        url = SOILGRIDS_URL.format(prop=prop, depth=depth)
        files.append(windowed_copy(url, raw / "soil" / f"soilgrids_{prop}_{depth}_mean_chennai.tif", buffered_aoi()))
    manifest.record(
        "soilgrids_texture",
        title="ISRIC SoilGrids 2.0 sand and clay content (g/kg), 0-5 cm and 30-60 cm, Chennai window",
        source_url=SOILGRIDS_URL.format(prop="{sand|clay}", depth="{depth}"),
        publisher="ISRIC - World Soil Information",
        licence="CC-BY 4.0",
        files=files,
        notes="Native Interrupted Goode Homolosine grid (250 m). Model predictions, not field survey.",
    )


def fetch_rainfall(raw: Path, manifest: Manifest):
    folder = raw / "rainfall" / "chirps"
    folder.mkdir(parents=True, exist_ok=True)
    files = []
    with httpx.Client(timeout=120, follow_redirects=True) as client:
        for day in CHIRPS_DATES:
            url = CHIRPS_URL.format(y=day.year, m=day.month, d=day.day)
            gz_path = folder / Path(url).name
            if not gz_path.exists():
                response = client.get(url)
                response.raise_for_status()
                gz_path.write_bytes(response.content)
            clipped = folder / f"chirps_{day.isoformat()}_chennai.tif"
            with MemoryFile(gzip.decompress(gz_path.read_bytes())) as mem, mem.open() as src:
                window = from_bounds(*buffered_aoi(), transform=src.transform).round_offsets().round_lengths()
                data = src.read(1, window=window)
                profile = src.profile.copy()
                profile.update(driver="GTiff", width=data.shape[1], height=data.shape[0],
                               transform=src.window_transform(window), compress="deflate")
                if profile.get("crs") is None:
                    raise RuntimeError(f"{gz_path.name} has no CRS; refusing to guess")
            with rasterio.open(clipped, "w", **profile) as dst:
                dst.write(data, 1)
            files += [gz_path, clipped]
            log.info("CHIRPS %s: max %.1f mm in window", day, float(data[data > -9999].max()))
    manifest.record(
        "chirps_2015_event",
        title="CHIRPS v2.0 daily precipitation (mm/day), 2015-11-28 to 2015-12-05",
        source_url=CHIRPS_URL.format(y=2015, m=12, d=1).replace("12.01", "{MM}.{DD}"),
        publisher="UC Santa Barbara Climate Hazards Center",
        licence="CC-BY 4.0 (public domain to the extent possible)",
        files=files,
        notes="Global .tif.gz kept as downloaded; *_chennai.tif are window clips with values unchanged.",
    )


# ----------------------------------------------------------------- OpenStreetMap

OSM_LAYERS = {
    "roads": 'way["highway"~"^(motorway|trunk|primary|secondary|tertiary|unclassified|residential|living_street|service|road|motorway_link|trunk_link|primary_link|secondary_link|tertiary_link)$"]',
    "railways": 'way["railway"~"^(rail|subway|light_rail|monorail|narrow_gauge)$"]',
    "buildings": 'way["building"];relation["building"]["type"="multipolygon"]',
}
OSM_TILES = {"roads": 3, "railways": 1, "buildings": 4}   # initial grid; busy tiles are split adaptively
OSM_MIN_TILE_DEG = 0.006                                  # stop splitting below ~650 m


class OverpassBusy(Exception):
    pass


def overpass(query: str, client: httpx.Client) -> dict:
    """Run one Overpass query. Raises OverpassBusy when the server refuses the size of the
    query (504), after waiting out rate limits (429) and transient errors."""
    for attempt in range(8):
        endpoint = OVERPASS_ENDPOINTS[attempt % len(OVERPASS_ENDPOINTS)]
        try:
            response = client.post(endpoint, data={"data": query})
        except httpx.HTTPError as exc:
            log.warning("Overpass network error (%s); retrying in 20s", exc)
            time.sleep(20)
            continue
        if response.status_code == 504:
            raise OverpassBusy(endpoint)
        if response.status_code in (429, 502, 503):
            log.warning("Overpass %s from %s; waiting 30s", response.status_code, endpoint)
            time.sleep(30)
            continue
        response.raise_for_status()
        payload = response.json()
        if "remark" in payload and ("runtime error" in payload["remark"] or "timed out" in payload["remark"]):
            raise OverpassBusy(payload["remark"])
        return payload
    raise RuntimeError("Overpass unavailable after repeated retries")


def osm_tiles(n: int):
    w, s, e, nn = AOI_WGS84
    dx, dy = (e - w) / n, (nn - s) / n
    for i in range(n):
        for j in range(n):
            yield (s + j * dy, w + i * dx, s + (j + 1) * dy, w + (i + 1) * dx)  # Overpass order: S,W,N,E


def fetch_tile(layer: str, bbox: tuple, client: httpx.Client, tiles_dir: Path) -> list[dict]:
    """Fetch one bbox (cached). When the server is overloaded (504) wait and retry the same
    tile with growing pauses; split it into quarters only after repeated refusals."""
    s, w, n, e = bbox
    key = f"{s:.5f}_{w:.5f}_{n:.5f}_{e:.5f}"
    tile_file = tiles_dir / f"{layer}_{key}.json.gz"
    if tile_file.exists():
        with gzip.open(tile_file, "rt", encoding="utf-8") as f:
            return [json.load(f)]
    selectors = "".join(f"{sel}({s:.6f},{w:.6f},{n:.6f},{e:.6f});" for sel in OSM_LAYERS[layer].split(";"))
    query = f"[out:json][timeout:120];({selectors});out geom tags;"
    waits = [60, 120, 180, 300, 300, 300, 600, 600]
    for attempt, wait in enumerate(waits, start=1):
        try:
            payload = overpass(query, client)
            break
        except OverpassBusy:
            if attempt >= 3 and (n - s) > OSM_MIN_TILE_DEG * 4:
                log.info("OSM %s %s refused %d times; splitting", layer, key, attempt)
                ms, mw = (s + n) / 2, (w + e) / 2
                parts = []
                for sub in ((s, w, ms, mw), (s, mw, ms, e), (ms, w, n, mw), (ms, mw, n, e)):
                    parts += fetch_tile(layer, sub, client, tiles_dir)
                return parts
            log.warning("OSM %s %s: server busy (attempt %d); waiting %ds", layer, key, attempt, wait)
            time.sleep(wait)
    else:
        raise RuntimeError(f"Overpass still refusing tile {bbox} after {len(waits)} attempts")
    with gzip.open(tile_file, "wt", encoding="utf-8") as f:
        json.dump(payload, f)
    log.info("OSM %s %s: %d elements", layer, key, len(payload.get("elements", [])))
    time.sleep(5)
    return [payload]


def fetch_osm(raw: Path, manifest: Manifest, layers=("roads", "railways", "buildings")):
    folder = raw / "osm"
    tiles_dir = folder / "tiles"
    tiles_dir.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=200, headers={"User-Agent": "FLOIN research backend (flood model)"}) as client:
        for layer in layers:
            elements, osm_base, n_tiles = {}, None, 0
            for bbox in osm_tiles(OSM_TILES[layer]):
                for payload in fetch_tile(layer, bbox, client, tiles_dir):
                    n_tiles += 1
                    osm_base = payload.get("osm3s", {}).get("timestamp_osm_base", osm_base)
                    for el in payload.get("elements", []):
                        elements[(el["type"], el["id"])] = el
            log.info("OSM %s: %d unique elements from %d tiles", layer, len(elements), n_tiles)
            out = folder / f"osm_{layer}_chennai.json.gz"
            with gzip.open(out, "wt", encoding="utf-8") as f:
                json.dump({"osm_base": osm_base, "bbox_wgs84": AOI_WGS84, "elements": list(elements.values())}, f)
            manifest.record(
                f"osm_{layer}",
                title=f"OpenStreetMap {layer} for the Chennai model area (Overpass extract)",
                source_url=OVERPASS_ENDPOINTS[-1],
                publisher="OpenStreetMap contributors",
                licence="ODbL 1.0",
                files=[out],
                notes=f"Overpass selector: {OSM_LAYERS[layer]}; OSM data timestamp {osm_base}; "
                      f"{n_tiles} adaptive tiles merged, duplicates removed by element id.",
            )


def main():
    configure_logging()
    parser = argparse.ArgumentParser()
    parser.add_argument("sources", nargs="*", default=["landcover", "soil", "rainfall", "osm"])
    args = parser.parse_args()
    raw = get_settings().raw_dir
    manifest = Manifest(raw / "MANIFEST.json")
    handlers = {"landcover": fetch_landcover, "soil": fetch_soil, "rainfall": fetch_rainfall, "osm": fetch_osm}
    for name in args.sources:
        log.info("fetching %s", name)
        handlers[name](raw, manifest)
    log.info("manifest: %s", manifest.path)


if __name__ == "__main__":
    main()
