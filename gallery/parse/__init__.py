"""Metadata interpretation, split by the application that wrote the file."""

from __future__ import annotations

from typing import Any

from .a1111 import build_from_a1111
from .novelai import build_from_novelai, looks_like_novelai
from .recipe import build_from_prompt, build_search_blob

__all__ = ["build_recipe", "build_search_blob", "build_from_a1111", "build_from_novelai",
           "build_from_prompt", "looks_like_novelai"]


def build_recipe(payload: dict[str, Any]) -> dict[str, Any]:
    """Pick the richest interpretation available for one file's payload.

    A ComfyUI graph wins over an Automatic1111 string because it also carries
    LoRA strengths and per-pass sampler settings; the string is the fallback for
    files saved by older tooling or by another frontend.
    """
    prompt = payload.get("prompt")
    if isinstance(prompt, dict) and prompt:
        recipe = build_from_prompt(prompt)
        if recipe.get("positive") or recipe.get("loras") or recipe.get("models", {}).get("checkpoints"):
            return recipe

    parameters = payload.get("parameters")
    if isinstance(parameters, str) and parameters.strip():
        recipe = build_from_a1111(parameters)
        if not recipe.get("positive") and isinstance(prompt, dict) and prompt:
            # The A1111 string was unusable but the graph still carries text.
            graph_recipe = build_from_prompt(prompt)
            graph_recipe["source"] = "a1111+comfy"
            return graph_recipe
        return recipe

    if looks_like_novelai(payload):
        return build_from_novelai(payload)

    workflow = payload.get("workflow")
    if isinstance(workflow, dict) and workflow:
        from .ui_workflow import build_from_ui_workflow

        return build_from_ui_workflow(workflow)

    if isinstance(prompt, dict) and prompt:
        return build_from_prompt(prompt)

    return {
        "source": "none",
        "positive": "",
        "negative": "",
        "models": {"checkpoints": [], "unet": [], "vae": [], "clip": [], "clip_skip": None},
        "loras": [],
        "samplers": [],
        "latent": {"width": None, "height": None, "batch": None},
        "extras": [],
        "node_types": {},
        "node_count": 0,
    }
