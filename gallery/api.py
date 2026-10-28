"""HTTP surface of the gallery: one page plus its JSON API.

Everything is mounted on ComfyUI's own aiohttp application, so the page lives at
``/gallery`` on the same origin and port as the running instance. Entry ids are
always resolved through the configured roots, never taken as raw paths.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

from aiohttp import web

from . import basemodel, config, metadata, thumbs, trash
from .pending import PendingQueue
from .index import GalleryIndex
from .parse import build_recipe

LOGGER = logging.getLogger("comfy-gallery")

INDEX = GalleryIndex()


def _expire_entry(entry_id: str) -> None:
    """The undo window ran out: move the file into the trash and forget it."""
    moved = trash.move_to_trash(entry_id)
    INDEX.delete_entry(entry_id)
    favorites = [item for item in (config.settings().get("favorites") or []) if item != entry_id]
    config.save_settings({"favorites": favorites})
    if moved is None:
        LOGGER.warning("comfy-gallery could not move %s to the trash", entry_id)


PENDING = PendingQueue(_expire_entry)

_SAFE_NAME_RE = re.compile(r"[^\w.\-]+", re.UNICODE)
_REGISTERED_ATTR = "_comfy_gallery_registered"


def _json(payload: Any, status: int = 200) -> web.Response:
    return web.json_response(payload, status=status,
                             dumps=lambda value: json.dumps(value, ensure_ascii=False))


def _int_param(request: web.Request, name: str, default: int, low: int, high: int) -> int:
    try:
        value = int(request.query.get(name, default))
    except (TypeError, ValueError):
        value = default
    return max(low, min(high, value))


def _entry_or_error(request: web.Request) -> tuple[dict[str, Any] | None, web.Response | None]:
    entry_id = request.query.get("id", "").strip()
    if not entry_id:
        return None, _json({"error": "missing_id"}, 400)
    record = INDEX.item(entry_id)
    if record is None:
        return None, _json({"error": "not_found"}, 404)
    return record, None


# -- page and assets ------------------------------------------------------


async def page(_request: web.Request) -> web.StreamResponse:
    INDEX.ensure_started()
    return web.FileResponse(
        config.WEB_ROOT / "index.html",
        headers={"Cache-Control": "no-store"},
    )


async def asset(request: web.Request) -> web.StreamResponse:
    relative = request.match_info.get("path", "")
    root = (config.WEB_ROOT / "assets").resolve()
    try:
        target = (root / config.normalize_rel(relative)).resolve()
    except ValueError:
        return web.Response(status=404)
    if root not in target.parents or not target.is_file():
        return web.Response(status=404)
    return web.FileResponse(target, headers={"Cache-Control": "no-cache"})


# -- API ------------------------------------------------------------------


async def api_state(_request: web.Request) -> web.StreamResponse:
    INDEX.ensure_started()
    settings = config.settings()
    return _json({
        "scan": INDEX.state,
        "counts": INDEX.counts(),
        "latest_mtime": INDEX.latest_mtime(),
        "favorites": list(settings.get("favorites") or []),
        "layout": settings.get("layout") or "grid",
        "detail_mode": settings.get("detail_mode") or "side",
        "columns": settings.get("columns") or 0,
        "families": basemodel.families(),
        "pending": PENDING.list(),
        "pending_paused": PENDING.paused(),
        "server_time": time.time(),
        "undo_seconds": int(settings.get("undo_seconds") or 0),
        "wheel_navigate": bool(settings.get("wheel_navigate")),
        "wheel_nav": bool(settings.get("wheel_nav", True)),
        "roots": [{"id": root.id, "label": root.label, "path": str(root.path)}
                  for root in config.roots()],
    })


async def api_items(request: web.Request) -> web.StreamResponse:
    INDEX.ensure_started()
    settings = config.settings()
    favorites = list(settings.get("favorites") or [])
    only_ids = favorites if request.query.get("fav") == "1" else None
    base_filter = request.query.get("base", "")
    if base_filter == "-":
        base_filter = " "  # sentinel: rows with an empty base_model
    result = INDEX.query(
        folder=request.query.get("folder", ""),
        text=request.query.get("q", ""),
        sort=request.query.get("sort", "newest"),
        root_id=request.query.get("root", ""),
        base=base_filter,
        offset=_int_param(request, "offset", 0, 0, 1_000_000),
        limit=_int_param(request, "limit", int(settings.get("page_size") or 60), 1, 200),
        only_ids=only_ids,
    )
    starred = set(favorites)
    items = [{**item, "favorite": item["id"] in starred} for item in result["items"]]
    return _json({"scan": INDEX.state, "total": result["total"], "items": items})


async def api_item(request: web.Request) -> web.StreamResponse:
    record, error = _entry_or_error(request)
    if error is not None:
        return error
    entry = record["entry"]
    recipe = record["recipe"]

    source_path = config.resolve_entry(entry["id"])
    if source_path is None:
        return _json({"error": "file_missing"}, 404)

    if not recipe or recipe.get("source") in (None, "none"):
        # A file written before the pack existed, or one whose metadata changed
        # on disk: re-read it once and keep the result.
        payload = metadata.read_payloads(source_path)
        recipe = build_recipe(payload)
        INDEX.store_recipe(entry["id"], recipe)

    return _json({
        "entry": dict(entry),
        "recipe": recipe,
        "base_model": basemodel.infer(recipe, allow_lora=True),
        "detected": entry.get("base_auto") or "",
        "base_source": entry.get("base_source") or "auto",
        "families": basemodel.families(),
        "has_workflow": bool(entry.get("has_workflow")),
        "favorite": entry["id"] in set(config.settings().get("favorites") or []),
        "file_url": f"/gallery/api/file?id={quote(entry['id'], safe='')}",
        "thumb_url": f"/gallery/api/thumb?id={quote(entry['id'], safe='')}&s=768",
    })


async def api_thumb(request: web.Request) -> web.StreamResponse:
    record, error = _entry_or_error(request)
    if error is not None:
        return error
    entry = record["entry"]
    source_path = config.resolve_entry(entry["id"])
    if source_path is None:
        return web.Response(status=404)
    edge = _int_param(request, "s", int(config.settings().get("thumb_size") or 384), 64, 1024)
    cached = await asyncio.get_running_loop().run_in_executor(
        None, thumbs.ensure_thumb, source_path, entry["id"], entry["mtime"], entry["size"], edge
    )
    if cached is None:
        return web.Response(status=500)
    return web.FileResponse(cached, headers={"Cache-Control": "max-age=604800"})


async def api_file(request: web.Request) -> web.StreamResponse:
    record, error = _entry_or_error(request)
    if error is not None:
        return error
    source_path = config.resolve_entry(record["entry"]["id"])
    if source_path is None:
        return web.Response(status=404)
    return web.FileResponse(source_path)


async def api_folders(_request: web.Request) -> web.StreamResponse:
    INDEX.ensure_started()
    return _json({"folders": INDEX.folders(), "bases": INDEX.base_counts()})


async def api_workflow(request: web.Request) -> web.StreamResponse:
    record, error = _entry_or_error(request)
    if error is not None:
        return error
    source_path = config.resolve_entry(record["entry"]["id"])
    if source_path is None:
        return _json({"error": "file_missing"}, 404)
    payload = metadata.read_payloads(source_path)
    if not payload.get("workflow") and not payload.get("prompt"):
        return _json({"error": "no_workflow"}, 404)
    return _json({"workflow": payload.get("workflow"), "prompt": payload.get("prompt"),
                  "name": record["entry"]["name"]})


async def api_export_workflow(request: web.Request) -> web.StreamResponse:
    """Copy a file's editor workflow into ComfyUI's own workflow library."""
    record, error = _entry_or_error(request)
    if error is not None:
        return error
    source_path = config.resolve_entry(record["entry"]["id"])
    if source_path is None:
        return _json({"error": "file_missing"}, 404)
    payload = metadata.read_payloads(source_path)
    workflow = payload.get("workflow")
    if not isinstance(workflow, dict):
        return _json({"error": "no_workflow"}, 404)

    stem = Path(record["entry"]["name"]).stem
    safe = _SAFE_NAME_RE.sub("_", stem).strip("_") or "workflow"
    target_dir = Path(_user_workflows_dir()) / "gallery"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{safe}.json"
    target.write_text(json.dumps(workflow, ensure_ascii=False), encoding="utf-8")
    return _json({"saved": f"gallery/{safe}.json", "name": safe})


def _user_workflows_dir() -> Path:
    import folder_paths  # noqa: PLC0415 - only inside a running ComfyUI

    return Path(folder_paths.get_user_directory()) / "default" / "workflows"


async def api_rescan(_request: web.Request) -> web.StreamResponse:
    INDEX.ensure_started(force=True)
    return _json({"scan": INDEX.state})


async def api_favorite(request: web.Request) -> web.StreamResponse:
    """Star or unstar entries. Starred ids live in the settings file.

    Accepts one id in the query string or a ``{"ids": [...], "on": 1|0}`` body so
    a multi-selection can be applied in one round trip.
    """
    body: dict[str, Any] = {}
    if request.method == "POST" and request.can_read_body:
        try:
            body = await request.json()
        except (ValueError, json.JSONDecodeError):
            body = {}

    ids = [str(item) for item in (body.get("ids") or []) if str(item).strip()]
    if not ids:
        single = request.query.get("id", "").strip()
        if single:
            ids = [single]
    if not ids:
        return _json({"error": "missing_id"}, 400)

    wanted = body.get("on")
    if wanted is None:
        wanted = request.query.get("on")
    known = [item for item in ids if INDEX.item(item) is not None]
    if not known:
        return _json({"error": "not_found"}, 404)

    favorites = list(config.settings().get("favorites") or [])
    starred = (known[0] not in favorites) if wanted is None else wanted in (1, "1", True)
    if starred:
        for entry_id in known:
            if entry_id not in favorites:
                favorites.append(entry_id)
    else:
        drop = set(known)
        favorites = [item for item in favorites if item not in drop]
    config.save_settings({"favorites": favorites})
    return _json({"ids": known, "favorite": starred, "count": len(favorites)})


async def api_trash(request: web.Request) -> web.StreamResponse:
    """Move a file into its root's ``.gallery-trash`` folder, then drop it."""
    entry_id = request.query.get("id", "").strip()
    if INDEX.item(entry_id) is None:
        return _json({"error": "not_found"}, 404)
    moved = await asyncio.get_running_loop().run_in_executor(None, trash.move_to_trash, entry_id)
    if moved is None:
        return _json({"error": "file_missing"}, 404)
    INDEX.delete_entry(entry_id)
    favorites = [item for item in (config.settings().get("favorites") or []) if item != entry_id]
    config.save_settings({"favorites": favorites})
    return _json({"id": entry_id, "moved_to": str(moved), "trash": trash.TRASH_DIRNAME})


