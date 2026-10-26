"""Best-effort reading of an editor-format (UI) workflow.

Only used when a file stored ``workflow`` without the executed ``prompt`` graph.
UI widgets are positional arrays, so this maps the handful of core node types by
their documented widget order and marks the result as approximate.
"""

from __future__ import annotations

from typing import Any

# widget order per core node type; only the leading fields this panel shows
_WIDGET_MAP: dict[str, tuple[str, ...]] = {
    "CheckpointLoaderSimple": ("ckpt_name",),
    "UNETLoader": ("unet_name", "weight_dtype"),
    "VAELoader": ("vae_name",),
    "CLIPLoader": ("clip_name", "type"),
    "LoraLoader": ("lora_name", "strength_model", "strength_clip"),
    "LoraLoaderModelOnly": ("lora_name", "strength_model"),
    "KSampler": ("seed", "control_after_generate", "steps", "cfg", "sampler_name", "scheduler", "denoise"),
    "KSamplerAdvanced": (
        "add_noise", "noise_seed", "control_after_generate", "steps", "cfg",
        "sampler_name", "scheduler", "start_at_step", "end_at_step",
        "return_with_leftover_noise",
    ),
    "CLIPTextEncode": ("text",),
    "EmptyLatentImage": ("width", "height", "batch_size"),
    "CLIPSetLastLayer": ("stop_at_clip_layer",),
}


def build_from_ui_workflow(workflow: dict[str, Any]) -> dict[str, Any]:
    nodes = [node for node in workflow.get("nodes") or [] if isinstance(node, dict)]
    by_id = {node.get("id"): node for node in nodes}
    links: dict[int, tuple[Any, int]] = {}
    for link in workflow.get("links") or []:
        if isinstance(link, list) and len(link) >= 5:
            links[link[0]] = (link[1], link[2])

    def widgets(node: dict[str, Any]) -> dict[str, Any]:
        values = node.get("widgets_values")
        order = _WIDGET_MAP.get(str(node.get("type") or ""), ())
        if isinstance(values, list):
            return {name: values[index] for index, name in enumerate(order) if index < len(values)}
        if isinstance(values, dict):
            return dict(values)
        return {}

    def input_link(node: dict[str, Any], name: str) -> tuple[Any, int] | None:
        for entry in node.get("inputs") or []:
            if isinstance(entry, dict) and entry.get("name") == name and entry.get("link") is not None:
                return links.get(entry["link"])
        return None

    def text_behind(node_id: Any, depth: int = 0) -> str:
        node = by_id.get(node_id)
        if not isinstance(node, dict) or depth > 24:
            return ""
        values = widgets(node)
        text = values.get("text") or values.get("string")
        if isinstance(text, str) and text.strip():
            return text.strip()
        for key in ("conditioning", "positive", "negative", "text", "conditioning_1", "conditioning_2"):
            found = input_link(node, key)
            if found:
                nested = text_behind(found[0], depth + 1)
                if nested:
                    return nested
        return ""

    samplers: list[dict[str, Any]] = []
    positives: list[str] = []
    negatives: list[str] = []

    for node in nodes:
        node_type = str(node.get("type") or "")
        values = widgets(node)
        if node_type in ("KSampler", "KSamplerAdvanced"):
            sampler_name = values.get("sampler_name")
            samplers.append({
                "node": str(node.get("id")),
                "title": node.get("title") or node_type,
                "node_class": node_type,
                "steps": values.get("steps"),
                "cfg": values.get("cfg"),
                "sampler": sampler_name,
                "scheduler": values.get("scheduler"),
                "seed": values.get("seed", values.get("noise_seed")),
                "denoise": values.get("denoise"),
                "start_at_step": values.get("start_at_step"),
                "end_at_step": values.get("end_at_step"),
                "skipped": False,
            })
            positive_link = input_link(node, "positive")
            negative_link = input_link(node, "negative")
            if positive_link:
                text = text_behind(positive_link[0])
                if text and text not in positives:
                    positives.append(text)
            if negative_link:
                text = text_behind(negative_link[0])
                if text and text not in negatives:
                    negatives.append(text)

    models: dict[str, Any] = {"checkpoints": [], "unet": [], "vae": [], "clip": [], "clip_skip": None}
    loras: list[dict[str, Any]] = []
    latent: dict[str, Any] = {"width": None, "height": None, "batch": None, "node": None}

    for node in nodes:
        node_type = str(node.get("type") or "")
        values = widgets(node)
        node_id = str(node.get("id"))
        if node_type in ("CheckpointLoaderSimple", "CheckpointLoader") and values.get("ckpt_name"):
            models["checkpoints"].append({"name": _strip_ext(values["ckpt_name"]), "path": values["ckpt_name"],
                                          "node": node_id, "node_class": node_type, "title": node.get("title") or node_type})
        elif node_type == "UNETLoader" and values.get("unet_name"):
            models["unet"].append({"name": _strip_ext(values["unet_name"]), "path": values["unet_name"],
                                   "node": node_id, "node_class": node_type, "title": node.get("title") or node_type})
        elif node_type == "VAELoader" and values.get("vae_name"):
            models["vae"].append({"name": _strip_ext(values["vae_name"]), "path": values["vae_name"],
                                  "node": node_id, "node_class": node_type, "title": node.get("title") or node_type})
        elif node_type == "CLIPLoader" and values.get("clip_name"):
            models["clip"].append({"name": _strip_ext(values["clip_name"]), "path": values["clip_name"],
                                   "type": values.get("type"), "node": node_id, "node_class": node_type,
                                   "title": node.get("title") or node_type})
        elif node_type in ("LoraLoader", "LoraLoaderModelOnly") and values.get("lora_name"):
            loras.append({
                "name": _strip_ext(values["lora_name"]),
                "path": values["lora_name"],
                "strength_model": values.get("strength_model"),
                "strength_clip": values.get("strength_clip"),
                "active": True,
                "node": node_id,
                "node_class": node_type,
            })
        elif node_type == "CLIPSetLastLayer" and values.get("stop_at_clip_layer") is not None:
            try:
                models["clip_skip"] = int(abs(int(values["stop_at_clip_layer"])))
            except (TypeError, ValueError):
                pass
        elif node_type.startswith("EmptyLatent") and values.get("width"):
            latent = {"width": values.get("width"), "height": values.get("height"),
                      "batch": values.get("batch_size"), "node": node_id}

    return {
        "source": "comfy-ui",
        "positive": "\n\n".join(positives),
        "negative": "\n\n".join(negatives),
        "models": models,
        "loras": loras,
        "samplers": samplers,
        "latent": latent,
        "extras": [],
        "node_types": {},
        "node_count": len(nodes),
        "warnings": ["ui_workflow_approximate"],
    }


def _strip_ext(value: Any) -> str:
    text = str(value).replace("\\", "/").rsplit("/", 1)[-1]
    for extension in (".safetensors", ".sft", ".ckpt", ".pt", ".gguf"):
        if text.lower().endswith(extension):
            return text[: -len(extension)]
    return text
