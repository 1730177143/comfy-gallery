"""Parser regression tests: the cases that are easy to get subtly wrong.

Run with the ComfyUI Python: ``python tests/smoke_parser.py``
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json  # noqa: E402

from gallery.parse import build_from_a1111, build_from_prompt, build_recipe  # noqa: E402

FAILURES: list[str] = []


def check(condition: bool, label: str, detail: object = "") -> None:
    print(("  ok   " if condition else "  FAIL ") + label + (f"  [{detail}]" if not condition else ""))
    if not condition:
        FAILURES.append(label)


def case_conditioning_pair() -> None:
    prompt = {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "sdxl.safetensors"}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": "a cat on a mat", "clip": ["1", 1]}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": "blurry, ugly", "clip": ["1", 1]}},
        "4": {"class_type": "ConditioningSetArea", "inputs": {"conditioning": ["2", 0], "width": 512, "height": 512}},
        "5": {"class_type": "KSampler", "inputs": {
            "model": ["1", 0], "positive": ["4", 0], "negative": ["3", 0],
            "latent_image": ["6", 0], "seed": ["7", 0], "steps": 24, "cfg": 7.5,
            "sampler_name": "dpmpp_2m", "scheduler": "karras", "denoise": 1.0}},
        "6": {"class_type": "EmptyLatentImage", "inputs": {"width": 1024, "height": 1024, "batch_size": 1}},
        "7": {"class_type": "Seed (rgthree)", "inputs": {"seed": 123456789}},
    }
    recipe = build_from_prompt(prompt)
    check(recipe["positive"] == "a cat on a mat", "positive resolves through a conditioning wrapper", recipe["positive"])
    check(recipe["negative"] == "blurry, ugly", "negative keeps its own encoder", recipe["negative"])
    check([m["name"] for m in recipe["models"]["checkpoints"]] == ["sdxl"], "checkpoint name loses its extension")
    sampler = recipe["samplers"][0]
    check(sampler["seed"] == 123456789, "seed resolves from a linked Seed node", sampler["seed"])
    check(sampler["sampler"] == "dpmpp_2m", "sampler name read")
    check(recipe["latent"]["width"] == 1024 and not recipe["latent"]["estimated"], "latent size read literally")


def case_zeroed_negative() -> None:
    promise = {
        "1": {"class_type": "CLIPTextEncode", "inputs": {"text": "only positive"}},
        "2": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["1", 0]}},
        "3": {"class_type": "KSampler", "inputs": {
            "positive": ["1", 0], "negative": ["2", 0], "steps": 8, "cfg": 1.0,
            "sampler_name": "euler", "scheduler": "beta", "seed": 5, "denoise": 1.0}},
    }
    recipe = build_from_prompt(promise)
    check(recipe["positive"] == "only positive", "zeroed branch leaves the positive intact", recipe["positive"])
    check(recipe["negative"] == "", "ConditioningZeroOut contributes no negative text", recipe["negative"])


def case_lora_rows() -> None:
    prompt = {
        "1": {"class_type": "Power Lora Loader (rgthree)", "inputs": {
            "lora_1": {"on": True, "lora": "krea2\\active_one.safetensors", "strength": 0.4800000048828125},
            "lora_2": {"on": False, "lora": "krea2\\disabled_two.safetensors", "strength": 0.8},
            "lora_3": {"on": False, "lora": "None", "strength": 0},
        }},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": "tag <lora:inline_one:0.6> more"}},
    }
    recipe = build_from_prompt(prompt)
    names = {lora["name"]: lora for lora in recipe["loras"]}
    check("active_one" in names, "enabled loader row collected", sorted(names))
    check(names.get("active_one", {}).get("active") is True, "enabled row marked active")
    check(names.get("active_one", {}).get("strength_model") == 0.48, "float32 noise rounded to the widget value",
          names.get("active_one", {}).get("strength_model"))
    check("disabled_two" in names and names["disabled_two"]["active"] is False, "disabled row kept but flagged")
    check("None" not in names, "empty loader row dropped")
    check("inline_one" in names, "prompt tag LoRA collected")


def case_a1111() -> None:
    text = (
        "a girl, <lora:style_a:0.4>, masterpiece\n"
        "Negative prompt: lowres, bad hands\n"
        "Steps: 50, Sampler: Euler a, CFG scale: 5, Seed: 785260828117868, "
        "Size: 768x1536, Model: chenkinNoobXLCKXL_v02, Clip skip: 2"
    )
    recipe = build_from_a1111(text)
    check(recipe["positive"].startswith("a girl"), "a1111 positive parsed", recipe["positive"][:30])
    check(recipe["negative"] == "lowres, bad hands", "a1111 negative parsed", recipe["negative"])
    check(recipe["models"]["checkpoints"][0]["name"] == "chenkinNoobXLCKXL_v02", "a1111 model parsed")
    check(recipe["models"]["clip_skip"] == 2, "a1111 clip skip parsed")
    sampler = recipe["samplers"][0]
    check(sampler["steps"] == 50 and sampler["cfg"] == 5, "a1111 sampler numbers parsed", sampler)
    check(sampler["seed"] == 785260828117868, "a1111 seed parsed", sampler["seed"])
    check(recipe["latent"]["width"] == 768, "a1111 size parsed", recipe["latent"])
    check([lora["name"] for lora in recipe["loras"]] == ["style_a"], "a1111 lora tag parsed")


def case_novelai() -> None:
    comment = {
        "prompt": "1girl, solo, masterpiece, best quality",
        "uc": "lowres, bad anatomy, worst quality",
        "steps": 28,
        "scale": 5.5,
        "seed": 1234567890,
        "sampler": "k_euler_ancestral",
        "noise_schedule": "karras",
        "width": 832,
        "height": 1216,
        "n_samples": 1,
        "sm": False,
        "sm_dyn": False,
    }
    recipe = build_recipe({
        "comment": json.dumps(comment),
        "description": "1girl, solo, masterpiece, best quality",
    })
    check(recipe["source"] == "novelai", "novelai source detected", recipe["source"])
    check(recipe["positive"].startswith("1girl, solo"), "novelai prompt read", recipe["positive"][:30])
    check(recipe["negative"].startswith("lowres"), "novelai uc becomes the negative", recipe["negative"][:24])
    sampler = recipe["samplers"][0]
    check(sampler["steps"] == 28 and sampler["cfg"] == 5.5, "novelai steps/scale mapped", sampler)
    check(sampler["seed"] == 1234567890, "novelai seed read", sampler["seed"])
    check("k_euler_ancestral" in (sampler["sampler"] or ""), "novelai sampler read", sampler["sampler"])
    check(recipe["latent"]["width"] == 832 and recipe["latent"]["height"] == 1216,
          "novelai size read", recipe["latent"])

    # A Comment chunk that is not NovelAI must not be mistaken for one.
    other = build_recipe({"comment": json.dumps({"note": "hello"})})
    check(other["source"] != "novelai", "non-novelai comment ignored", other["source"])


for case in (case_conditioning_pair, case_zeroed_negative, case_lora_rows, case_a1111, case_novelai):
    print(f"{case.__name__}:")
    case()

print("\nFAILURES:", FAILURES if FAILURES else "none")
sys.exit(1 if FAILURES else 0)
