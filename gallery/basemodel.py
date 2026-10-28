"""Infer the base-model family a recipe was made with.

LoRA Manager shows this as a short badge on each card ("ANI", "KR2"). ComfyUI
files do not record it, so it is derived from the model, CLIP type and LoRA names
already present in the recipe. An unknown family simply yields no badge.
"""

from __future__ import annotations

from typing import Any, Iterable

# Ordered most-specific first: "noobai" is an SDXL finetune, so it has to be
# tested before the generic "xl" rule.
_FAMILIES: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    ("krea2", "KR2", "Krea 2", ("krea2", "krea-2", "krea_2")),
    ("qwen", "QWEN", "Qwen Image", ("qwen_image", "qwen-image", "qwenimage")),
    ("flux", "FLUX", "Flux", ("flux",)),
    ("wan", "WAN", "Wan", ("wan2", "wan_", "wan-", "wanvideo")),
    ("hunyuan", "HY", "Hunyuan", ("hunyuan",)),
    ("minimax", "MM", "MiniMax", ("minimax",)),
    ("ltx", "LTX", "LTX", ("ltx",)),
    ("illustrious", "IL", "Illustrious", ("illustrious", "ilustrious", "illustriuos")),
    ("noobai", "NOOB", "NoobAI", ("noobai", "noob-ai", "noob_ai")),
    ("animagine", "ANG", "Animagine", ("animagine",)),
    # Anima is its own 2.9B family; keep it after Animagine, whose name
    # contains the same letters.
    ("anima", "ANIMA", "Anima", ("anima",)),
    ("pony", "PONY", "Pony", ("pony",)),
    ("sdxl", "XL", "SDXL", ("sdxl", "_xl", "xl_", "xl-", "xlv", "xlbase", "xl_refiner")),
    ("sd3", "SD3", "SD3", ("sd3", "sd_3")),
    ("sd15", "SD15", "SD 1.5", ("sd15", "sd_15", "v1-5", "v1.5", "sd1-5")),
    ("sd21", "SD21", "SD 2.1", ("sd21", "v2-1", "sd_2")),
)

LONG_LABELS = {key: long_label for key, _short, long_label, _needles in _FAMILIES}
SHORT_LABELS = {key: short for key, short, _long, _needles in _FAMILIES}

# CLIP loader types that name the family directly.
_CLIP_TYPES = {
    "krea2": "krea2",
    "qwen_image": "qwen",
    "flux": "flux",
    "wan": "wan",
    "hunyuan_video": "hunyuan",
    "ltxv": "ltx",
    "stable_diffusion": "",
    "sd3": "sd3",
}


# Needles that are too generic to trust from a LoRA folder name; they only count
# when they appear in the checkpoint / UNET / CLIP type itself.
_WEAK_NEEDLES = frozenset({"_xl", "xl_", "xl-", "xlv", "xlbase", "xl_refiner",
                           "anima_", "anima-", "v1.5", "v2-1", "sd_2", "sd_3", "wan_", "wan-"})


def _match(haystack: str, strict: bool = False) -> str:
    lowered = haystack.lower()
    for key, _short, _long, needles in _FAMILIES:
        for needle in needles:
            if strict and needle in _WEAK_NEEDLES:
                continue
            if needle in lowered:
                return key
    return ""


def _model_names(recipe: dict[str, Any]) -> Iterable[str]:
    """Strong evidence: what the loader actually loaded."""
    models = recipe.get("models") or {}
    for bucket in ("unet", "checkpoints"):
        for item in models.get(bucket) or []:
            yield str(item.get("path") or item.get("name") or "")
    for item in models.get("clip") or []:
        clip_type = str(item.get("type") or "").lower()
        mapped = _CLIP_TYPES.get(clip_type)
        if mapped:
            yield mapped


def _lora_names(recipe: dict[str, Any]) -> Iterable[str]:
    """Weak evidence: LoRA folders often encode the family in their path."""
    for lora in recipe.get("loras") or []:
        yield str(lora.get("path") or lora.get("name") or "")


def infer(recipe: dict[str, Any], allow_lora: bool = False) -> dict[str, str] | None:
    """The family, from the model names, a LoRA path, or the generator itself."""
    if str(recipe.get("source") or "") == "novelai":
        # NovelAI runs its own models; there is no checkpoint name to read.
        return {"key": "novelai", "label": "NAI", "long": "NovelAI", "source": "source"}

    """Return ``{"key", "label", "long", "source"}`` for the recipe, or None.

    ``allow_lora`` is off for the card badge: a Pony LoRA on an SDXL checkpoint
    would mislabel the image. The detail panel opts in and the answer says where
    it came from, so an inferred family is never presented as fact.
    """
    for name in _model_names(recipe):
        key = _match(name)
        if key:
            return {"key": key, "label": SHORT_LABELS.get(key, key.upper()),
                    "long": LONG_LABELS.get(key, key), "source": "model"}
    if allow_lora:
        for name in _lora_names(recipe):
            key = _match(name, strict=True)
            if key:
                return {"key": key, "label": SHORT_LABELS.get(key, key.upper()),
                        "long": LONG_LABELS.get(key, key), "source": "lora"}
    return None


def families() -> list[dict[str, str]]:
    """Every family the picker may offer, most specific first."""
    return [{"key": key, "label": short, "long": long_label}
            for key, short, long_label, _needles in _FAMILIES]


def key_of(recipe: dict[str, Any]) -> str:
    """The family stored in the index.

    Must match what the detail panel reports, or the same file would show one
    badge on the card and another in the panel. Both therefore allow the LoRA
    fallback; the panel still says when the answer came from a LoRA.
    """
    found = infer(recipe, allow_lora=True)
    return found["key"] if found else ""


def snippet_of(recipe: dict[str, Any], limit: int = 160) -> str:
    """One-line prompt preview for the card overlay."""
    text = " ".join((recipe.get("positive") or "").split())
    return text[:limit]
