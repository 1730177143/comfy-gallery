/* The recipe panel: how one file was made, plus the actions that apply to it. */

import { el, clear, chip, svgIcon, copyText, toast, formatBytes, formatDate, formatNumber } from "./dom.js";
import { t } from "./i18n.js";
import { fetchWorkflow, exportWorkflow, fileUrl } from "./api.js";

export function renderDetailEmpty(container) {
  clear(container);
  container.removeAttribute("data-open");
  container.append(
    el("div", { class: "detail-empty" },
      svgIcon("image"),
      el("p", { text: t("detail.empty") }),
    ),
  );
}

function panel(title, ...children) {
  return el("section", { class: "panel" },
    el("div", { class: "panel-head" }, el("h3", { text: title })),
    ...children,
  );
}

function copyButton(getText) {
  return el("button", {
    class: "mini",
    type: "button",
    title: t("action.copy"),
    "aria-label": t("action.copy"),
    onclick: async () => {
      const text = await getText();
      if (!text) {
        toast(t("toast.noWorkflow"));
        return;
      }
      toast((await copyText(text)) ? t("toast.copied") : t("toast.copyFailed"));
    },
  }, svgIcon("copy"));
}

function promptField(label, text, kind) {
  return el("div", { class: "field" },
    el("div", { class: "field-head" },
      el("span", { class: "field-label", text: label }),
      text ? copyButton(() => text) : null,
    ),
    text
      ? el("p", { class: "prompt-text", dataset: { kind }, text })
      : el("p", { class: "prompt-empty", text: t("field.empty") }),
  );
}

function kvRow(label, value) {
  if (value === null || value === undefined || value === "") return null;
  return el("li", {}, el("span", { class: "k", text: label }), el("span", { class: "v", text: value }));
}

function modelPanel(models) {
  const rows = [];
  const push = (label, list, withType) => {
    for (const item of list || []) {
      const suffix = withType && item.type ? ` (${item.type})` : "";
      const dtype = item.dtype ? ` · ${item.dtype}` : "";
      rows.push(kvRow(label, `${item.name}${suffix}${dtype}`));
    }
  };
  push(t("label.checkpoint"), models.checkpoints);
  push(t("label.unet"), models.unet);
  push(t("label.vae"), models.vae);
  push(t("label.clip"), models.clip, true);
  if (models.clip_skip) rows.push(kvRow(t("label.clipSkip"), String(models.clip_skip)));

  const kept = rows.filter(Boolean);
  if (!kept.length) return null;
  return panel(t("panel.model"), el("ul", { class: "kv" }, ...kept));
}

function loraPanel(loras) {
  if (!loras || !loras.length) return null;
  const items = loras.map((lora) => {
    const weight = lora.strength_model;
    const weightText = weight === null || weight === undefined ? "" : String(weight);
    return el("li", { class: "lora", dataset: { active: String(lora.active !== false) } },
      el("span", { class: "lora-dot" }),
      el("span", { class: "lora-name", text: lora.name, title: lora.path || lora.name }),
      weightText
        ? el("span", { class: "lora-weight", dataset: { zero: String(Number(weight) === 0) }, text: weightText })
        : null,
      lora.active === false ? el("span", { class: "lora-off", text: "off" }) : null,
    );
  });

  const head = el("div", { class: "panel-head" },
    el("h3", { text: t("panel.lora") }),
    el("span", { class: "panel-count", text: String(loras.length) }),
  );
  return el("section", { class: "panel" }, head, el("ul", { class: "lora-list" }, ...items));
}

function stat(label, value, groupDigits = true) {
  if (value === null || value === undefined || value === "") return null;
  const text = groupDigits ? formatNumber(value) : String(value);
  // A long value (a seed, a wide number) should not wrap inside a third of the
  // card, so it takes two columns instead.
  const wide = text.length > 9 ? " stat-wide" : "";
  return el("div", { class: `stat${wide}` },
    el("span", { class: "stat-k", text: label }),
    el("span", { class: "stat-v", text }),
  );
}

function samplerPanel(samplers) {
  if (!samplers || !samplers.length) return null;
  const passes = samplers.map((pass) => {
    const stats = [
      stat(t("label.steps"), pass.steps),
      stat(t("label.cfg"), pass.cfg),
      stat(t("label.sampler"), pass.sampler),
      stat(t("label.scheduler"), pass.scheduler),
      stat(t("label.seed"), pass.seed, false),
      stat(t("label.denoise"), pass.denoise),
      pass.start_at_step !== null && pass.end_at_step !== null
        ? stat(t("label.steps_range"), `${pass.start_at_step}–${pass.end_at_step}`)
        : null,
    ].filter(Boolean);

    return el("div", { class: "pass" },
      el("div", { class: "pass-title" },
        el("span", { text: pass.title || pass.node_class }),
        pass.skipped ? chip("denoise 0", "warn") : null,
      ),
      stats.length ? el("div", { class: "stat-grid" }, ...stats) : null,
    );
  });

  return panel(t("panel.sampler"), ...passes);
}

