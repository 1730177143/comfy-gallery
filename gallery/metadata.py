"""Read the generation metadata a saved file carries.

ComfyUI's own ``SaveImage`` writes two PNG text chunks: ``prompt`` (the API
graph that actually executed) and ``workflow`` (the editor graph). Saver packs
such as ComfyUI-Image-Saver additionally write an Automatic1111 ``parameters``
string, sometimes into JPEG/WEBP EXIF instead of PNG text. All three shapes are
normalized here into one payload dictionary; interpretation happens in
``server.parse``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# EXIF tag holding free-form text (0x9286 = UserComment).
_EXIF_USER_COMMENT = 0x9286


def _maybe_json(value: Any) -> Any:
    """Decode a JSON string, tolerating a few shapes seen in the wild."""
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, bytes):
        value = _decode_bytes(value)
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if not (text.startswith("{") or text.startswith("[")):
        # Some savers prefix the payload (e.g. "ASCII\0\0\0"); retry from the
        # first brace before giving up.
        index = min(
            [pos for pos in (text.find("{"), text.find("[")) if pos >= 0] or [-1]
        )
        if index < 0:
            return None
        text = text[index:]
    try:
        return json.loads(text)
    except ValueError:
        return None


def _decode_bytes(raw: bytes) -> str:
    """Decode EXIF/PNG byte payloads, dropping EXIF's charset marker prefix."""
    for marker in (b"UNICODE\x00", b"ASCII\x00\x00\x00", b"\xef\xbb\xbf"):
        if raw.startswith(marker):
            raw = raw[len(marker) :]
            break
    for encoding in ("utf-8", "utf-16-be", "utf-16-le", "latin-1"):
        try:
            return raw.decode(encoding).strip("\x00").strip()
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace").strip("\x00")


def _exif_text(image) -> str | None:
    try:
        exif = image.getexif()
    except Exception:
        return None
    try:
        value = exif.get(_EXIF_USER_COMMENT)
    except Exception:
        return None
    if value is None:
        return None
    if isinstance(value, bytes):
        return _decode_bytes(value)
    return str(value)


def read_payloads(path: Path) -> dict[str, Any]:
    """Return the embedded generation metadata of one file.

    Keys: ``prompt`` (API graph), ``workflow`` (editor graph), ``parameters``
    (A1111 text), ``text_keys`` (chunk names found) and ``error`` when the file
    could not be opened at all.
    """
    from PIL import Image  # noqa: PLC0415 - Pillow ships with ComfyUI

    payload: dict[str, Any] = {
        "prompt": None,
        "workflow": None,
        "parameters": None,
        "text_keys": [],
        "size": None,
    }
    try:
        with Image.open(path) as image:
            payload["size"] = (int(image.size[0]), int(image.size[1]))
            info = dict(image.info)
            parameters = info.get("parameters")
            if isinstance(parameters, bytes):
                parameters = _decode_bytes(parameters)
            if isinstance(parameters, str) and parameters.strip():
                payload["parameters"] = parameters
            exif_text = None
            if "prompt" not in info and "workflow" not in info:
                exif_text = _exif_text(image)
    except Exception as error:  # corrupt or unsupported file
        payload["error"] = f"{type(error).__name__}: {error}"
        return payload

    payload["text_keys"] = sorted(key for key in info if isinstance(key, str))

    prompt = _maybe_json(info.get("prompt"))
    workflow = _maybe_json(info.get("workflow"))
    if isinstance(prompt, dict):
        payload["prompt"] = prompt
    if isinstance(workflow, dict):
        payload["workflow"] = workflow

    # JPEG/WEBP savers put the same payload in EXIF UserComment.
    if exif_text:
        decoded = _maybe_json(exif_text)
        if isinstance(decoded, dict):
            if isinstance(decoded.get("prompt"), dict) or isinstance(decoded.get("workflow"), dict):
                payload["prompt"] = payload["prompt"] or decoded.get("prompt")
                payload["workflow"] = payload["workflow"] or decoded.get("workflow")
            else:
                payload["prompt"] = payload["prompt"] or decoded
        elif payload["parameters"] is None:
            payload["parameters"] = exif_text

    return payload
