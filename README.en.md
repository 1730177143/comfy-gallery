# comfy-gallery

A gallery for ComfyUI output. It indexes your `output` folder and opens any image into a recipe-style metadata panel: prompt, models, LoRA list with strengths, and every sampler pass.

It is a standalone page, reachable from a button in ComfyUI's toolbar:

```
http://127.0.0.1:8188/gallery
```

[简体中文](README.md)

## Why a separate pack

[ComfyUI-Lora-Manager](https://github.com/willmiao/ComfyUI-Lora-Manager) has an excellent recipe view, but an image has to be added to a recipe by hand before its metadata is visible. This pack reads the generation data ComfyUI already writes into each file, so there is nothing to add: generate, then browse.

The parsing approach follows [ComfyUI-Sidebar-Gallery](https://github.com/TokenSpender/ComfyUI-Sidebar-Gallery), reading the embedded API graph rather than a flat parameter string.

## Installation

**ComfyUI-Manager:** search for `comfy-gallery`, install, restart ComfyUI.

**Manual:** place this repository in `ComfyUI/custom_nodes/` and restart ComfyUI.

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/1730177143/comfy-gallery.git comfy-gallery
```

If the repository lives elsewhere, link it instead of copying:

```bat
cd ComfyUI\custom_nodes
mklink /J comfy-gallery D:\path\to\comfy-gallery
```

After the restart a **Gallery** button appears in ComfyUI's toolbar and opens the gallery in a new tab; `Shift+click` opens it in its own window.

The first visit scans the whole output folder; a library of several thousand images takes a minute or two. Progress shows at the top and you can browse whatever is already indexed.

## Usage

- **Sidebar**: `All images`, `Favorites`, and your folders as a tree with counts. Below that, `Base model` filters by family (Krea2 / SDXL / Illustrious and so on).
- **Toolbar**: library-wide search (file names, folders, prompts, model names, LoRA names, samplers), sort order, a `Grid` / `Waterfall` switch, and refresh.
- **Cards**: base-model badge top-left, followed by a small workflow chip when the file carries one (click it to send that workflow to ComfyUI); favourite and delete top-right; the waterfall shows a two-line prompt preview, the grid shows the file name.
- **Multi-select**: the check button in the toolbar turns card clicks into selection; the strip above the grid offers `Select all`, batch `Favorite`, batch `Delete`, and `Esc` leaves the mode.
- **Detail mode**: a three-way switch in the toolbar — `Side panel` (default), `Large view` (a modal with the image on the left and parameters on the right, arrow buttons to step through), and `Image only` (full-screen viewer, `←` / `→` to step, no panels).
- **Settings**: default layout, items per row (0 = fit to width), extra folders, whether to include video, **wheel switching in the viewer**, items per page, undo window, cache folder, rebuild index.
- **Wheel switching** is off by default. When on, the wheel in the image viewer steps to the next image (down) or the previous one (up), one image per gesture; when off, the wheel scrolls as usual.

Keys: `/` focuses search, `Esc` closes the enlarged image or the panel, arrow keys move through the grid.

## The panel

- **Generation**: positive and negative prompt, each copyable.
- **Base model**: the inferred family (Krea2, Qwen Image, Flux, Wan, Hunyuan, LTX, MiniMax, Illustrious, NoobAI, Animagine, **Anima**, Pony, SDXL, SD3, SD 1.5 / 2.1, NovelAI as `NAI`), with a note when it was inferred from a LoRA rather than the checkpoint.
- **Model**: checkpoint / UNET, VAE, CLIP with its type and clip skip.
- **LoRA**: name, weight and whether it was enabled; disabled rows are dimmed and marked off.
- **Sampler**: one card per sampling node with steps, CFG, sampler, scheduler, seed, denoise and step range. Multiple passes, or a high-noise / low-noise split, are listed separately.
- **Other parameters**: ControlNet, upscale models and factors, detectors, source images, base size.
- **Raw metadata**: the whole payload as JSON.

Values come from resolving the graph's links, so numbers produced by Seed nodes, math nodes or resolution selectors still show what actually ran. A base size derived from a resolution selector is marked with `≈`.

The footer offers copy prompt, **send to ComfyUI**, download, and move to trash.

`Send to ComfyUI` loads the file's embedded workflow onto the canvas: it opens (or reuses) a canvas tab, and the small frontend extension shipped with this pack calls `app.loadGraphData()`. The button is disabled when the file has no workflow. It replaces whatever that tab currently shows (`Ctrl+Z` undoes it).

## Supported metadata

| Source | Notes |
| --- | --- |
| ComfyUI `prompt` | The API graph written by the built-in `SaveImage` and similar nodes; the most complete reading |
| Automatic1111 `parameters` | The flat parameter string written by ComfyUI-Image-Saver and others, including `<lora:...>` tags |
| NovelAI `Comment` | The JSON NovelAI writes (prompt, uc, steps, scale, seed, sampler, size); the older `sd-metadata` chunk is accepted too |
| `workflow` only | When a file stored the editor graph but not the executed one, core nodes are read approximately and the panel says so |
| No metadata | Still listed and browsable, labelled as having no metadata |

## When the base model is wrong

Files the detector cannot place are counted under `Unknown` in the sidebar. Open one and pick a family from the dropdown in the `Base model` panel: the choice is remembered, survives a rebuild of the index, and `Restore detected` puts the automatic answer back.

## Favorites and deleting

- Favorites are stored in the pack's settings file, so they survive a browser switch and a restart. `Favorites` in the sidebar is that view.
- **Deleting has an undo window.** A delete does not touch the disk at once: the card dims with a countdown and the toolbar's undo button turns red with a count.
- That button opens the "waiting to be deleted" panel, which lists only the queued images: undo them one by one, switch on `Select` to undo a subset, or `Undo all`.
- **Timers pause while the panel is open** — the pause is enforced by the server, not faked in the browser — and resume when it closes.
- The window is configurable under Settings: 60 seconds by default, 0–600; `0` disables undo and deletes immediately.
- When the countdown ends the file moves to `.gallery-trash/<original relative path>` inside its root, where it can still be restored by hand.

## Data and privacy

The index and thumbnail cache live in ComfyUI's user directory:

```
ComfyUI/user/comfy-gallery/
├── index.db     # file index and parsed recipes
├── settings.json
└── thumbs/      # thumbnail cache
```

Everything stays on this machine; nothing is uploaded. Deleting that folder rebuilds it and never touches the images.

## Known limits

- If ComfyUI was started with `--disable-metadata`, no file carries generation data and the panel can only report that there is none.
- JPEG / WebP rely on the EXIF `UserComment` field; some save nodes do not write it, and those files show no recipe either.
- Files with only a `workflow` are read by core node widget order, so custom nodes may be missed.
- The base-model badge is a guess; a renamed checkpoint may not be recognised, in which case no badge is shown.
- The pack only indexes and reads; apart from the single-file actions above it does no batch delete, rating or tagging, and registers no nodes.
