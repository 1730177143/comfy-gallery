"""Turn a ComfyUI API prompt into the structured recipe the gallery renders.

The shape produced here is deliberately close to a LoRA Manager "recipe": the
prompt pair, the loaders, the LoRA list with its strengths, and one card per
sampler pass. Values are resolved through ``PromptGraph`` so a seed or a width
that came out of another node reports what actually ran rather than a link.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from .graph import PromptGraph, as_number, as_text
from .lora_tags import LORA_TAG_RE, clean_lora_name

_LORA_FLAT_KEY_RE = re.compile(r"lora_name(?:_(\d+))?$")

_EMPTY_MODELS = {"checkpoints": [], "unet": [], "vae": [], "clip": [], "clip_skip": None}

# Sampler inputs whose presence marks a node as a real sampling pass rather than
# a selector or a helper that merely has "sampler" in its class name.
_PASS_INPUTS = (
    "steps",
    "cfg",
    "sampler_name",
    "noise_seed",
    "seed",
    "denoise",
    "start_at_step",
    "guider",
)


def _clean_model_name(value: Any) -> str:
    text = as_text(value)
    if not text:
        return ""
    base = text.replace("\\", "/").rsplit("/", 1)[-1]
    for extension in (".safetensors", ".sft", ".ckpt", ".pt", ".gguf", ".bin"):
        if base.lower().endswith(extension):
            base = base[: -len(extension)]
            break
    return base.strip()


# -- models ---------------------------------------------------------------


def _collect_models(graph: PromptGraph) -> dict[str, Any]:
    models = {key: list(value) if isinstance(value, list) else value for key, value in _EMPTY_MODELS.items()}
    clip_types: list[str] = []

    for node_id, node in graph.iter_nodes():
        class_name = str(node.get("class_type") or "")
        low = class_name.lower()
        inputs = node.get("inputs") or {}
        title = graph.title_of(node_id)

        def add(bucket: str, raw: Any, extra: dict[str, Any] | None = None) -> None:
            name = _clean_model_name(raw)
            if not name:
                return
            record = {"name": name, "path": as_text(raw), "node": node_id,
                      "node_class": class_name, "title": title}
            if extra:
                record.update(extra)
            if not any(item["name"] == name for item in models[bucket]):
                models[bucket].append(record)

        for key, value in inputs.items():
            low_key = key.lower()
            raw = value if isinstance(value, str) else graph.resolve(value)
            if low_key in ("ckpt_name", "checkpoint"):
                add("checkpoints", raw, {"dtype": as_text(inputs.get("weight_dtype")) or None})
            elif low_key == "unet_name":
                add("unet", raw, {"dtype": as_text(inputs.get("weight_dtype")) or None})
            elif low_key == "vae_name":
                add("vae", raw)
            elif low_key in ("clip_name", "clip_name1", "clip_name2", "clip_name3"):
                add("clip", raw)
                clip_type = inputs.get("type") or inputs.get("clip_type")
                if clip_type and isinstance(clip_type, str) and clip_type not in clip_types:
                    clip_types.append(clip_type)

        if "clipsetlastlayer" in low:
            stop_layer = as_number(graph.resolve(inputs.get("stop_at_clip_layer")))
            if stop_layer is not None and models["clip_skip"] is None:
                models["clip_skip"] = int(abs(stop_layer))

    if clip_types:
        for record in models["clip"]:
            record.setdefault("type", clip_types[0])
    return models


# -- loras ----------------------------------------------------------------


def _collect_loras(graph: PromptGraph) -> list[dict[str, Any]]:
    loras: list[dict[str, Any]] = []
    index: dict[str, dict[str, Any]] = {}

    def add(raw_name: Any, strength_model: Any, strength_clip: Any, active: bool,
            node_id: str, class_name: str) -> None:
        display = clean_lora_name(raw_name)
        if not display or display.lower() in ("none", "null"):
            return
        key = display.lower()
        model_strength = _round_weight(as_number(strength_model))
        clip_strength = _round_weight(as_number(strength_clip))
        record = index.get(key)
        if record is None:
            record = {
                "name": display,
                "path": as_text(raw_name),
                "strength_model": model_strength,
                "strength_clip": clip_strength,
                "active": bool(active),
                "node": node_id,
                "node_class": class_name,
            }
            index[key] = record
            loras.append(record)
            return
        # The same file can be loaded in several places (e.g. a high/low noise
        # pair). Keep one entry and let an enabled loader define its strengths.
        if active and (not record["active"] or record["strength_model"] is None):
            record["active"] = True
            record["node"] = node_id
            record["node_class"] = class_name
            if model_strength is not None:
                record["strength_model"] = model_strength
            if clip_strength is not None:
                record["strength_clip"] = clip_strength

    for node_id, node in graph.iter_nodes():
        class_name = str(node.get("class_type") or "")
        inputs = node.get("inputs") or {}

        # Style A: flat widget keys, "lora_name" and "lora_name_2" families.
        for key, value in inputs.items():
            low_key = key.lower()
            if not _LORA_FLAT_KEY_RE.fullmatch(low_key):
                continue
            suffix = low_key[len("lora_name"):]
            raw = value if isinstance(value, str) else graph.resolve(value)
            strength_model = inputs.get(f"strength_model{suffix}")
            if strength_model is None:
                strength_model = inputs.get(f"strength{suffix}")
            if strength_model is None:
                strength_model = inputs.get("strength_model", inputs.get("strength"))
            strength_clip = inputs.get(f"strength_clip{suffix}", inputs.get("strength_clip"))
            add(raw, strength_model, strength_clip, True, node_id, class_name)

        # Style B: one dict per row, as rgthree's Power Lora Loader and most
        # stacker nodes serialize their rows.
        for row in _iter_lora_rows(inputs):
            raw = row.get("lora") or row.get("lora_name") or row.get("name")
            active = row.get("on", row.get("active", row.get("enabled", True)))
            strength_model = row.get("strength", row.get("strength_model", row.get("weight")))
            strength_clip = row.get("strengthTwo", row.get("strength_clip"))
            add(raw, strength_model, strength_clip, bool(active), node_id, class_name)

        # Style C: "<lora:name:weight>" written into a text widget.
        for value in inputs.values():
            if isinstance(value, str) and "<lora:" in value.lower():
                for match in LORA_TAG_RE.finditer(value):
                    weight = match.group(2) or match.group(3) or 1.0
                    add(match.group(1), weight, match.group(3) or weight, True, node_id, class_name)

    return loras


def _iter_lora_rows(inputs: dict[str, Any]):
    for value in inputs.values():
        if isinstance(value, dict):
            if any(key in value for key in ("lora", "lora_name")):
                yield value
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict) and any(key in item for key in ("lora", "lora_name")):
                    yield item


def _round_weight(value: float | int | None) -> float | int | None:
    """Loader widgets round-trip through float32: 0.48 becomes 0.4800048828125001."""
    return round(value, 3) if isinstance(value, float) else value


# -- samplers -------------------------------------------------------------


def _collect_samplers(graph: PromptGraph) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    passes: list[dict[str, Any]] = []
    positives: list[str] = []
    negatives: list[str] = []

    for node_id, node in graph.iter_nodes():
        class_name = str(node.get("class_type") or "")
        low = class_name.lower()
        if "sampler" not in low or "select" in low:
            continue
        inputs = node.get("inputs") or {}
        if not any(key in inputs for key in _PASS_INPUTS):
            continue

        positive_link = inputs.get("positive")
        negative_link = inputs.get("negative")
        guider = inputs.get("guider")
        if guider is not None and graph.is_link(guider):
            guider_inputs = graph.inputs_of(str(guider[0]))
            positive_link = positive_link if positive_link is not None else guider_inputs.get("positive")
            negative_link = negative_link if negative_link is not None else guider_inputs.get("negative")

        sampler_name = graph.resolve(inputs.get("sampler_name"), ("sampler_name", "value"))
        if not sampler_name and "sampler" in inputs:
            sampler_name = graph.resolve(inputs["sampler"], ("sampler_name", "value"))
        scheduler = graph.resolve(inputs.get("scheduler"), ("scheduler", "value"))
        if not scheduler and "sigmas" in inputs:
            scheduler = graph.resolve(inputs["sigmas"], ("scheduler", "value"))

        seed_source = inputs.get("noise_seed", inputs.get("seed"))
        if seed_source is None:
            seed_source = inputs.get("noise")

        denoise = graph.resolve_number(inputs.get("denoise"))
        start_at = graph.resolve_number(inputs.get("start_at_step"))
        end_at = graph.resolve_number(inputs.get("end_at_step"))

        passes.append({
            "node": node_id,
            "title": graph.title_of(node_id),
            "node_class": class_name,
            "steps": graph.resolve_number(inputs.get("steps"), ("steps", "value")),
            "cfg": graph.resolve_number(inputs.get("cfg"), ("cfg", "value")),
            "sampler": as_text(sampler_name) or None,
            "scheduler": as_text(scheduler) or None,
            "seed": graph.resolve_number(seed_source, ("noise_seed", "seed", "value")),
            "denoise": denoise,
            "start_at_step": start_at,
            "end_at_step": end_at,
            "skipped": denoise == 0,
        })

        if positive_link is not None:
            for text in graph.collect_texts(positive_link):
                if text not in positives:
                    positives.append(text)
        if negative_link is not None:
            for text in graph.collect_texts(negative_link):
                if text not in negatives:
                    negatives.append(text)

    return passes, positives, negatives


def _fallback_texts(graph: PromptGraph) -> tuple[list[str], list[str]]:
    """Split encoder texts when no sampler exposed a conditioning link."""
    texts: list[str] = []
    for node_id, node in graph.iter_nodes():
        text = graph.direct_text(node)
        if text and text not in texts:
            texts.append(text)
    if len(texts) >= 2:
        return [texts[0]], texts[1:]
    return texts, []


# -- latent and extras ----------------------------------------------------


def _selector_resolution(graph: PromptGraph, node_id: str) -> tuple[int | None, int | None]:
    """Derive width/height from an aspect-ratio + megapixel selector node.

    Packages such as ResolutionSelector output computed sizes, so no widget holds
    the final numbers and the estimate is the closest the graph can offer.
    """
    inputs = graph.inputs_of(node_id)
    ratio = inputs.get("aspect_ratio")
    if not isinstance(ratio, str):
        return None, None
    match = re.match(r"\s*(\d+)\s*[:x/×]\s*(\d+)", ratio)
    if not match:
        return None, None
    ratio_w, ratio_h = int(match.group(1)), int(match.group(2))
    megapixels = as_number(graph.resolve(inputs.get("megapixels"))) or 1
    multiple = as_number(graph.resolve(inputs.get("multiple"))) or 1
    if ratio_w <= 0 or ratio_h <= 0 or megapixels <= 0:
        return None, None
    import math  # noqa: PLC0415 - only needed on this path

    total = float(megapixels) * 1_000_000
    width = math.sqrt(total * ratio_w / ratio_h)
    height = math.sqrt(total * ratio_h / ratio_w)
    step = max(1, int(multiple))
    return (max(step, int(round(width / step)) * step),
            max(step, int(round(height / step)) * step))


def _collect_latent(graph: PromptGraph) -> dict[str, Any]:
    for node_id, node in graph.iter_nodes():
        low = str(node.get("class_type") or "").lower()
        inputs = node.get("inputs") or {}
        if "latent" not in low or "width" not in inputs or "height" not in inputs:
            continue
        width = graph.resolve_number(inputs.get("width"), ("width",))
        height = graph.resolve_number(inputs.get("height"), ("height",))
        estimated = False
        if not width or not height:
            for key in ("width", "height"):
                link = inputs.get(key)
                if not graph.is_link(link):
                    continue
                computed_w, computed_h = _selector_resolution(graph, str(link[0]))
                if computed_w and computed_h:
                    width, height, estimated = computed_w, computed_h, True
                    break
        if not width or not height:
            continue
        return {
            "width": int(width),
            "height": int(height),
            "batch": graph.resolve_number(inputs.get("batch_size")),
            "node": node_id,
            "estimated": estimated,
        }
    return {"width": None, "height": None, "batch": None, "node": None, "estimated": False}


def _collect_extras(graph: PromptGraph) -> list[dict[str, Any]]:
    extras: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def push(kind: str, label: str, value: Any, node_id: str, class_name: str) -> None:
        text = as_text(value)
        if not text or (kind, text) in seen:
            return
        seen.add((kind, text))
        extras.append({
            "kind": kind,
            "label": label,
            "value": text,
            "node": node_id,
            "node_class": class_name,
        })

    for node_id, node in graph.iter_nodes():
        class_name = str(node.get("class_type") or "")
        low = class_name.lower()
        inputs = node.get("inputs") or {}

        if "loadimage" in low:
            for key in ("image", "path"):
                if isinstance(inputs.get(key), str):
                    push("input_image", "Source image", inputs[key], node_id, class_name)
                    break
        if "loadvideo" in low:
            for key in ("video", "file", "video_path"):
                if isinstance(inputs.get(key), str):
                    push("input_video", "Source video", inputs[key], node_id, class_name)
                    break
        if isinstance(inputs.get("control_net_name"), str):
            push("controlnet", "ControlNet", inputs["control_net_name"], node_id, class_name)
        if "upscalemodelloader" in low or ("upscale" in low and isinstance(inputs.get("model_name"), str)):
            push("upscale_model", "Upscale model", inputs.get("model_name"), node_id, class_name)
        if "ultralytics" in low or "detectorprovider" in low:
            name = inputs.get("model_name") or inputs.get("bbox_detector") or inputs.get("segm_detector")
            if isinstance(name, str):
                push("detector", "Detector", name, node_id, class_name)
        if "ipadapter" in low:
            name = inputs.get("ipadapter_file") or inputs.get("ipadapter_name") or inputs.get("image")
            if isinstance(name, str):
                push("ipadapter", "IP-Adapter", name, node_id, class_name)
        if "clipvisionloader" in low or "clipvision" in low:
            name = inputs.get("clip_name") or inputs.get("clipvision_file")
            if isinstance(name, str):
                push("clip_vision", "CLIP Vision", name, node_id, class_name)
        scale = inputs.get("upscale_by", inputs.get("scale_by"))
        if scale is not None:
            push("scale", "Upscale factor", graph.resolve(scale, ("upscale_by", "scale_by", "value")), node_id, class_name)
        batch = inputs.get("amount") if "batch" in low else None
        if batch is not None:
            push("batch", "Batch count", graph.resolve(batch), node_id, class_name)

    return extras


# -- entry point ----------------------------------------------------------


def build_from_prompt(prompt: dict[str, Any]) -> dict[str, Any]:
    """Build the recipe dictionary for one API-format prompt."""
    graph = PromptGraph(prompt)
    models = _collect_models(graph)
    loras = _collect_loras(graph)
    samplers, positives, negatives = _collect_samplers(graph)
    latent = _collect_latent(graph)
    extras = _collect_extras(graph)

    if not positives and not negatives:
        positives, negatives = _fallback_texts(graph)

    node_types = Counter(str(node.get("class_type") or "?") for node in graph.nodes.values())
    warnings: list[str] = []
    if not samplers:
        warnings.append("no_sampler")
    if not models["checkpoints"] and not models["unet"]:
        warnings.append("no_model")
    if not positives:
        warnings.append("no_prompt")

    return {
        "source": "comfy",
        "positive": "\n\n".join(positives),
        "negative": "\n\n".join(negatives),
        "models": models,
        "loras": loras,
        "samplers": [item for item in samplers if not item["skipped"]] or samplers,
        "latent": latent,
        "extras": extras,
        "node_types": dict(node_types.most_common(40)),
        "node_count": len(graph.nodes),
        "warnings": warnings,
    }


def build_search_blob(recipe: dict[str, Any], name: str, folder: str) -> str:
    """Lowercased haystack for the grid's search box."""
    parts: list[str] = [name, folder]
    parts.append(recipe.get("positive") or "")
    parts.append(recipe.get("negative") or "")
    for lora in recipe.get("loras") or []:
        parts.append(str(lora.get("name") or ""))
    for bucket in ("checkpoints", "unet", "vae", "clip"):
        for model in (recipe.get("models") or {}).get(bucket) or []:
            parts.append(str(model.get("name") or ""))
    for sampler in recipe.get("samplers") or []:
        parts.append(str(sampler.get("sampler") or ""))
        parts.append(str(sampler.get("scheduler") or ""))
    for extra in recipe.get("extras") or []:
        parts.append(str(extra.get("value") or ""))
    return " ".join(part for part in parts if part).lower()
