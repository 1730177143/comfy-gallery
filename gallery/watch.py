"""Index images the moment ComfyUI writes them.

A full scan costs a walk over the whole output tree, which is why the gallery
used to learn about a new render only on a rescan. ComfyUI already announces each
saved file through ``PromptServer.send_sync("executed", ...)``, so we listen there
and index just that one path: no walking, no delay.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger("comfy_gallery")

_HOOK_FLAG = "_comfy_gallery_index_hook"


def _output_paths(data: dict[str, Any]) -> list[Path]:
    """Absolute paths of the files a node just saved into the output folder."""
    output = (data or {}).get("output") or {}
    entries: list[dict[str, Any]] = []
    for key in ("images", "gifs", "videos", "audio"):
        items = output.get(key)
        if isinstance(items, list):
            entries.extend(item for item in items if isinstance(item, dict))
    if not entries:
        return []

    try:
        import folder_paths  # noqa: PLC0415 - provided by ComfyUI at runtime

        base = Path(folder_paths.get_output_directory())
    except Exception:
        return []

    paths: list[Path] = []
    for entry in entries:
        # "temp" is the preview folder — those files are not part of the library.
        if str(entry.get("type") or "output") != "output":
            continue
        filename = entry.get("filename")
        if not filename:
            continue
        subfolder = entry.get("subfolder") or ""
        paths.append(base / subfolder / filename if subfolder else base / filename)
    return paths


def install(index) -> bool:
    """Wrap the prompt server so saved files are indexed immediately.

    Returns True when the hook is in place. Failure is never fatal: without it the
    gallery simply falls back to scanning.
    """
    try:
        from server import PromptServer  # noqa: PLC0415 - provided by ComfyUI

        server = PromptServer.instance
    except Exception:
        LOGGER.debug("comfy-gallery: no prompt server yet, saving hook not installed")
        return False
    if server is None:
        return False
    if getattr(server, _HOOK_FLAG, False):
        return True

    original = getattr(server, "send_sync", None)
    if not callable(original):
        # Other builds (and test doubles) may not expose it; scanning still works.
        LOGGER.debug("comfy-gallery: prompt server has no send_sync, save hook skipped")
        return False

    def send_sync(event, data=None, sid=None):
        try:
            if event == "executed":
                paths = _output_paths(data)
                if paths:
                    index.index_files(paths)
        except Exception:  # indexing must never break a render
            LOGGER.exception("comfy-gallery: could not index a freshly saved file")
        return original(event, data, sid)

    server.send_sync = send_sync
    setattr(server, _HOOK_FLAG, True)
    LOGGER.info("comfy-gallery: new images are indexed as they are saved")
    return True


def installed() -> bool:
    """True when the save hook is already in place."""
    try:
        from server import PromptServer  # noqa: PLC0415

        return bool(getattr(PromptServer.instance, _HOOK_FLAG, False))
    except Exception:
        return False
