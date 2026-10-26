"""On-demand thumbnail cache.

Cards are small and the originals are several thousand pixels wide, so the grid
must never receive a full-size file. Thumbnails are keyed by file identity plus
mtime, which invalidates them automatically when a file is regenerated.
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
from pathlib import Path

from . import config

LOGGER = logging.getLogger("comfy-gallery")

_BUDGET_BYTES = 2 * 1024 ** 3

_path_locks: dict[str, threading.Lock] = {}
_path_locks_guard = threading.Lock()
_counter = {"value": 0}


def thumb_path(entry_id: str, mtime: float, size: int) -> Path:
    digest = hashlib.sha1(f"{entry_id}|{mtime:.3f}|{size}".encode("utf-8")).hexdigest()
    return config.thumbs_dir() / f"{digest}.jpg"


def _lock_for(name: str) -> threading.Lock:
    with _path_locks_guard:
        return _path_locks.setdefault(name, threading.Lock())


def ensure_thumb(source: Path, entry_id: str, mtime: float, size: int,
                 longest_edge: int = 384) -> Path | None:
    """Return a cached JPEG thumbnail, generating it on first use."""
    target = thumb_path(entry_id, mtime, size)
    if target.is_file() and target.stat().st_size > 0:
        return target

    with _lock_for(target.name):
        if target.is_file() and target.stat().st_size > 0:
            return target
        try:
            _render(source, target, longest_edge)
        except Exception as error:
            LOGGER.warning("thumbnail failed for %s: %s", source, error)
            return None

    _counter["value"] += 1
    if _counter["value"] % 200 == 0:
        _enforce_budget()
    return target


def _render(source: Path, target: Path, longest_edge: int) -> None:
    from PIL import Image  # noqa: PLC0415 - Pillow ships with ComfyUI

    edge = max(64, min(1024, int(longest_edge)))
    with Image.open(source) as image:
        # draft() lets libjpeg decode a reduced JPEG, which matters for the large
        # files a 4x upscale produces.
        try:
            image.draft("RGB", (edge * 2, edge * 2))
        except Exception:
            pass
        frame = image.convert("RGB") if image.mode not in ("RGB", "L") else image.copy()
    frame.thumbnail((edge, edge), Image.LANCZOS)
    temporary = target.with_suffix(".tmp")
    frame.save(temporary, "JPEG", quality=82, optimize=True, progressive=True)
    os.replace(temporary, target)


def _enforce_budget() -> None:
    """Drop the oldest thumbnails once the cache grows past its budget."""
    directory = config.thumbs_dir()
    try:
        entries = [(item.stat().st_mtime, item.stat().st_size, item)
                   for item in directory.glob("*.jpg")]
    except OSError:
        return
    total = sum(size for _, size, _ in entries)
    if total <= _BUDGET_BYTES:
        return
    entries.sort()
    removed = 0
    for _mtime, size, item in entries:
        try:
            item.unlink()
            removed += 1
            total -= size
        except OSError:
            continue
        if total <= _BUDGET_BYTES * 0.8:
            break
    LOGGER.info("thumbnail cache trimmed: %s files removed", removed)
