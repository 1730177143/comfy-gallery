"""Integration smoke test for the gallery backend, runnable outside ComfyUI.

Stubs the two ComfyUI modules the pack touches (``folder_paths`` and ``server``)
so the index, the parsers and the thumbnail cache can be exercised against real
output files without starting ComfyUI.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import time
from pathlib import Path

WORK = Path(__file__).resolve().parent.parent / "tmp" / "smoke"
shutil.rmtree(WORK, ignore_errors=True)
OUTPUT = WORK / "output"
USER_DIR = WORK / "user"
OUTPUT.mkdir(parents=True)
(USER_DIR / "default" / "workflows").mkdir(parents=True)

SOURCE = Path("D:/AI/ComfyUI-aki-v3.2/ComfyUI/output")

# A spread of files: nested folders, both metadata flavours, one bare PNG.
samples = []
for pattern in ("**/*.png",):
    samples = sorted(SOURCE.glob(pattern))
picked = samples[-14:] + samples[:6] + samples[len(samples) // 2: len(samples) // 2 + 6]
copied = 0
for index, path in enumerate(picked):
    if copied >= 24:
        break
    target_dir = OUTPUT / ("set" + str(index % 3) if index % 3 else "")
    target_dir.mkdir(exist_ok=True)
    shutil.copy2(path, target_dir / path.name)
    copied += 1

# Two files made with the same checkpoint: the base-model sync test needs a pair
# whose model name is recorded, which the real spread does not guarantee.
from PIL import Image, PngImagePlugin  # noqa: E402

for suffix in ("a", "b"):
    info = PngImagePlugin.PngInfo()
    info.add_text("parameters",
                  "\n".join([
                      "a portrait",
                      "Negative prompt: blur",
                      "Steps: 20, Sampler: Euler a, CFG scale: 7, Seed: 42, Size: 512x512, "
                      "Model: sharedTestModel_v1, Model hash: deadbeef",
                  ]))
    Image.new("RGB", (64, 64), (40, 60, 90)).save(OUTPUT / f"shared-{suffix}.png", pnginfo=info)

# Bare file with no metadata at all.
bare = next(p for p in samples if p.name.startswith("pose_"))
shutil.copy2(bare, OUTPUT / "no-metadata.png")
print(f"copied {copied + 1} files into {OUTPUT}")

stubs = WORK / "stubs"
stubs.mkdir()
(stubs / "folder_paths.py").write_text(
    "import os\n"
    f"OUT = {str(OUTPUT)!r}\n"
    f"USR = {str(USER_DIR)!r}\n"
    "def get_output_directory():\n    return OUT\n"
    "def get_user_directory():\n    return USR\n"
    "def get_input_directory():\n    return OUT\n"
    "def get_temp_directory():\n    return OUT\n",
    encoding="utf-8",
)
(stubs / "server.py").write_text(
    "class _Routes:\n"
    "    def _register(self, *a, **k):\n"
    "        return lambda fn: fn\n"
    "    get = post = put = delete = _register\n"
    "class PromptServer:\n"
    "    instance = type('I', (), {'routes': _Routes()})()\n",
    encoding="utf-8",
)

sys.path.insert(0, str(stubs))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gallery import config, index, metadata, thumbs  # noqa: E402
from gallery.parse import build_recipe  # noqa: E402

failures: list[str] = []


def check(condition: bool, label: str, detail: object = "") -> None:
    print(("  ok   " if condition else "  FAIL ") + label + (f"  [{detail}]" if not condition else ""))
    if not condition:
        failures.append(label)


started = time.time()
gallery = index.GalleryIndex()
started_scan = time.time()
gallery._scan(force=True)
scan_seconds = time.time() - started_scan
print(f"scan finished in {scan_seconds:.2f}s")

counts = gallery.counts()
check(counts["total"] >= 20, f"indexed {counts['total']} files")
check(counts["by_source"].get("comfy", 0) > 0, "comfy recipes parsed")
check(counts["by_source"].get("a1111", 0) > 0, "a1111 recipes parsed")
check(counts["by_source"].get("none", 0) > 0, "files without metadata kept")

page = gallery.query(limit=10)
check(len(page["items"]) == 10, "pagination returns a page")
check(page["total"] == counts["total"], "page total matches index")

folder = gallery.query(folder="set1", limit=50)
check(all(item["folder"].startswith("set1") for item in folder["items"]), "folder filter scopes results")

searched = gallery.query(text="lora", limit=50)
check(searched["total"] >= 0, "free text search runs")

record = gallery.item(page["items"][0]["id"])
check(record is not None and record["recipe"]["source"] != "", "detail record has a recipe")

folders = gallery.folders()
check(len(folders) >= 2, f"{len(folders)} folders listed")

# Every indexed image must be able to produce a thumbnail and a resolvable path.
first = page["items"][0]
source = config.resolve_entry(first["id"])
check(source is not None and source.is_file(), "entry id resolves to a real file")
thumb = thumbs.ensure_thumb(source, first["id"], first["mtime"], first["size"], 256)
check(thumb is not None and thumb.is_file() and thumb.stat().st_size > 0, "thumbnail generated")
if thumb:
    again = thumbs.ensure_thumb(source, first["id"], first["mtime"], first["size"], 256)
    check(again == thumb, "thumbnail is cached")

check(config.resolve_entry("output:../etc/passwd") is None, "path traversal rejected")
check(config.resolve_entry("bogus:whatever.png") is None, "unknown root rejected")

# --- base-model corrections -------------------------------------------------
# Files made with one model share a model_key, so one correction can fix a batch.
with_model = [item for item in gallery.query(limit=200)["items"]
              if item.get("model_key") == "sharedtestmodel_v1"]
check(len(with_model) == 2, "files made with one model share a model_key", len(with_model))
if with_model:
    subject = with_model[0]
    siblings = [item for item in gallery.query(limit=200)["items"]
                if item.get("model_key") == "sharedtestmodel_v1"]
    changed = gallery.set_base_model(subject["id"], "sdxl", sync_model=True)
    check(changed == len(siblings), "sync corrected the whole model batch",
          f"{changed} vs {len(siblings)}")
    pinned = [item for item in gallery.query(limit=200)["items"]
              if item.get("model_key") == "sharedtestmodel_v1"]
    check(all(item["base_model"] == "sdxl" and item["base_source"] == "manual" for item in pinned),
          "every sibling is pinned")

    # A rescan must not undo the correction...
    gallery._scan(force=True)
    after_scan = gallery.item(subject["id"])["entry"]
    check(after_scan["base_model"] == "sdxl" and after_scan["base_source"] == "manual",
          "a rescan keeps the pinned base", after_scan["base_model"])

    # ...and neither must a full rebuild, which throws every row away.
    gallery.rebuild(preserve_manual=True)
    after_rebuild = [item for item in gallery.query(limit=200)["items"]
                     if item.get("model_key") == "sharedtestmodel_v1"]
    check(after_rebuild and all(item["base_model"] == "sdxl" for item in after_rebuild),
          "a rebuild keeps the pinned base", len(after_rebuild))

    # Resetting one file clears its pin without touching the others.
    gallery.set_base_model(subject["id"], "")
    cleared = gallery.item(subject["id"])["entry"]
    check(cleared["base_source"] == "auto", "reset restores the detected base")

# --- indexing a single freshly saved file -----------------------------------
fresh = OUTPUT / "brand-new.png"
if not fresh.exists():
    shutil.copy2(bare, fresh)
indexed = gallery.index_files([fresh])
check(indexed == 1, "a single new file can be indexed on its own", indexed)
check(any(item["name"] == "brand-new.png" for item in gallery.query(limit=100)["items"]),
      "the new file shows up without a full scan")

# --- a missing root must not wipe the index --------------------------------
before = gallery.query(limit=1)["total"]
real_roots = config.roots()
config.roots = lambda: [type(real_roots[0])("output", "output", OUTPUT / "does-not-exist")]
gallery._scan(force=False)
config.roots = lambda: real_roots
check(gallery.query(limit=1)["total"] == before,
      "an unreadable root does not delete rows", gallery.query(limit=1)["total"])

# HTTP surface: registration must succeed against the stub server.
from gallery import api  # noqa: E402

api.init()
check(True, "routes registered on the stub server")


class FakeRequest:
    """Just enough of aiohttp's Request for the handlers under test."""

    def __init__(self, query=None, method="GET", body=None):
        self.query = query or {}
        self.method = method
        self._body = body or {}
        self.can_read_body = method == "POST"

    async def json(self):
        return self._body


