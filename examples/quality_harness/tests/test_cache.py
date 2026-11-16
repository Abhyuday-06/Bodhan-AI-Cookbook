"""Tests for deterministic SHA-256 disk cache."""

from __future__ import annotations

import tempfile
from pathlib import Path
from bodhan_eval.cache import DiskCache


def test_disk_cache_json():
    with tempfile.TemporaryDirectory() as tmp_dir:
        cache = DiskCache(tmp_dir)

        # Cache miss
        assert cache.get_json("test_model", "sample text", lang="hi") is None
        assert cache.stats.misses == 1

        # Cache put
        cache.set_json("test_model", "sample text", {"translation": "नमूना"}, lang="hi")

        # Cache hit
        cached = cache.get_json("test_model", "sample text", lang="hi")
        assert cached == {"translation": "नमूना"}
        assert cache.stats.hits == 1

        # Parameter mismatch -> miss
        assert cache.get_json("test_model", "sample text", lang="ta") is None
        assert cache.stats.misses == 2


def test_disk_cache_bytes():
    with tempfile.TemporaryDirectory() as tmp_dir:
        cache = DiskCache(tmp_dir)
        binary_data = b"\x00\x01\x02\x03\x04"

        cache.set_bytes("audio_model", "text_input", binary_data, voice="Kavya")
        retrieved = cache.get_bytes("audio_model", "text_input", voice="Kavya")
        assert retrieved == binary_data
        assert cache.stats.hits == 1
