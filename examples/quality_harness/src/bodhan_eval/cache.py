"""Deterministic disk cache for API and model responses."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class CacheStats:
    """Statistics for cache efficiency tracking."""
    hits: int = 0
    misses: int = 0
    entries: int = 0
    total_bytes: int = 0

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return (self.hits / total) if total > 0 else 0.0


class DiskCache:
    """
    Key-value disk cache keyed by SHA-256 of request signatures.
    Guarantees deterministic, zero-cost repeated evaluation runs.
    """

    def __init__(self, cache_dir: str | Path = ".bodhan_cache"):
        self.root = Path(cache_dir).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self.stats = CacheStats()

    def _make_key(self, namespace: str, payload: str | bytes, **params: Any) -> str:
        """Create a deterministic SHA-256 cache key."""
        hasher = hashlib.sha256()
        hasher.update(namespace.encode("utf-8"))
        hasher.update(b"::")
        if isinstance(payload, bytes):
            hasher.update(payload)
        else:
            hasher.update(payload.encode("utf-8"))

        if params:
            sorted_params = json.dumps(params, sort_keys=True, ensure_ascii=True)
            hasher.update(b"::")
            hasher.update(sorted_params.encode("utf-8"))

        return hasher.hexdigest()

    def _path_for_key(self, key: str, ext: str = ".json") -> Path:
        """Partition cache into subdirectories to avoid large folder scans."""
        prefix = key[:2]
        sub = self.root / prefix
        sub.mkdir(parents=True, exist_ok=True)
        return sub / f"{key}{ext}"

    def get_json(self, namespace: str, payload: str, **params: Any) -> dict[str, Any] | None:
        """Retrieve a cached JSON dictionary."""
        key = self._make_key(namespace, payload, **params)
        path = self._path_for_key(key, ".json")
        with self._lock:
            if path.exists():
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    self.stats.hits += 1
                    return data
                except Exception as e:
                    logger.warning(f"Failed to read cache entry {key}: {e}")
            self.stats.misses += 1
            return None

    def set_json(self, namespace: str, payload: str, data: dict[str, Any], **params: Any) -> None:
        """Write a JSON dictionary into disk cache."""
        key = self._make_key(namespace, payload, **params)
        path = self._path_for_key(key, ".json")
        with self._lock:
            try:
                content = json.dumps(data, ensure_ascii=False, indent=2)
                path.write_text(content, encoding="utf-8")
                self.stats.entries += 1
                self.stats.total_bytes += len(content.encode("utf-8"))
            except Exception as e:
                logger.error(f"Failed to write cache entry {key}: {e}")

    def get_bytes(self, namespace: str, payload: str | bytes, **params: Any) -> bytes | None:
        """Retrieve cached binary blob (e.g. WAV audio)."""
        key = self._make_key(namespace, payload, **params)
        path = self._path_for_key(key, ".bin")
        with self._lock:
            if path.exists():
                try:
                    b = path.read_bytes()
                    self.stats.hits += 1
                    return b
                except Exception as e:
                    logger.warning(f"Failed to read binary cache {key}: {e}")
            self.stats.misses += 1
            return None

    def set_bytes(self, namespace: str, payload: str | bytes, data: bytes, **params: Any) -> None:
        """Store binary blob into disk cache."""
        key = self._make_key(namespace, payload, **params)
        path = self._path_for_key(key, ".bin")
        with self._lock:
            try:
                path.write_bytes(data)
                self.stats.entries += 1
                self.stats.total_bytes += len(data)
            except Exception as e:
                logger.error(f"Failed to write binary cache {key}: {e}")