# Call every handler directly. A single undefined name in one payload used to take
# the whole detail view down while the other endpoints kept working.
api.INDEX = gallery
first_id = page["items"][0]["id"]
for label, coro in [
    ("state", api.api_state(FakeRequest())),
    ("items", api.api_items(FakeRequest({"limit": "5"}))),
    ("item", api.api_item(FakeRequest({"id": first_id}))),
    ("pending", api.api_pending(FakeRequest(method="POST"))),
]:
    response = asyncio.run(coro)
    check(response.status == 200, f"{label} endpoint answers 200", detail=response.status)

response = asyncio.run(api.api_delete(FakeRequest(method="POST", body={"ids": [first_id]})))
check(response.status == 200, "delete endpoint answers 200", detail=response.status)
response = asyncio.run(api.api_pending_undo(FakeRequest(method="POST", body={"ids": [first_id]})))
check(response.status == 200, "undo endpoint answers 200", detail=response.status)
check(len(api.PENDING.list()) == 0, "undo emptied the queue")

# Recipe payload must survive a JSON round trip (it is stored in SQLite).
sample_item = next((row for row in page["items"] if row["source"] == "comfy"), page["items"][0])
payload = metadata.read_payloads(config.resolve_entry(sample_item["id"]))
recipe = build_recipe(payload)
encoded = json.dumps(recipe, ensure_ascii=False)
check(json.loads(encoded)["source"] == recipe["source"], "recipe serializes cleanly")

elapsed = time.time() - started
print(f"\n{counts['total']} files, {scan_seconds / max(1, counts['total']) * 1000:.0f} ms/file, total {elapsed:.1f}s")
print("FAILURES:", failures if failures else "none")

shutil.rmtree(WORK, ignore_errors=True)
sys.exit(1 if failures else 0)