function otherPanel(recipe) {
  const rows = [];
  for (const extra of recipe.extras || []) {
    rows.push(el("div", { class: "extra" },
      el("span", { class: "extra-k", text: extra.label }),
      el("span", { class: "extra-v", text: extra.value }),
    ));
  }
  const latent = recipe.latent || {};
  if (latent.width && latent.height) {
    rows.push(el("div", { class: "extra" },
      el("span", { class: "extra-k", text: t("label.base_size") }),
      el("span", { class: "extra-v", text: `${latent.width}×${latent.height}${latent.estimated ? " ≈" : ""}` }),
    ));
  }
  if (latent.batch && Number(latent.batch) > 1) {
    rows.push(el("div", { class: "extra" },
      el("span", { class: "extra-k", text: t("label.batch") }),
      el("span", { class: "extra-v", text: String(latent.batch) }),
    ));
  }
  if (!rows.length) return null;
  return panel(t("panel.other"), ...rows);
}

function baseModelRow(payload, handlers) {
  const families = payload.families || [];
  const current = payload.base_model;
  const manual = payload.base_source === "manual";
  const detected = payload.detected || "";

  const line = el("div", { class: "base-line" },
    current
      ? el("span", {
        class: "base-badge",
        dataset: { base: current.key },
        text: current.label,
      })
      : el("span", { class: "base-badge", dataset: { base: "" }, text: t("base.unknown") }),
    el("span", {
      class: "base-long",
      text: current
        ? `${current.long}${current.source === "lora" ? ` · ${t("base.fromLora")}` : ""}`
        : t("base.unknownHint"),
    }),
  );

  if (!families.length) return panel(t("label.baseModel"), line);

  const select = el("select", {
    class: "base-select", name: "base-model", "aria-label": t("label.baseModel"),
  },
    el("option", { value: "", text: t("base.unknown") }),
    ...families.map((family) => el("option", {
      value: family.key,
      text: `${family.label} · ${family.long}`,
    })),
  );
  select.value = current?.key || "";
  select.addEventListener("change", () => {
    if (handlers.onBaseChange) handlers.onBaseChange(select.value);
  });

  const controls = el("div", { class: "base-controls" }, select);
  if (manual && detected) {
    const reset = el("button", {
      class: "btn", type: "button", text: t("base.reset"),
      title: t("base.resetHint", { base: detected.toUpperCase() }),
    });
    reset.addEventListener("click", () => handlers.onBaseChange?.(""));
    controls.append(reset);
  }

  return panel(t("label.baseModel"), line, controls);
}

function mediaBlock(entry, payload, onZoom) {
  const kind = entry.kind === "video" ? "video" : "image";
  const media = kind === "video"
    ? el("video", { src: fileUrl(entry.id), controls: "controls", preload: "metadata" })
    : el("img", { src: payload.thumb_url, alt: entry.name, decoding: "async" });

  const block = el("div", { class: "detail-media", dataset: { kind } }, media);
  if (kind === "image") {
    block.append(el("span", { class: "detail-media-zoom", text: t("action.zoom") }));
    block.addEventListener("click", () => onZoom(entry.id));
  }
  return block;
}

function actionsRow(entry, recipe, payload, handlers) {
  const copyPrompt = el("button", {
    class: "btn",
    type: "button",
    dataset: { variant: "primary" },
    onclick: async () => {
      const text = [recipe.positive, recipe.negative ? `\nNegative prompt: ${recipe.negative}` : ""]
        .filter(Boolean).join("\n");
      if (!text.trim()) {
        toast(t("toast.noWorkflow"));
        return;
      }
      toast((await copyText(text)) ? t("toast.copied") : t("toast.copyFailed"));
    },
  }, svgIcon("copy"), el("span", { text: t("action.copyPrompt") }));

  const copyWorkflow = el("button", {
    class: "btn",
    type: "button",
    onclick: async () => {
      try {
        const data = await fetchWorkflow(entry.id);
        await copyText(JSON.stringify(data.workflow || data.prompt, null, 2));
        toast(t("toast.copied"));
      } catch {
        toast(t("toast.noWorkflow"));
      }
    },
  }, svgIcon("copy"), el("span", { text: t("action.copyWorkflow") }));

  const saveWorkflow = el("button", {
    class: "btn",
    type: "button",
    onclick: async () => {
      try {
        const result = await exportWorkflow(entry.id);
        toast(t("toast.saved", { name: result.name }));
      } catch {
        toast(t("toast.noWorkflow"));
      }
    },
  }, svgIcon("save"), el("span", { text: t("action.saveWorkflow") }));

  const download = el("a", {
    class: "btn",
    href: payload.file_url || fileUrl(entry.id),
    download: entry.name,
  }, svgIcon("download"), el("span", { text: t("action.download") }));

  return el("footer", { class: "detail-actions" },
    copyPrompt, copyWorkflow, saveWorkflow, download,
    handlers.onTrash ? trashButton(entry, handlers) : null,
  );
}

