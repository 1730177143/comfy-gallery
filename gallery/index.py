"""SQLite index over the configured roots, built by an incremental scan.

Scanning thousands of PNGs means reading each file's metadata chunk once. The
result is cached so the grid, the search box and the detail panel never touch
the disk again until a file or the pack version changes.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from . import basemodel, config, media, metadata
from .parse import build_recipe, build_search_blob

LOGGER = logging.getLogger("comfy-gallery")

_SORT_ORDERS = {
    "newest": "mtime DESC",
    "oldest": "mtime ASC",
    "name": "name COLLATE NOCASE ASC",
    "largest": "size DESC",
    "smallest": "size ASC",
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    id          TEXT PRIMARY KEY,
    root_id     TEXT NOT NULL,
    rel         TEXT NOT NULL,
    name        TEXT NOT NULL,
    folder      TEXT NOT NULL,
    ext         TEXT NOT NULL,
    size        INTEGER NOT NULL,
    mtime       REAL NOT NULL,
    width       INTEGER,
    height      INTEGER,
    kind        TEXT NOT NULL,
    source      TEXT NOT NULL,
    base_model  TEXT NOT NULL DEFAULT '',
    base_auto   TEXT NOT NULL DEFAULT '',
    snippet     TEXT NOT NULL DEFAULT '',
    base_source TEXT NOT NULL DEFAULT 'auto',
    has_workflow INTEGER NOT NULL DEFAULT 0,
    version     INTEGER NOT NULL,
    search_text TEXT NOT NULL,
    recipe      TEXT
);
CREATE INDEX IF NOT EXISTS idx_files_mtime  ON files(mtime DESC);
CREATE INDEX IF NOT EXISTS idx_files_folder ON files(folder);
CREATE INDEX IF NOT EXISTS idx_files_root   ON files(root_id);
CREATE INDEX IF NOT EXISTS idx_files_base   ON files(base_model);
"""

_BATCH_SIZE = 40


