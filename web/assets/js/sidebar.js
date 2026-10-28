/* Sidebar rendering: folder tree, favorites entry and base-model filters. */

import { el, clear, svgIcon, formatNumber } from "./dom.js";
import { t } from "./i18n.js";

export const BASE_LABEL = {
  novelai: "NAI", krea2: "KR2", flux: "FLUX", sdxl: "XL", illustrious: "IL", noobai: "NOOB",
  animagine: "ANG", pony: "PONY", qwen: "QWEN", wan: "WAN", hunyuan: "HY",
  ltx: "LTX", minimax: "MM", sd15: "SD15", sd3: "SD3", sd21: "SD21",
};

function navButton({ icon, label, count, active, indent, onClick }) {
  const button = el("button", {
    class: "nav-item",
    type: "button",
    "aria-current": active ? "true" : "false",
    style: indent ? `padding-left:${8 + indent * 12}px` : null,
  },
  svgIcon(icon),
  el("span", { class: "nav-name", text: label }),
  el("span", { class: "nav-count", text: count ? formatNumber(count) : "" }));
  button.addEventListener("click", onClick);
  return button;
}

/**
 * ``state`` is read for the active highlight only; the caller owns it and reacts
 * to ``onSelect`` with the filter patch to apply.
 */
export function renderFolders(navEl, { folders, state, favoritesCount, onSelect }) {
  clear(navEl);

  navEl.append(navButton({
    icon: "all",
    label: t("sidebar.all"),
    count: folders.reduce((sum, item) => sum + item.count, 0),
    active: !state.folder && !state.root && !state.favOnly,
    onClick: () => onSelect({ folder: "", root: "", favOnly: false }),
  }));

  navEl.append(navButton({
    icon: "star",
    label: t("sidebar.favorites"),
    count: favoritesCount,
    active: state.favOnly,
    onClick: () => onSelect({ folder: "", root: "", favOnly: !state.favOnly }),
  }));

  const nested = folders.filter((item) => item.folder);
  if (!nested.length) {
    navEl.append(el("p", { class: "root-empty", text: t("sidebar.empty") }));
    return;
  }

  const multipleRoots = new Set(nested.map((item) => item.root_id)).size > 1;
  for (const entry of nested) {
    const depth = entry.folder.split("/").length;
    const label = entry.folder.split("/").pop();
    navEl.append(navButton({
      icon: "folder",
      label: multipleRoots && depth === 1 ? `${label} · ${entry.root_label}` : label,
      count: entry.count,
      indent: depth,
      active: !state.favOnly && state.folder === entry.folder && state.root === entry.root_id,
      onClick: () => onSelect({ folder: entry.folder, root: entry.root_id, favOnly: false }),
    }));
  }
}

export function renderBases(listEl, { bases, selected, onSelect }) {
  clear(listEl);

  const all = el("button", {
    class: "base-chip",
    type: "button",
    "aria-pressed": selected ? "false" : "true",
    dataset: { base: "" },
    style: "--badge-tone: var(--tone-muted)",
  }, el("span", { text: t("base.all") }));
  all.addEventListener("click", () => onSelect(""));
  listEl.append(all);

  // Files whose family could not be inferred get their own entry, so they can be
  // found and fixed instead of being invisible.
  const unknown = bases.find((item) => !item.key);
  if (unknown && unknown.count > 0) {
    const chip = el("button", {
      class: "base-chip base-chip-unknown",
      type: "button",
      "aria-pressed": selected === "-" ? "true" : "false",
      dataset: { base: "unknown" },
      title: t("base.unknownHint"),
    },
    el("span", { text: t("base.unknown") }),
    el("span", { class: "n", text: formatNumber(unknown.count) }));
    chip.addEventListener("click", () => onSelect(selected === "-" ? "" : "-"));
    listEl.append(chip);
  }

  for (const entry of bases.filter((item) => item.key)) {
    const chip = el("button", {
      class: "base-chip",
      type: "button",
      "aria-pressed": selected === entry.key ? "true" : "false",
      dataset: { base: entry.key },
    },
    el("span", { text: BASE_LABEL[entry.key] || entry.key.toUpperCase() }),
    el("span", { class: "n", text: formatNumber(entry.count) }));
    chip.addEventListener("click", () => onSelect(selected === entry.key ? "" : entry.key));
    listEl.append(chip);
  }
}