/** Delete needs a second click, so a stray press cannot move a file. */
function trashButton(entry, handlers) {
  let armed = false;
  const button = el("button", {
    class: "btn",
    type: "button",
    dataset: { variant: "danger" },
    title: t("action.delete"),
  }, svgIcon("trash"), el("span", { text: t("action.delete") }));

  button.addEventListener("click", () => {
    if (!armed) {
      armed = true;
      button.dataset.armed = "true";
      button.lastChild.textContent = t("action.deleteConfirm");
      setTimeout(() => {
        if (!armed) return;
        armed = false;
        delete button.dataset.armed;
        button.lastChild.textContent = t("action.delete");
      }, 4000);
      return;
    }
    armed = false;
    handlers.onTrash(entry.id);
  });
  return button;
}

function starButton(entry, payload, handlers) {
  const pressed = payload.favorite ? "true" : "false";
  const button = el("button", {
    class: "btn",
    type: "button",
    "aria-pressed": pressed,
    dataset: { favorite: pressed },
  }, svgIcon("star"), el("span", { text: t("action.favorite") }));

  button.addEventListener("click", () => {
    const next = button.getAttribute("aria-pressed") !== "true";
    button.setAttribute("aria-pressed", next ? "true" : "false");
    button.dataset.favorite = next ? "true" : "false";
    handlers.onFavorite(entry.id, next);
  });
  return button;
}

export function renderDetail(container, payload, handlers = {}) {
  const { entry, recipe } = payload;
  clear(container);
  container.setAttribute("data-open", "true");

  const metaRow = el("div", { class: "meta-row" },
    chip(t(`source.${recipe.source || "none"}`), recipe.source === "none" ? "warn" : "model"),
    entry.width ? chip(`${entry.width}×${entry.height}`, "sampler", "chip-mono") : null,
    chip(formatBytes(entry.size), "muted", "chip-mono"),
    chip(formatDate(entry.mtime), "muted"),
  );

  const headActions = el("div", { class: "detail-head-actions" },
    payload.base_model
      ? el("span", {
        class: "base-badge",
        dataset: { base: payload.base_model.key },
        title: payload.base_model.long,
        text: payload.base_model.label,
      })
      : null,
    handlers.onFavorite ? starButton(entry, payload, handlers) : null,
    handlers.onClose
      ? el("button", {
        class: "mini detail-close",
        type: "button",
        title: t("action.close"),
        "aria-label": t("action.close"),
        onclick: handlers.onClose,
      }, el("span", { "aria-hidden": "true", text: "×" }))
      : null,
  );

  // Two blocks so the same markup works as a side column (stacked) and as a
  // modal (image on the left, parameters on the right).
  const head = el("div", { class: "detail-head" },
    mediaBlock(entry, payload, handlers.onZoom || (() => {})),
    el("div", { class: "detail-title" },
      el("h2", { class: "file-name", text: entry.name }),
      metaRow,
      headActions,
    ),
  );
  const panels = el("div", { class: "detail-panels" });

  const hasRecipe = recipe.source && recipe.source !== "none";
  if (hasRecipe) {
    panels.append(panel(t("panel.generation"),
      promptField(t("field.prompt"), recipe.positive || "", "positive"),
      promptField(t("field.negative"), recipe.negative || "", "negative"),
    ));
    const base = baseModelRow(payload, handlers);
    if (base) panels.append(base);
    for (const section of [
      modelPanel(recipe.models || {}),
      loraPanel(recipe.loras),
      samplerPanel(recipe.samplers),
      otherPanel(recipe),
    ]) {
      if (section) panels.append(section);
    }
  } else {
    const base = baseModelRow(payload, handlers);
    if (base) panels.append(base);
    panels.append(panel(t("source.none"), promptField(t("field.prompt"), "", "positive")));
  }

  panels.append(actionsRow(entry, recipe, payload, handlers));

  panels.append(el("details", { class: "raw" },
    el("summary", { text: t("raw.summary") }),
    el("pre", { text: JSON.stringify({ entry, base_model: payload.base_model, recipe }, null, 2) }),
  ));

  const scroll = el("div", { class: "detail-scroll" }, head, panels);
  container.append(scroll);
  const scroller = container.querySelector(".detail-scroll");
  if (scroller) scroller.scrollTop = 0;
}
