"""Deferred deletion: a short undo window before a file moves to the trash.

The queue is the only owner of the countdown. A viewer that opens the undo panel
holds the queue, which both suspends the purge and keeps every remaining time
frozen, so browsing the list cannot race the timer.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

LOGGER = logging.getLogger("comfy-gallery")

# A viewer sends a heartbeat while it is open; this long after the last one the
# queue resumes on its own, so a closed tab cannot pause it forever.
HOLD_SECONDS = 12.0
TICK = 1.0


class PendingQueue:
    """Files waiting out their undo window, keyed by entry id.

    Kept in memory: if ComfyUI restarts mid-window the files simply stay on disk,
    which is the harmless end of the trade-off (nothing is deleted by accident).
    """

    def __init__(self, on_expire: Callable[[str], None]) -> None:
        self._on_expire = on_expire
        self._items: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()
        self._hold_until = 0.0
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    # -- queue ---------------------------------------------------------

    def add(self, entry: dict[str, Any], seconds: int) -> dict[str, Any]:
        deadline = time.time() + max(1, int(seconds))
        record = {
            "id": entry["id"],
            "name": entry.get("name") or "",
            "folder": entry.get("folder") or "",
            "width": entry.get("width"),
            "height": entry.get("height"),
            "size": entry.get("size"),
            "deadline": deadline,
        }
        with self._lock:
            self._items[record["id"]] = record
        return dict(record)

    def cancel(self, entry_ids: list[str]) -> int:
        removed = 0
        with self._lock:
            for entry_id in entry_ids:
                if self._items.pop(entry_id, None) is not None:
                    removed += 1
        return removed

    def discard(self, entry_id: str) -> None:
        """Drop an entry without treating it as an undo (used by the purge)."""
        with self._lock:
            self._items.pop(entry_id, None)

    def ids(self) -> list[str]:
        with self._lock:
            return list(self._items)

    def list(self) -> list[dict[str, Any]]:
        now = time.time()
        with self._lock:
            return [
                {**record, "remaining": max(0.0, record["deadline"] - now)}
                for record in sorted(self._items.values(), key=lambda item: item["deadline"])
            ]

    def count(self) -> int:
        with self._lock:
            return len(self._items)

    # -- pause ---------------------------------------------------------

    def hold(self, seconds: float = HOLD_SECONDS) -> None:
        with self._lock:
            self._hold_until = max(self._hold_until, time.time() + seconds)

    def release(self) -> None:
        """Drop a hold immediately (the viewer closed its panel)."""
        with self._lock:
            self._hold_until = 0.0

    def paused(self) -> bool:
        with self._lock:
            return time.time() < self._hold_until

    # -- worker --------------------------------------------------------

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="comfy-gallery-pending", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.wait(TICK):
            try:
                self._tick()
            except Exception:  # a failing purge must not kill the worker
                LOGGER.exception("comfy-gallery pending queue tick failed")

    def _tick(self) -> None:
        now = time.time()
        with self._lock:
            if now < self._hold_until:
                # Frozen: push every deadline forward by one tick so the remaining
                # time a viewer sees stops moving.
                for record in self._items.values():
                    record["deadline"] += TICK
                return
            expired = [key for key, record in self._items.items() if record["deadline"] <= now]
            for key in expired:
                self._items.pop(key, None)

        for entry_id in expired:
            try:
                self._on_expire(entry_id)
            except Exception:
                LOGGER.exception("comfy-gallery could not delete %s", entry_id)