async def api_delete(request: web.Request) -> web.StreamResponse:
    """Queue one or more entries for deletion after the undo window."""
    body: dict[str, Any] = {}
    try:
        body = await request.json()
    except (ValueError, json.JSONDecodeError):
        body = {}
    ids = [str(item) for item in (body.get("ids") or []) if str(item).strip()]
    if not ids:
        single = request.query.get("id", "").strip()
        if single:
            ids = [single]
    if not ids:
        return _json({"error": "missing_id"}, 400)

    settings = config.settings()
    seconds = int(settings.get("undo_seconds") or 0)
    results: list[dict[str, Any]] = []
    for entry_id in ids:
        record = INDEX.item(entry_id)
        if record is None:
            continue
        if seconds > 0:
            PENDING.add(record["entry"], seconds)
            results.append({"id": entry_id, "pending": True})
            continue
        # Undo turned off: delete straight away, exactly like the old behaviour.
        moved = await asyncio.get_running_loop().run_in_executor(None, trash.move_to_trash, entry_id)
        if moved is None:
            results.append({"id": entry_id, "error": "file_missing"})
            continue
        INDEX.delete_entry(entry_id)
        favorites = [item for item in (settings.get("favorites") or []) if item != entry_id]
        config.save_settings({"favorites": favorites})
        results.append({"id": entry_id, "deleted": True})

    return _json({"results": results, "undo_seconds": seconds, "pending": PENDING.list()})


