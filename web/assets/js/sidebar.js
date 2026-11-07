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
const COLLAPSE_KEY = "comfy-gallery:collapsed";
let folderQuery = "";

function collapsedSet() {
  try {
    return new Set(JSON.parse(localStorage.getItem(COLLAPSE_KEY) || "[]"));
  } catch {
    return new Set();
  }
}

function saveCollapsed(set) {
  try {
    localStorage.setItem(COLLAPSE_KEY, JSON.stringify([...set]));
  } catch {
    /* private mode: collapsing just will not survive a reload */
  }
}

function countRows(nodes) {
  return nodes.reduce((sum, node) => sum + 1 + countRows(node.children || []), 0);
}

export function renderFolders(navEl, { folders, tree, state, favoritesCount, onSelect }) {
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

  // The tree carries every ancestor, including folders that only hold
  // subfolders — those never appear as rows of their own.
  const nodes = Array.isArray(tree) ? tree : [];
  if (!nodes.length) {
    navEl.append(el("p", { class: "root-empty", text: t("sidebar.empty") }));
    return;
  }

  // Only suffix the root name when there really is more than one root; the
  // number of top-level folders says nothing about that.
  const multipleRoots = new Set(nodes.map((node) => node.root_id)).size > 1;
  const collapsed = collapsedSet();
  const list = el("div", { class: "nav-list", role: "tree" });

  const matches = (node, needle) => {
    if (!needle) return true;
    if (node.name.toLowerCase().includes(needle)) return true;
    if (node.folder.toLowerCase().includes(needle)) return true;
    return (node.children || []).some((child) => matches(child, needle));
  };

  const nodeKey = (node) => `${node.root_id}:${node.folder}`;

  const drawNode = (node, depth, needle) => {
    const children = node.children || [];
    const hasChildren = children.length > 0;
    // While filtering, everything on the way to a match is opened.
    const open = hasChildren && (Boolean(needle) || !collapsed.has(nodeKey(node)));

    const caret = hasChildren
      ? el("button", {
        class: `nav-caret${open ? " is-open" : ""}`,
        type: "button",
        "aria-expanded": open ? "true" : "false",
        "aria-label": open ? t("sidebar.collapseFolder") : t("sidebar.expandFolder"),
      }, svgIcon("chevronRight"))
      : el("span", { class: "nav-caret is-empty", "aria-hidden": "true" });

    const label = multipleRoots && depth === 1 ? `${node.name} · ${node.root_label}` : node.name;
    const row = el("div", {
      class: "nav-item",
      role: "treeitem",
      tabindex: "0",
      "aria-current": !state.favOnly && state.folder === node.folder && state.root === node.root_id
        ? "true" : "false",
      style: `padding-left:${8 + (depth - 1) * 14}px`,
    },
      caret,
      svgIcon("folder"),
      el("span", { class: "nav-name", text: label }),
      el("span", { class: "nav-count", text: node.total ? formatNumber(node.total) : "" }));

    const choose = () => onSelect({ folder: node.folder, root: node.root_id, favOnly: false });
    row.addEventListener("click", choose);
    row.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        choose();
      }
    });

    if (hasChildren) {
      caret.addEventListener("click", (event) => {
        event.stopPropagation();
        if (collapsed.has(nodeKey(node))) collapsed.delete(nodeKey(node));
        else collapsed.add(nodeKey(node));
        saveCollapsed(collapsed);
        draw();
      });
    }

    list.append(row);
    if (hasChildren && open) {
      for (const child of children) {
        if (matches(child, needle)) drawNode(child, depth + 1, needle);
      }
    }
  };

  const draw = () => {
    clear(list);
    const needle = folderQuery.trim().toLowerCase();
    const visible = nodes.filter((node) => matches(node, needle));
    if (!visible.length) {
      list.append(el("p", { class: "root-empty", text: t("sidebar.noMatch") }));
      return;
    }
    for (const node of visible) drawNode(node, 1, needle);
  };

  // A long folder tree is hard to scroll by eye, so it gets a filter box. Sticky,
  // because the list itself scrolls.
  if (countRows(nodes) > FILTER_THRESHOLD) {
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
