"""Raster/file storage.

Two backends with the same bucket layout (source/, processed/, simulations/):
  supabase  Supabase Storage REST API, authenticated with the service-role key (server only)
  local     a directory on disk, for development without Supabase credentials

The backend is chosen by STORAGE_BACKEND. A failure is raised as StorageError; the code
never falls back from one backend to the other.
"""
import shutil
from pathlib import Path
from typing import Protocol
from urllib.parse import quote

import httpx

from app.core.config import get_settings
from app.core.errors import ConfigurationError, StorageError
from app.core.logging import get_logger

log = get_logger("storage")


class Storage(Protocol):
    kind: str
    bucket: str

    def ensure_bucket(self) -> None: ...
    def upload(self, local_path: Path, key: str, content_type: str) -> None: ...
    def download(self, key: str, local_path: Path) -> Path: ...
    def exists(self, key: str) -> bool: ...
    def list(self, prefix: str) -> list[str]: ...


class LocalStorage:
    kind = "local"

    def __init__(self, root: Path, bucket: str):
        self.bucket = bucket
        self.root = Path(root) / bucket

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if self.root.resolve() not in path.parents:
            raise StorageError(f"Storage key escapes bucket: {key}")
        return path

    def ensure_bucket(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def upload(self, local_path: Path, key: str, content_type: str = "application/octet-stream") -> None:
        target = self._path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        if Path(local_path).resolve() != target:
            shutil.copyfile(local_path, target)

    def download(self, key: str, local_path: Path) -> Path:
        source = self._path(key)
        if not source.exists():
            raise StorageError(f"Storage object not found: {self.bucket}/{key}")
        local_path = Path(local_path)
        local_path.parent.mkdir(parents=True, exist_ok=True)
        if source != local_path.resolve():
            shutil.copyfile(source, local_path)
        return local_path

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def list(self, prefix: str = "") -> list[str]:
        base = self._path(prefix) if prefix else self.root
        if not base.exists():
            return []
        return sorted(p.relative_to(self.root).as_posix() for p in base.rglob("*") if p.is_file())


class SupabaseStorage:
    kind = "supabase"

    def __init__(self, url: str, service_key: str, bucket: str):
        self.bucket = bucket
        self.base = url.rstrip("/") + "/storage/v1"
        self.client = httpx.Client(
            timeout=httpx.Timeout(300, connect=20),
            headers={"Authorization": f"Bearer {service_key}", "apikey": service_key},
        )

    def _check(self, response: httpx.Response, action: str) -> httpx.Response:
        if response.status_code >= 400:
            raise StorageError(f"Supabase Storage {action} failed: HTTP {response.status_code} {response.text[:200]}")
        return response

    def ensure_bucket(self) -> None:
        response = self.client.get(f"{self.base}/bucket/{self.bucket}")
        if response.status_code == 200:
            return
        created = self.client.post(f"{self.base}/bucket", json={"id": self.bucket, "name": self.bucket, "public": False})
        self._check(created, f"create bucket {self.bucket}")
        log.info("created private storage bucket %s", self.bucket)

    def upload(self, local_path: Path, key: str, content_type: str = "application/octet-stream") -> None:
        with Path(local_path).open("rb") as f:
            response = self.client.post(
                f"{self.base}/object/{self.bucket}/{quote(key)}",
                content=f.read(),
                headers={"Content-Type": content_type, "x-upsert": "true"},
            )
        self._check(response, f"upload {key}")

    def download(self, key: str, local_path: Path) -> Path:
        response = self._check(self.client.get(f"{self.base}/object/{self.bucket}/{quote(key)}"), f"download {key}")
        local_path = Path(local_path)
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(response.content)
        return local_path

    def exists(self, key: str) -> bool:
        folder, _, name = key.rpartition("/")
        return name in self._list_folder(folder, search=name)

    def _list_folder(self, folder: str, search: str = "") -> list[str]:
        response = self.client.post(
            f"{self.base}/object/list/{self.bucket}",
            json={"prefix": folder, "search": search, "limit": 1000, "offset": 0},
        )
        return [item["name"] for item in self._check(response, f"list {folder}").json()]

    def list(self, prefix: str = "") -> list[str]:
        keys, pending = [], [prefix.rstrip("/")]
        while pending:
            folder = pending.pop()
            response = self.client.post(
                f"{self.base}/object/list/{self.bucket}",
                json={"prefix": folder, "limit": 1000, "offset": 0},
            )
            for item in self._check(response, f"list {folder}").json():
                key = f"{folder}/{item['name']}" if folder else item["name"]
                (pending if item.get("id") is None else keys).append(key)
        return sorted(keys)


_storage: Storage | None = None


def get_storage() -> Storage:
    global _storage
    if _storage is None:
        s = get_settings()
        if s.storage_backend == "supabase":
            if not s.supabase_url or not s.supabase_service_role_key:
                raise ConfigurationError("STORAGE_BACKEND=supabase needs SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY")
            _storage = SupabaseStorage(s.supabase_url, s.supabase_service_role_key, s.supabase_storage_bucket)
        else:
            _storage = LocalStorage(s.local_storage_dir, s.supabase_storage_bucket)
    return _storage
