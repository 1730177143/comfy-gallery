/* Sidebar rendering: folder tree, favorites entry and base-model filters. */

import { el, clear, svgIcon, formatNumber } from "./dom.js";
import { t } from "./i18n.js";

export const BASE_LABEL = {
  novelai: "NAI", moss: "MOSS", krea2: "KR2", flux: "FLUX", sdxl: "XL", illustrious: "IL", noobai: "NOOB",
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
// Kept outside the render so a sidebar refresh does not clear the filter.
const FILTER_THRESHOLD = 12;
let folderQuery = "";

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
  const list = el("div", { class: "nav-list" });

  const draw = () => {
    clear(list);
    const needle = folderQuery.trim().toLowerCase();
    const visible = needle
      ? nested.filter((item) => item.folder.toLowerCase().includes(needle))
      : nested;
    if (!visible.length) {
      list.append(el("p", { class: "root-empty", text: t("sidebar.noMatch") }));
      return;
    }
    for (const entry of visible) {
      const depth = entry.folder.split("/").length;
      const label = entry.folder.split("/").pop();
      list.append(navButton({
        icon: "folder",
        label: multipleRoots && depth === 1 ? `${label} · ${entry.root_label}` : label,
        count: entry.count,
        indent: depth,
        active: !state.favOnly && state.folder === entry.folder && state.root === entry.root_id,
        onClick: () => onSelect({ folder: entry.folder, root: entry.root_id, favOnly: false }),
      }));
    }
  };

  // A long folder tree is hard to scroll by eye, so it gets a filter box. Sticky,
  // because the list itself scrolls.
  if (nested.length > FILTER_THRESHOLD) {
    const input = el("input", {
      class: "nav-filter",
      id: "folder-filter",
      name: "folder-filter",
      type: "search",
      value: folderQuery,
      placeholder: t("sidebar.filter"),
      "aria-label": t("sidebar.filter"),
      spellcheck: "false",
    });
    input.addEventListener("input", () => {
      folderQuery = input.value;
      draw();
    });
    navEl.append(input);
  }

  draw();
  navEl.append(list);
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