class GalleryIndex:
    """Owns the database and the background scan."""

    def __init__(self) -> None:
        self._db: sqlite3.Connection | None = None
        self._lock = threading.RLock()
        self._scan_thread: threading.Thread | None = None
        # A finished scan must not be restarted by the next API call; only an
        # explicit rescan or a failed scan is allowed to run again.
        self._scanned_once = False
        self._state: dict[str, Any] = {
            "running": False,
            "indexed": 0,
            "total": 0,
            "scanned": 0,
            "started_at": None,
            "finished_at": None,
            "error": None,
        }

    # -- database ------------------------------------------------------

    def db(self) -> sqlite3.Connection:
        with self._lock:
            if self._db is not None:
                return self._db
            path = config.db_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(str(path), check_same_thread=False, timeout=30)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=NORMAL")
            # Migration has to run first: the schema below creates an index on a
            # column an older table lacks, and that statement would abort the
            # whole script before the table could be replaced.
            self._migrate(connection)
            connection.executescript(_SCHEMA)
            connection.commit()
            self._db = connection
            return connection

    @staticmethod
    def _migrate(connection: sqlite3.Connection) -> None:
        """Drop an index written by a build with a different column set.

        The table is a cache over files on disk, so rebuilding is always safe and
        cheaper than tracking per-column migrations.
        """
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(files)")}
        if not columns:
            return
        required = {"id", "base_model", "base_auto", "base_source", "snippet", "has_workflow",
                "recipe", "search_text"}
        if not required.issubset(columns):
            LOGGER.info("comfy-gallery index schema changed; rebuilding")
            connection.execute("DROP TABLE IF EXISTS files")
            connection.commit()

    def close(self) -> None:
        with self._lock:
            if self._db is not None:
                self._db.close()
                self._db = None

    # -- scan ----------------------------------------------------------

    @property
    def state(self) -> dict[str, Any]:
        return dict(self._state)

    def ensure_started(self, force: bool = False) -> None:
        """Start a background scan unless one is already running."""
        with self._lock:
            if self._scan_thread is not None and self._scan_thread.is_alive():
                return
            if not force and self._scanned_once:
                return
            self._scan_thread = threading.Thread(
                target=self._scan_safe, kwargs={"force": force}, name="comfy-gallery-scan", daemon=True
            )
            self._scan_thread.start()

    def _scan_safe(self, force: bool = False) -> None:
        try:
            self._scan(force=force)
        except Exception as error:  # a failed scan must not kill the server
            LOGGER.exception("comfy-gallery scan failed")
            self._state.update(running=False, error=f"{type(error).__name__}: {error}",
                               finished_at=time.time())

    def _scan(self, force: bool = False) -> None:
        connection = self.db()
        started = time.time()
        self._state.update(running=True, indexed=0, scanned=0, started_at=started,
                           finished_at=None, error=None)

        include_video = bool(config.settings().get("include_video"))
        roots = config.roots()
        with self._lock:
            existing = {
                row["id"]: (row["size"], row["mtime"], row["version"])
                for row in connection.execute("SELECT id, size, mtime, version FROM files")
            }

        seen: set[str] = set()
        batch: list[tuple[Any, ...]] = []
        for root in roots:
            for scanned in media.iter_media(root, include_video):
                entry_id = config.make_entry_id(root.id, scanned.rel)
                seen.add(entry_id)
                self._state["scanned"] += 1
                previous = existing.get(entry_id)
                if (
                    previous is not None
                    and not force
                    and previous[0] == scanned.size
                    and abs(previous[1] - scanned.mtime) < 0.001
                    and previous[2] == config.INDEX_VERSION
                ):
                    continue
                batch.append(self._build_row(entry_id, root, scanned))
                if len(batch) >= _BATCH_SIZE:
                    self._write(connection, batch)
                    batch = []
        if batch:
            self._write(connection, batch)

        stale = [entry_id for entry_id in existing if entry_id not in seen]
        if stale:
            with self._lock:
                connection.executemany("DELETE FROM files WHERE id = ?", [(item,) for item in stale])
                connection.commit()

        total = self._count_all()
        self._scanned_once = True
        self._state.update(running=False, indexed=total, total=total, finished_at=time.time())

    def _build_row(self, entry_id: str, root: config.Root, scanned: media.ScannedFile) -> tuple[Any, ...]:
        payload: dict[str, Any] = {}
        if scanned.is_image:
            payload = metadata.read_payloads(scanned.path)
        recipe = build_recipe(payload) if payload else _video_recipe()
        dimensions = payload.get("size") or (0, 0)
        name = scanned.rel.rsplit("/", 1)[-1]
        folder = scanned.rel.rsplit("/", 1)[0] if "/" in scanned.rel else ""
        source = recipe.get("source") or "none"
        base_key = basemodel.key_of(recipe)
        return (
            entry_id,
            root.id,
            scanned.rel,
            name,
            folder,
            Path(name).suffix.lower().lstrip("."),
            scanned.size,
            scanned.mtime,
            int(dimensions[0] or 0),
            int(dimensions[1] or 0),
            "image" if scanned.is_image else "video",
            source,
            base_key,
            base_key,
            basemodel.snippet_of(recipe),
            "auto",
            1 if payload.get("workflow") else 0,
            config.INDEX_VERSION,
            build_search_blob(recipe, name, folder),
            json.dumps(recipe, ensure_ascii=False, separators=(",", ":")),
        )

    def _write(self, connection: sqlite3.Connection, rows: list[tuple[Any, ...]]) -> None:
        with self._lock:
            connection.executemany(
                """
                INSERT INTO files (id, root_id, rel, name, folder, ext, size, mtime, width, height,
                                   kind, source, base_model, base_auto, snippet, base_source,
                                   has_workflow, version, search_text, recipe)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    root_id=excluded.root_id, rel=excluded.rel, name=excluded.name,
                    folder=excluded.folder, ext=excluded.ext, size=excluded.size,
                    mtime=excluded.mtime, width=excluded.width, height=excluded.height,
                    kind=excluded.kind, source=excluded.source,
                    base_auto=excluded.base_auto,
                    base_model=CASE WHEN files.base_source = 'manual'
                                    THEN files.base_model ELSE excluded.base_model END,
                    snippet=excluded.snippet, has_workflow=excluded.has_workflow,
                    version=excluded.version, search_text=excluded.search_text,
                    recipe=excluded.recipe
                """,
                rows,
            )
            connection.commit()
        self._state["indexed"] += len(rows)

    def _count_all(self) -> int:
        with self._lock:
            row = self.db().execute("SELECT COUNT(*) AS count FROM files").fetchone()
        return int(row["count"] if row else 0)

    # -- queries -------------------------------------------------------

    def query(self, folder: str = "", text: str = "", sort: str = "newest", root_id: str = "",
              offset: int = 0, limit: int = 60, base: str = "",
              only_ids: list[str] | None = None) -> dict[str, Any]:
        clauses: list[str] = []
        params: list[Any] = []
        if only_ids is not None:
            if not only_ids:
                return {"total": 0, "items": []}
            placeholders = ",".join("?" for _ in only_ids)
            clauses.append(f"id IN ({placeholders})")
            params.extend(only_ids)
        if root_id:
            clauses.append("root_id = ?")
            params.append(root_id)
        folder = folder.strip("/")
        if folder:
            clauses.append("(folder = ? OR folder LIKE ?)")
            params.extend([folder, f"{folder}/%"])
        if base:
            # A single space is the sentinel for "no base model detected".
            clauses.append("base_model = ?")
            params.append("" if base == " " else base)
        text = text.strip()
        if text:
            clauses.append("search_text LIKE ?")
            params.append(f"%{text.lower()}%")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        order = _SORT_ORDERS.get(sort, _SORT_ORDERS["newest"])

        with self._lock:
            connection = self.db()
            total_row = connection.execute(f"SELECT COUNT(*) AS count FROM files {where}", params).fetchone()
            rows = connection.execute(
                f"""
                SELECT id, name, folder, width, height, size, mtime, source, kind, root_id,
                       base_model, snippet, has_workflow
                FROM files {where} ORDER BY {order} LIMIT ? OFFSET ?
                """,
                [*params, max(1, min(200, limit)), max(0, offset)],
            ).fetchall()
        return {"total": int(total_row["count"] if total_row else 0),
                "items": [dict(row) for row in rows]}

    def item(self, entry_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self.db().execute("SELECT * FROM files WHERE id = ?", (entry_id,)).fetchone()
        if row is None:
            return None
        record = dict(row)
        recipe = None
        if record.get("recipe"):
            try:
                recipe = json.loads(record["recipe"])
            except ValueError:
                recipe = None
        return {"entry": record, "recipe": recipe}

    def store_recipe(self, entry_id: str, recipe: dict[str, Any]) -> None:
        with self._lock:
            connection = self.db()
            base_key = basemodel.key_of(recipe)
            connection.execute(
                "UPDATE files SET recipe = ?, source = ?, base_auto = ?, "
                "base_model = CASE WHEN base_source = 'manual' THEN base_model ELSE ? END, "
                "snippet = ? WHERE id = ?",
                (json.dumps(recipe, ensure_ascii=False, separators=(",", ":")),
                 recipe.get("source") or "none",
                 base_key,
                 base_key,
                 basemodel.snippet_of(recipe),
                 entry_id),
            )
            connection.commit()

    def set_base_model(self, entry_id: str, base_key: str) -> bool:
        """Pin a base model by hand; an empty key restores the detected one."""
        with self._lock:
            connection = self.db()
            if base_key:
                cursor = connection.execute(
                    "UPDATE files SET base_model = ?, base_source = 'manual' WHERE id = ?",
                    (base_key, entry_id))
            else:
                cursor = connection.execute(
                    "UPDATE files SET base_model = base_auto, base_source = 'auto' WHERE id = ?",
                    (entry_id,))
            connection.commit()
        return cursor.rowcount > 0

    def delete_entry(self, entry_id: str) -> bool:
        """Forget one file (used after it has been moved out of its root)."""
        with self._lock:
            connection = self.db()
            cursor = connection.execute("DELETE FROM files WHERE id = ?", (entry_id,))
            connection.commit()
        return cursor.rowcount > 0

    def base_counts(self) -> list[dict[str, Any]]:
        """Per-family totals for the sidebar filter; "" collects unknown ones."""
        with self._lock:
            rows = self.db().execute(
                "SELECT base_model, COUNT(*) AS count FROM files GROUP BY base_model ORDER BY count DESC"
            ).fetchall()
        return [{"key": row["base_model"], "count": int(row["count"])} for row in rows]

    def folders(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self.db().execute(
                """
                SELECT root_id, folder, COUNT(*) AS count, MAX(mtime) AS latest
                FROM files GROUP BY root_id, folder ORDER BY folder COLLATE NOCASE
                """
            ).fetchall()
        roots = {root.id: root.label for root in config.roots()}
        return [
            {
                "root_id": row["root_id"],
                "root_label": roots.get(row["root_id"], row["root_id"]),
                "folder": row["folder"],
                "count": int(row["count"]),
                "latest": row["latest"],
            }
            for row in rows
        ]

    def latest_mtime(self) -> float:
        """Newest file timestamp, so the page can notice a finished render."""
        with self._lock:
            row = self.db().execute("SELECT MAX(mtime) AS stamp FROM files").fetchone()
        return float(row["stamp"] or 0) if row else 0.0

    def counts(self) -> dict[str, Any]:
        with self._lock:
            rows = self.db().execute(
                "SELECT source, kind, COUNT(*) AS count FROM files GROUP BY source, kind"
            ).fetchall()
        by_source: dict[str, int] = {}
        by_kind: dict[str, int] = {}
        for row in rows:
            by_source[row["source"]] = by_source.get(row["source"], 0) + int(row["count"])
            by_kind[row["kind"]] = by_kind.get(row["kind"], 0) + int(row["count"])
        return {"by_source": by_source, "by_kind": by_kind, "total": self._count_all()}


def _video_recipe() -> dict[str, Any]:
    return {
        "source": "video",
        "positive": "",
        "negative": "",
        "models": {"checkpoints": [], "unet": [], "vae": [], "clip": [], "clip_skip": None},
        "loras": [],
        "samplers": [],
        "latent": {"width": None, "height": None, "batch": None, "node": None},
        "extras": [],
        "node_types": {},
        "node_count": 0,
        "warnings": ["no_metadata"],
    }
