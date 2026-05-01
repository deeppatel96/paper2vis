"""
Storage abstraction.

LocalStorage writes to disk and serves files via /api/files/*.
Swap for S3Storage (same interface) to move to cloud.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class StorageBackend(Protocol):
    def write(self, key: str, data: bytes) -> None: ...
    def read(self, key: str) -> bytes: ...
    def url(self, key: str) -> str: ...
    def exists(self, key: str) -> bool: ...
    def path(self, key: str) -> Path: ...


class LocalStorage:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def write(self, key: str, data: bytes) -> None:
        dest = self.root / key
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)

    def read(self, key: str) -> bytes:
        return (self.root / key).read_bytes()

    def url(self, key: str) -> str:
        return f"/api/files/{key}"

    def exists(self, key: str) -> bool:
        return (self.root / key).exists()

    def path(self, key: str) -> Path:
        return self.root / key
