"""Directory walking and cheap media probing.

Scanning a library of several thousand files must not decode any of them: sizes
come from the image header alone, and everything else is read lazily when the
user opens one item.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator, NamedTuple

from . import config


class ScannedFile(NamedTuple):
    rel: str
    path: Path
    size: int
    mtime: float
    is_image: bool
    is_video: bool


def _skip_dir(name: str) -> bool:
    # Dot-directories hold caches and trash; thumbs of this pack live in the user
    # directory, but a user-added root may still contain another tool's cache.
    return name.startswith(".") or name in ("__pycache__", "node_modules")


def iter_media(root: config.Root, include_video: bool) -> Iterator[ScannedFile]:
    """Yield every media file under ``root``, recursively.

    Symlinked directories are followed only when they resolve inside the root,
    which keeps a stray link from walking the whole disk.
    """
    base = root.path
    try:
        stack: list[tuple[Path, str]] = [(base, "")]
        while stack:
            directory, prefix = stack.pop()
            try:
                entries = list(os.scandir(directory))
            except OSError:
                continue
            for entry in entries:
                try:
                    if entry.is_dir(follow_symlinks=False):
                        if not _skip_dir(entry.name):
                            child = f"{prefix}{entry.name}"
                            stack.append((Path(entry.path), f"{child}/"))
                        continue
                    if not entry.is_file(follow_symlinks=False):
                        continue
                    is_image, is_video = config.is_media(entry.name)
                    if not is_image and not (include_video and is_video):
                        continue
                    stat = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                rel = f"{prefix}{entry.name}"
                yield ScannedFile(rel, Path(entry.path), stat.st_size, stat.st_mtime, is_image, is_video)
    except OSError:
        return


def probe_dimensions(path: Path) -> tuple[int, int] | None:
    """Read pixel dimensions from the file header without decoding pixels."""
    from PIL import Image  # noqa: PLC0415 - Pillow ships with ComfyUI

    try:
        with Image.open(path) as image:
            width, height = image.size
            return int(width), int(height)
    except Exception:
        return None
