"""Interpret an Automatic1111 ``parameters`` string.

ComfyUI-Image-Saver and most external frontends write this flat format, so the
gallery can show a recipe for files that never stored a ComfyUI graph at all.
"""

from __future__ import annotations

import re
from typing import Any

from .graph import as_number, as_text
from .lora_tags import clean_lora_name, parse_lora_tags

_SETTINGS_PAIR_RE = re.compile(r"([A-Za-z][\w \-/]*?):\s*([^,]+)")
_NEGATIVE_RE = re.compile(r"(?:^|\n)\s*Negative prompt:\s*", re.I)
_SIZE_RE = re.compile(r"^\s*(\d+)\s*[x×]\s*(\d+)\s*$")


def _split_sections(body: str) -> tuple[str, str, dict[str, str]]:
    """Split the payload into positive text, negative text and settings."""
    lines = body.splitlines()
    settings_line = ""
    # The settings line is the last non-empty line, and only that line.
    for index in range(len(lines) - 1, -1, -1):
        if not lines[index].strip():
            continue
        if "Steps:" in lines[index]:
            settings_line = lines[index]
            del lines[index]
        break

    remainder = "\n".join(lines)
    match = _NEGATIVE_RE.search(remainder)
    if match:
        positive = remainder[: match.start()]
        negative = remainder[match.end():]
    else:
        positive, negative = remainder, ""

    settings: dict[str, str] = {}
    for key, value in _SETTINGS_PAIR_RE.findall(settings_line):
        settings[key.strip().lower()] = value.strip()
    return positive.strip(), negative.strip(), settings


def build_from_a1111(text: str) -> dict[str, Any]:
    body = as_text(text, 200000)
    positive, negative, settings = _split_sections(body)

    loras: list[dict[str, Any]] = []
    seen: set[str] = set()
    for tag in parse_lora_tags(positive):
        display = clean_lora_name(tag["name"])
        if not display or display.lower() in seen:
            continue
        seen.add(display.lower())
        loras.append({
            "name": display,
            "path": tag["name"],
            "strength_model": tag["strength_model"],
            "strength_clip": tag["strength_clip"],
            "active": True,
            "node": None,
            "node_class": "prompt-tag",
        })

    models: dict[str, Any] = {"checkpoints": [], "unet": [], "vae": [], "clip": [], "clip_skip": None}
    model_name = settings.get("model")
    if model_name:
        models["checkpoints"].append({
            "name": model_name,
            "path": model_name,
            "node": None,
            "node_class": "parameters",
            "title": "Model",
            "hash": settings.get("model hash") or None,
        })
    clip_skip = as_number(settings.get("clip skip"))
    if clip_skip:
        models["clip_skip"] = int(clip_skip)

    width = height = None
    size_match = _SIZE_RE.match(settings.get("size", ""))
    if size_match:
        width, height = int(size_match.group(1)), int(size_match.group(2))

    sampler_pass = {
        "node": None,
        "title": "Sampler",
        "node_class": "parameters",
        "steps": as_number(settings.get("steps")),
        "cfg": as_number(settings.get("cfg scale")),
        "sampler": settings.get("sampler") or None,
        "scheduler": settings.get("schedule type") or settings.get("scheduler") or None,
        "seed": as_number(settings.get("seed")),
        "denoise": as_number(settings.get("denoising strength")),
        "start_at_step": None,
        "end_at_step": None,
        "skipped": False,
    }

    extras: list[dict[str, Any]] = []
    if settings.get("vae"):
        extras.append({"kind": "vae_name", "label": "VAE", "value": settings["vae"],
                       "node": None, "node_class": "parameters"})

    return {
        "source": "a1111",
        "positive": positive,
        "negative": negative,
        "models": models,
        "loras": loras,
        "samplers": [sampler_pass],
        "latent": {"width": width, "height": height, "batch": None, "node": None},
        "extras": extras,
        "node_types": {},
        "node_count": 0,
        "warnings": [] if positive else ["no_prompt"],
    }