async def api_pending(request: web.Request) -> web.StreamResponse:
    """The undo queue, plus the pause state the viewer needs to show."""
    if request.method == "POST":
        body: dict[str, Any] = {}
        try:
            body = await request.json()
        except (ValueError, json.JSONDecodeError):
            body = {}
        if body.get("release"):
            PENDING.release()
        else:
            PENDING.hold()
    return _json({
        "items": PENDING.list(),
        "paused": PENDING.paused(),
        "server_time": time.time(),
    })


async def api_pending_undo(request: web.Request) -> web.StreamResponse:
    """Cancel the deletion of specific entries, or of everything queued."""
    if request.query.get("all") == "1":
        removed = PENDING.cancel(PENDING.ids())
        return _json({"removed": removed, "pending": PENDING.list()})

    body: dict[str, Any] = {}
    try:
        body = await request.json()
    except (ValueError, json.JSONDecodeError):
        body = {}
    ids = [str(item) for item in (body.get("ids") or []) if str(item).strip()]
    if not ids:
        single = request.query.get("id", "").strip()
        if single:
            ids = [single]
    if not ids:
        return _json({"error": "missing_id"}, 400)
    removed = PENDING.cancel(ids)
    return _json({"removed": removed, "pending": PENDING.list()})


async def api_base(request: web.Request) -> web.StreamResponse:
    """Pin or reset the base model of one entry."""
    entry_id = request.query.get("id", "").strip()
    base_key = request.query.get("base", "").strip()
    if INDEX.item(entry_id) is None:
        return _json({"error": "not_found"}, 404)
    known = {family["key"] for family in basemodel.families()}
    if base_key and base_key not in known:
        return _json({"error": "unknown_family"}, 400)
    if not INDEX.set_base_model(entry_id, base_key):
        return _json({"error": "not_found"}, 404)
    record = INDEX.item(entry_id)
    return _json({
        "id": entry_id,
        "base_model": basemodel.infer(record["recipe"] or {}, allow_lora=True) if base_key else None,
        "effective": base_key,
        "detected": (record["entry"].get("base_auto") or ""),
    })


