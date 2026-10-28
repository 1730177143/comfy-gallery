"""Read the generation data NovelAI writes into a PNG.

NovelAI stores a JSON blob in the ``Comment`` text chunk (``prompt``, ``uc``,
``steps``, ``scale``, ``seed``, ``sampler``, size and so on), plus a plain
``Description`` copy of the prompt. The older NAIDiffusion build used an
``sd-metadata`` chunk instead; both are accepted here.
"""

from __future__ import annotations

import json
from typing import Any

from ..parse.graph import as_number, as_text


def _maybe_json(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return {}
    text = value.strip()
    if not text.startswith("{"):
        index = text.find("{")
        if index < 0:
            return {}
        text = text[index:]
    try:
        decoded = json.loads(text)
    except ValueError:
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _sampler_name(data: dict[str, Any]) -> str:
    sampler = as_text(data.get("sampler")) or "k_euler"
    schedule = as_text(data.get("noise_schedule"))
    # NovelAI keeps sampler and schedule apart; the panel shows one field.
    return f"{sampler} · {schedule}" if schedule else sampler


def build_from_novelai(payload: dict[str, Any]) -> dict[str, Any]:
    data = _maybe_json(payload.get("comment")) or _maybe_json(payload.get("sd_metadata"))

    prompt = as_text(data.get("prompt")) or as_text(payload.get("description"))
    negative = as_text(data.get("uc")) or as_text(data.get("negative_prompt"))

    extras: list[dict[str, Any]] = []
    for key, label in (
        ("noise_schedule", "Noise schedule"),
        ("sm", "SMEA"),
        ("sm_dyn", "SMEA DYN"),
        ("dynamic_thresholding", "Dynamic thresholding"),
        ("cfg_rescale", "CFG rescale"),
        ("controlnet_strength", "ControlNet strength"),
        ("n_samples", "Batch"),
    ):
        value = data.get(key)
        if value in (None, "", 0, False):
            continue
        extras.append({
            "kind": key,
            "label": label,
            "value": ("yes" if value is True else "no" if value is False else as_text(value)),
            "node": None,
            "node_class": "novelai",
        })

    width = as_number(data.get("width"))
    height = as_number(data.get("height"))
    batch = as_number(data.get("n_samples"))

    sampler_pass = {
        "node": None,
        "title": "NovelAI",
        "node_class": "novelai",
        "steps": as_number(data.get("steps")),
        "cfg": as_number(data.get("scale")),
        "sampler": _sampler_name(data),
        "scheduler": as_text(data.get("noise_schedule")) or None,
        "seed": as_number(data.get("seed")),
        "denoise": None,
        "start_at_step": None,
        "end_at_step": None,
        "skipped": False,
    }

    return {
        "source": "novelai",
        "positive": prompt,
        "negative": negative,
        "models": {"checkpoints": [], "unet": [], "vae": [], "clip": [], "clip_skip": None},
        "loras": [],
        "samplers": [sampler_pass],
        "latent": {
            "width": int(width) if width else None,
            "height": int(height) if height else None,
            "batch": batch,
            "node": None,
            "estimated": False,
        },
        "extras": extras,
        "node_types": {},
        "node_count": 0,
        "warnings": [] if prompt else ["no_prompt"],
    }


def looks_like_novelai(payload: dict[str, Any]) -> bool:
    """True when the file carries a NovelAI comment or an NAIDiffusion blob."""
    if payload.get("sd_metadata"):
        return True
    comment = payload.get("comment")
    if not comment:
        return False
    data = _maybe_json(comment)
    if not data:
        return False
    # A Comment chunk that carries a prompt and sampler parameters is NovelAI's;
    # other tools also use Comment, but not with this shape.
    return bool(data.get("prompt") and (data.get("steps") or data.get("sampler") or data.get("seed")))
