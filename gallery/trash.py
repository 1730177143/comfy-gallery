"""Move files out of the gallery without destroying them.

Deleting a render is not something a browsing tool should do irreversibly, so a
delete here relocates the file into ``<root>/.gallery-trash/<same relative path>``
where it can be recovered by hand. The folder is skipped by the scanner.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from . import config

LOGGER = logging.getLogger("comfy-gallery")

TRASH_DIRNAME = ".gallery-trash"


def move_to_trash(entry_id: str) -> Path | None:
    """Relocate one entry into its root's trash folder. Returns the new path."""
    source = config.resolve_entry(entry_id)
    if source is None:
        return None
    root_id, rel = config.split_entry_id(entry_id)
    root = config.root_map().get(root_id)
    if root is None:
        return None

    destination = root.path / TRASH_DIRNAME / rel
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        # A file of the same name was already trashed; keep both.
        stem, suffix = destination.stem, destination.suffix
        counter = 1
        while destination.exists():
            destination = destination.with_name(f"{stem}-{counter}{suffix}")
            counter += 1

    shutil.move(str(source), str(destination))
    LOGGER.info("comfy-gallery moved %s to %s", source, destination)
    return destination
