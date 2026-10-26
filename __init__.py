"""comfy-gallery — a full-page gallery for ComfyUI output with recipe-style metadata.

ComfyUI imports this module when the folder sits in ``custom_nodes``. Loading it
registers the ``/gallery`` page and its JSON API on ComfyUI's own aiohttp server,
so the gallery is served from the same origin and port as the running instance.

This pack exposes no nodes; ``NODE_CLASS_MAPPINGS`` stays empty and only exists so
ComfyUI does not report the package as a failed import.

The gallery itself is a standalone document at ``/gallery``, loading its assets
from ``/gallery/assets/``. ``WEB_DIRECTORY`` points at a separate folder holding
the one small script that adds a Gallery button to ComfyUI's own toolbar.
"""

from __future__ import annotations

import logging

LOGGER = logging.getLogger("comfy-gallery")

WEB_DIRECTORY = "./web_ext"

# ComfyUI's loader treats an exception raised here as a broken pack. A gallery
# that cannot start must not take the whole custom-node import down with it, so
# the failure is logged with its cause and the pack degrades to "no routes".
try:
    from .gallery import api as _api

    _api.init()
except Exception:  # pragma: no cover - depends on the host ComfyUI build
    LOGGER.exception("comfy-gallery failed to register its routes")

NODE_CLASS_MAPPINGS: dict[str, type] = {}

__all__ = ["NODE_CLASS_MAPPINGS", "WEB_DIRECTORY"]
