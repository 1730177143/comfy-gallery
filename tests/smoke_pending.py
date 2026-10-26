"""Deferred deletion: undo window, pause, batch undo and real expiry.

Runs against a throwaway copy of a few real output files, so it can exercise the
purge (a file actually landing in ``.gallery-trash``) without touching the
user's library.
"""

from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path

PACK_ROOT = Path(__file__).resolve().parent.parent
WORK = PACK_ROOT / "tmp" / "pending"
shutil.rmtree(WORK, ignore_errors=True)
OUTPUT = WORK / "output"
USER_DIR = WORK / "user"
OUTPUT.mkdir(parents=True)
(USER_DIR / "default" / "workflows").mkdir(parents=True)

SOURCE = Path("D:/AI/ComfyUI-aki-v3.2/ComfyUI/output")
picked = sorted(SOURCE.rglob("*.png"))[-4:]
for index, path in enumerate(picked):
    shutil.copy2(path, OUTPUT / f"shot{index}.png")

stubs = WORK / "stubs"
stubs.mkdir()
(stubs / "folder_paths.py").write_text(
    "OUT = %r\nUSR = %r\ndef get_output_directory():\n    return OUT\n"
    "def get_user_directory():\n    return USR\n"
    "def get_input_directory():\n    return OUT\n"
    "def get_temp_directory():\n    return OUT\n" % (str(OUTPUT), str(USER_DIR)),
    encoding="utf-8",
)
(stubs / "server.py").write_text(
    "class _Routes:\n"
    "    def _register(self, *a, **k):\n        return lambda fn: fn\n"
    "    get = post = put = delete = _register\n"
    "class PromptServer:\n"
    "    instance = type('I', (), {'routes': _Routes()})()\n",
    encoding="utf-8",
)

sys.path.insert(0, str(stubs))
sys.path.insert(0, str(PACK_ROOT))

from gallery import config, trash  # noqa: E402
from gallery.index import GalleryIndex  # noqa: E402
from gallery.pending import PendingQueue  # noqa: E402

FAILURES: list[str] = []


def check(condition: bool, label: str, detail: object = "") -> None:
    print(("  ok   " if condition else "  FAIL ") + label + (f"  [{detail}]" if not condition else ""))
    if not condition:
        FAILURES.append(label)


index = GalleryIndex()
index._scan(force=True)
entries = index.query(limit=10)["items"]
check(len(entries) == 4, f"indexed {len(entries)} files")

expired: list[str] = []
queue = PendingQueue(lambda entry_id: expired.append(entry_id))
queue.start()

first, second = entries[0], entries[1]
queue.add(first, 30)
queue.add(second, 30)
check(queue.count() == 2, "two entries queued")
check(all(item["remaining"] > 25 for item in queue.list()), "deadline is in the future")

# Pausing freezes the remaining time instead of letting it drain.
before = {item["id"]: item["remaining"] for item in queue.list()}
queue.hold(3)
time.sleep(2.2)
after = {item["id"]: item["remaining"] for item in queue.list()}
check(queue.paused(), "queue reports paused")
check(
    all(abs(after[key] - before[key]) < 1.5 for key in before),
    "remaining time frozen while paused",
    f"{before} -> {after}",
)

# Undo one, keep the other.
removed = queue.cancel([first["id"]])
check(removed == 1 and queue.count() == 1, "single undo removed one entry", removed)
check(queue.cancel([first["id"]]) == 0, "undoing twice is a no-op")

# Undo everything.
queue.add(first, 30)
check(queue.count() == 2, "re-queued for the batch-undo case")
check(queue.cancel(queue.ids()) == 2 and queue.count() == 0, "batch undo clears the queue")

# Real expiry: the file must land in .gallery-trash and leave the index.
def expire(entry_id: str) -> None:
    assert trash.move_to_trash(entry_id) is not None
    index.delete_entry(entry_id)


queue_expire = PendingQueue(expire)
queue_expire.start()
queue_expire.add(first, 1)
target = OUTPUT / trash.TRASH_DIRNAME / first["name"]
deadline = time.time() + 6
while time.time() < deadline and not target.exists():
    time.sleep(0.3)
check(target.exists(), "expired file moved into .gallery-trash")
check(index.item(first["id"]) is None, "expired entry dropped from the index")
check(index.query(limit=10)["total"] == 3, "remaining files still indexed")

queue.stop()
queue_expire.stop()
print("\nFAILURES:", FAILURES if FAILURES else "none")
shutil.rmtree(WORK, ignore_errors=True)
sys.exit(1 if FAILURES else 0)