async def api_settings(request: web.Request) -> web.StreamResponse:
    if request.method == "POST":
        try:
            body = await request.json()
        except (ValueError, json.JSONDecodeError):
            return _json({"error": "bad_json"}, 400)
        patch: dict[str, Any] = {}
        rescan = False
        if isinstance(body.get("extra_roots"), list):
            roots: list[str] = []
            for raw in body["extra_roots"]:
                if not isinstance(raw, str) or not raw.strip():
                    continue
                path = Path(raw).expanduser()
                if path.is_dir():
                    roots.append(str(path.resolve()))
            patch["extra_roots"] = roots
            rescan = True
        if isinstance(body.get("include_video"), bool):
            patch["include_video"] = body["include_video"]
            rescan = True
        if body.get("thumb_size") is not None:
            try:
                patch["thumb_size"] = max(128, min(1024, int(body["thumb_size"])))
            except (TypeError, ValueError):
                pass
        if body.get("layout") in ("grid", "masonry"):
            patch["layout"] = body["layout"]
        if body.get("detail_mode") in ("side", "modal", "image"):
            patch["detail_mode"] = body["detail_mode"]
        if isinstance(body.get("wheel_nav"), bool):
            patch["wheel_nav"] = body["wheel_nav"]
        if isinstance(body.get("wheel_navigate"), bool):
            patch["wheel_navigate"] = body["wheel_navigate"]
        if body.get("undo_seconds") is not None:
            try:
                patch["undo_seconds"] = max(0, min(600, int(body["undo_seconds"])))
            except (TypeError, ValueError):
                pass
        if body.get("columns") is not None:
            try:
                patch["columns"] = max(0, min(12, int(body["columns"])))
            except (TypeError, ValueError):
                pass
        if body.get("page_size") is not None:
            try:
                patch["page_size"] = max(20, min(200, int(body["page_size"])))
            except (TypeError, ValueError):
                pass
        if patch:
            config.save_settings(patch)
            if rescan:
                INDEX.ensure_started(force=True)
    settings = config.settings()
    return _json({
        "settings": {key: settings.get(key) for key in config.DEFAULT_SETTINGS},
        "roots": [{"id": root.id, "label": root.label, "path": str(root.path)}
                  for root in config.roots()],
        "data_dir": str(config.data_dir()),
    })


# -- registration ---------------------------------------------------------


def init() -> None:
    """Attach every route to the running ComfyUI server, once per process."""
    try:
        import server as comfy_server  # noqa: PLC0415 - provided by ComfyUI

        routes = comfy_server.PromptServer.instance.routes
    except Exception as error:
        LOGGER.error("comfy-gallery could not reach ComfyUI's server: %s", error)
        return

    if getattr(routes, _REGISTERED_ATTR, False):
        return
    setattr(routes, _REGISTERED_ATTR, True)

    routes.get("/gallery")(page)
    routes.get("/gallery/")(page)
    routes.get("/gallery/assets/{path:.*}")(asset)
    routes.get("/gallery/api/state")(api_state)
    routes.get("/gallery/api/items")(api_items)
    routes.get("/gallery/api/item")(api_item)
    routes.get("/gallery/api/thumb")(api_thumb)
    routes.get("/gallery/api/file")(api_file)
    routes.get("/gallery/api/folders")(api_folders)
    routes.get("/gallery/api/workflow")(api_workflow)
    routes.post("/gallery/api/export-workflow")(api_export_workflow)
    routes.post("/gallery/api/rescan")(api_rescan)
    routes.post("/gallery/api/favorite")(api_favorite)
    routes.post("/gallery/api/base")(api_base)
    routes.post("/gallery/api/delete")(api_delete)
    routes.get("/gallery/api/pending")(api_pending)
    routes.post("/gallery/api/pending")(api_pending)
    routes.post("/gallery/api/pending/undo")(api_pending_undo)
    routes.post("/gallery/api/trash")(api_trash)
    routes.get("/gallery/api/settings")(api_settings)
    routes.post("/gallery/api/settings")(api_settings)

    INDEX.ensure_started()
    PENDING.start()
    LOGGER.info("comfy-gallery served at /gallery")
