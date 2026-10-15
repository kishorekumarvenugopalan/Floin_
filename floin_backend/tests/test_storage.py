import pytest

from app.core.errors import StorageError
from app.services.storage_service import LocalStorage


def test_local_storage_round_trip(tmp_path):
    storage = LocalStorage(tmp_path / "store", "floin-rasters")
    storage.ensure_bucket()
    source = tmp_path / "x.bin"
    source.write_bytes(b"floin")
    storage.upload(source, "processed/test/x.bin")
    assert storage.exists("processed/test/x.bin")
    assert storage.list("processed") == ["processed/test/x.bin"]
    back = storage.download("processed/test/x.bin", tmp_path / "back.bin")
    assert back.read_bytes() == b"floin"


def test_missing_object_and_path_escape(tmp_path):
    storage = LocalStorage(tmp_path / "store", "floin-rasters")
    with pytest.raises(StorageError):
        storage.download("nope.tif", tmp_path / "n.tif")
    with pytest.raises(StorageError):
        storage.exists("../../etc/passwd")


def test_local_fetch_verifies_stored_file_in_place(tmp_path, monkeypatch):
    from app.core.errors import DataValidationError
    from app.gis.raster import sha256_file
    from app.services import dataset_service, storage_service

    storage = LocalStorage(tmp_path / "store", "floin-rasters")
    storage.ensure_bucket()
    source = tmp_path / "r.tif"
    source.write_bytes(b"raster-bytes")
    storage.upload(source, "processed/r.tif")
    monkeypatch.setattr(storage_service, "_storage", storage)
    record = {"name": "r", "storage_kind": "storage", "storage_path": "floin-rasters/processed/r.tif",
              "checksum_sha256": sha256_file(source)}
    assert dataset_service.fetch_raster(record) == storage.root / "processed/r.tif"   # no extra copy
    (storage.root / "processed/r.tif").write_bytes(b"tampered")
    with pytest.raises(DataValidationError):
        dataset_service.fetch_raster(record)
