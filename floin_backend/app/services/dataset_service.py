"""Dataset catalog operations: register rasters in storage and resolve them for the model."""
import tempfile
from pathlib import Path

import rasterio
from sqlalchemy.engine import Connection

from app.core.config import get_settings
from app.core.errors import DataValidationError, DatasetMissingError, StorageError
from app.core.logging import get_logger
from app.db.repositories import get_dataset, upsert_dataset
from app.gis.raster import raster_metadata, sha256_file
from app.services.storage_service import get_storage

log = get_logger("datasets")

USABLE = ("available", "limited")


def register_raster(conn: Connection, *, name: str, title: str, category: str, stage: str, path: Path,
                    storage_key: str, source: str, description: str | None = None,
                    source_url: str | None = None, licence: str | None = None, status: str = "available",
                    quality_notes: str | None = None, lineage: dict | None = None) -> dict:
    """Upload a GeoTIFF, prove it can be retrieved and opened, then record it in the catalog."""
    meta = raster_metadata(path)
    storage = get_storage()
    storage.ensure_bucket()
    storage.upload(path, storage_key, "image/tiff")
    verify_retrieval(storage_key, meta["checksum_sha256"])
    record = {
        "name": name, "title": title, "dataset_type": "raster", "category": category, "stage": stage,
        "description": description, "source": source, "source_url": source_url, "licence": licence,
        "format": "GeoTIFF", "storage_kind": "storage", "storage_path": f"{storage.bucket}/{storage_key}",
        "version": meta["checksum_sha256"][:12], "status": status, "quality_notes": quality_notes,
        "lineage": {**(lineage or {}), "storage_backend": storage.kind, "valid_fraction": meta["valid_fraction"]},
        **{k: meta[k] for k in ("crs", "srid", "resolution_x", "resolution_y", "width", "height", "min_x", "min_y",
                                "max_x", "max_y", "dtype", "nodata_value", "min_value", "max_value",
                                "checksum_sha256", "size_bytes", "footprint_wgs84")},
    }
    record["id"] = upsert_dataset(conn, record)
    log.info("registered %-34s %s (%s, %dx%d)", name, record["storage_path"], meta["crs"], meta["width"], meta["height"])
    return record


def verify_retrieval(storage_key: str, checksum: str) -> None:
    """Download an object to a temporary file, compare SHA-256 and open it with rasterio."""
    storage = get_storage()
    with tempfile.TemporaryDirectory() as tmp:
        local = storage.download(storage_key, Path(tmp) / Path(storage_key).name)
        if sha256_file(local) != checksum:
            raise StorageError(f"checksum mismatch after retrieving {storage_key}")
        with rasterio.open(local) as src:
            src.read(1, window=((0, min(8, src.height)), (0, min(8, src.width))))


def resolve(conn: Connection, name: str) -> dict:
    """Catalog record for a dataset the model needs; raises if missing or unusable."""
    record = get_dataset(conn, name)
    if record is None:
        raise DatasetMissingError(f"Required dataset '{name}' is not registered. Run the ingestion scripts.")
    if record["status"] not in USABLE:
        raise DatasetMissingError(f"Dataset '{name}' has status {record['status']}: {record['quality_notes']}")
    return record


def fetch_raster(record: dict) -> Path:
    """Local, checksum-verified copy of a stored raster (cached by checksum)."""
    if record["storage_kind"] != "storage" or not record["storage_path"]:
        raise DatasetMissingError(f"Dataset '{record['name']}' is not a stored raster")
    storage = get_storage()
    bucket, _, key = record["storage_path"].partition("/")
    if bucket != storage.bucket:
        raise StorageError(f"{record['name']} is in bucket {bucket}, configured bucket is {storage.bucket}")
    if storage.kind == "local":
        # The stored object is already a local file: verify it in place instead of copying it.
        stored = storage.root / key
        if not stored.is_file():
            raise DatasetMissingError(f"{record['name']}: stored file {record['storage_path']} is missing")
        if sha256_file(stored) != record["checksum_sha256"]:
            raise DataValidationError(f"{record['name']}: stored file does not match the catalog checksum")
        return stored
    cache = get_settings().data_dir / "cache" / f"{record['checksum_sha256'][:16]}_{Path(key).name}"
    if not cache.exists() or sha256_file(cache) != record["checksum_sha256"]:
        storage.download(key, cache)
        if sha256_file(cache) != record["checksum_sha256"]:
            cache.unlink(missing_ok=True)
            raise DataValidationError(f"{record['name']}: retrieved file does not match the catalog checksum")
    return cache
