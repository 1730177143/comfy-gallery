"""Filesystem locations, persisted settings, and the roots the gallery scans.

Entries are addressed as ``<root_id>:<posix relative path>`` and always resolved
back through the root table. A browser-supplied id therefore cannot escape a
configured directory, which is why no route ever takes a raw absolute path.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
WEB_ROOT = PACKAGE_ROOT / "web"

# Bumped whenever the stored recipe payload changes shape. Cached parse results
# written by an older build are then recomputed instead of served half-empty.
INDEX_VERSION = 5

IMAGE_EXTS = frozenset({".png", ".jpg", ".jpeg", ".webp", ".bmp"})
VIDEO_EXTS = frozenset({".mp4", ".webm", ".mov", ".mkv", ".m4v", ".avi"})

DEFAULT_SETTINGS: dict[str, Any] = {
    # Absolute directories the user added besides ComfyUI's own output root.
    "extra_roots": [],
    # Longest edge of a cached thumbnail. Cards request a handful of sizes.
    "thumb_size": 384,
    # Items per page in the grid.
    "page_size": 60,
    # Video files carry no recipe usable by this panel; they stay off by default.
    "include_video": False,
    # "grid" (uniform square tiles) or "masonry" (natural aspect waterfall).
    "layout": "masonry",
    # Entry ids the user starred, kept here so they survive a browser switch.
    "favorites": [],
    # Tiles per row in grid layout; 0 lets the browser fit as many as it can.
    "columns": 0,
    # Where a selected item opens: side panel, modal, or the bare image.
    "detail_mode": "side",
    # Seconds a deletion can be undone; 0 deletes immediately.
    "undo_seconds": 60,
    # Let the mouse wheel step through images in the full-screen viewer.
    "wheel_navigate": False,
}

_SETTINGS_LOCK = threading.RLock()
_settings_cache: dict[str, Any] | None = None
_settings_mtime: float = -1.0
_data_dir_cache: Path | None = None


def _comfy_module():
    import folder_paths  # noqa: PLC0415 - only exists inside a running ComfyUI

    return folder_paths


def output_dir() -> Path:
    """ComfyUI's output directory, the default and only built-in root."""
    return Path(_comfy_module().get_output_directory())


def data_dir() -> Path:
    """Private storage for the index and thumbnails.

    Lives under ComfyUI's user directory so a reinstall of the pack keeps the
    cache, and so the folder is writable even when ``custom_nodes`` is not.
    """
    global _data_dir_cache
    if _data_dir_cache is not None:
        return _data_dir_cache
    try:
        base = Path(_comfy_module().get_user_directory())
    except Exception:
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "ComfyUI" / "user"
    target = base / "comfy-gallery"
    (target / "thumbs").mkdir(parents=True, exist_ok=True)
    _data_dir_cache = target
    return target


def db_path() -> Path:
    return data_dir() / "index.db"


def thumbs_dir() -> Path:
    return data_dir() / "thumbs"


def settings_path() -> Path:
    return data_dir() / "settings.json"


def settings() -> dict[str, Any]:
    """Current settings, merged over the defaults.

    Re-read when the file's mtime moves so an edit made outside the UI is picked
    up without a restart.
    """
    global _settings_cache, _settings_mtime
    path = settings_path()
    with _SETTINGS_LOCK:
        try:
            stamp = path.stat().st_mtime
        except OSError:
            stamp = -1.0
        if _settings_cache is not None and stamp == _settings_mtime:
            return dict(_settings_cache)
        merged = dict(DEFAULT_SETTINGS)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                merged.update(raw)
        except (OSError, ValueError):
            # A missing or corrupt settings file means defaults, not a hard error.
            pass
        _settings_cache = merged
        _settings_mtime = stamp
        return dict(merged)


def save_settings(patch: dict[str, Any]) -> dict[str, Any]:
    """Merge ``patch`` into the settings file and return the merged result."""
    global _settings_cache, _settings_mtime
    with _SETTINGS_LOCK:
        current = settings()
        current.update(patch)
        path = settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(current, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
        _settings_cache = current
        try:
            _settings_mtime = path.stat().st_mtime
        except OSError:
            _settings_mtime = -1.0
        return dict(current)


@dataclass(frozen=True)
class Root:
    """One scannable directory tree."""

    id: str
    label: str
    path: Path


def _extra_root_id(path: str) -> str:
    return "x" + hashlib.sha1(path.encode("utf-8")).hexdigest()[:8]


def roots() -> list[Root]:
    """The output root followed by every configured extra root that still exists."""
    result = [Root("output", "output", output_dir())]
    for raw in settings().get("extra_roots") or []:
        if not isinstance(raw, str) or not raw.strip():
            continue
        path = Path(raw)
        if not path.is_dir():
            continue
        result.append(Root(_extra_root_id(str(path)), path.name or str(path), path))
    return result


def root_map() -> dict[str, Root]:
    return {root.id: root for root in roots()}


def normalize_rel(rel: str) -> str:
    """Normalize a relative path to posix form, rejecting escapes."""
    cleaned = rel.replace("\\", "/").strip("/")
    if not cleaned:
        raise ValueError("empty path")
    parts = [part for part in cleaned.split("/") if part not in ("", ".")]
    if any(part == ".." for part in parts):
        raise ValueError("path escapes its root")
    return "/".join(parts)


def make_entry_id(root_id: str, rel: str) -> str:
    return f"{root_id}:{normalize_rel(rel)}"


def split_entry_id(entry_id: str) -> tuple[str, str]:
    root_id, sep, rel = str(entry_id).partition(":")
    if not sep or not root_id or not rel:
        raise ValueError("malformed entry id")
    return root_id, normalize_rel(rel)


def resolve_entry(entry_id: str) -> Path | None:
    """Map an entry id back to a file inside a configured root."""
    try:
        root_id, rel = split_entry_id(entry_id)
    except ValueError:
        return None
    root = root_map().get(root_id)
    if root is None:
        return None
    candidate = (root.path / rel).resolve()
    try:
        base = root.path.resolve()
    except OSError:
        return None
    if candidate != base and base not in candidate.parents:
        return None
    return candidate if candidate.is_file() else None


def is_media(name: str) -> tuple[bool, bool]:
    """Return ``(is_image, is_video)`` for a file name."""
    suffix = Path(name).suffix.lower()
    return suffix in IMAGE_EXTS, suffix in VIDEO_EXTS
