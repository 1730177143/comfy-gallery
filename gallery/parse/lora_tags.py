"""LoRA file names and the ``<lora:name:weight>`` tag syntax.

Shared by the ComfyUI graph reader and the Automatic1111 string reader so both
report the same display names for the same file.
"""

from __future__ import annotations

import re
from typing import Any

from .graph import as_text

LORA_TAG_RE = re.compile(r"<lora:([^:>]+)(?::([-+]?[0-9.]+))?(?::([-+]?[0-9.]+))?>", re.I)

_EXTENSIONS = (".safetensors", ".sft", ".ckpt", ".pt", ".bin")


def clean_lora_name(value: Any) -> str:
    """Display name of a LoRA: no directory prefix, no extension."""
    text = as_text(value)
    if not text:
        return ""
    base = text.replace("\\", "/").rsplit("/", 1)[-1]
    for extension in _EXTENSIONS:
        if base.lower().endswith(extension):
            base = base[: -len(extension)]
            break
    return base.strip()


def parse_lora_tags(text: str) -> list[dict[str, Any]]:
    """Every ``<lora:name:w>`` occurrence in a prompt string."""
    results: list[dict[str, Any]] = []
    for match in LORA_TAG_RE.finditer(text or ""):
        model_weight = match.group(2) or match.group(3) or "1"
        clip_weight = match.group(3) or model_weight
        results.append({
            "name": match.group(1).strip(),
            "strength_model": _number(model_weight),
            "strength_clip": _number(clip_weight),
        })
    return results


def _number(raw: str) -> float | None:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None
