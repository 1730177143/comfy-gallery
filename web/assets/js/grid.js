/* Thumbnail cards: a uniform grid, or a waterfall that fills the shortest column.

   CSS multi-column would be simpler, but it pours items down one column at a time,
   so "newest first" would read top-to-bottom inside a column instead of across the
   top. Placing each card into the currently shortest column keeps reading order
   intact, and the item's real width/height means no reflow once images arrive. */

import { el, svgIcon } from "./dom.js";
import { t } from "./i18n.js";
import { thumbUrl } from "./api.js";

const BASE_LABEL = {
  krea2: "KR2", flux: "FLUX", sdxl: "XL", illustrious: "IL", noobai: "NOOB",
  animagine: "ANG", pony: "PONY", qwen: "QWEN", wan: "WAN", hunyuan: "HY",
  ltx: "LTX", minimax: "MM", sd15: "SD15", sd3: "SD3", sd21: "SD21",
};

const MIN_COLUMN = 210;
const GAP = 10;
// Text block under the image; used only to balance columns before measuring.
const INFO_HEIGHT = 46;

export function createGrid({ gridEl, onSelect, onZoom, onFavorite, onDelete }) {
  const cards = new Map();   // id -> element, in insertion order
  const items = new Map();   // id -> item data, for re-layout
  let selectedId = null;
  let favorites = new Set();
  let mode = "grid";
  let columns = [];
  let columnCount = 0;
  let columnWidth = 0;
  let totals = [];
  let desiredColumns = 0;
  let selectMode = false;
  const pending = new Map();   // id -> deadline (epoch seconds)
  const picked = new Set();

  function buildCard(item) {
    const card = el("div", {
      class: "card",
      role: "option",
      tabindex: "0",
      "aria-selected": "false",
      "aria-label": item.name,
      dataset: { id: item.id, base: item.base_model || "" },
      title: item.folder ? `${item.folder}/${item.name}` : item.name,
    });

    const media = el("span", { class: "card-media" });
    if (item.width && item.height) media.style.setProperty("--ar", `${item.width} / ${item.height}`);
    const thumb = el("img", {
      class: "card-thumb",
      src: thumbUrl(item.id, 384),
      alt: "",
      loading: "lazy",
      decoding: "async",
      draggable: "false",
    });
    thumb.addEventListener("load", () => thumb.setAttribute("data-loaded", "true"));
    thumb.addEventListener("error", () => {
      thumb.remove();
      media.append(el("div", { class: "card-fallback" }, svgIcon("image")));
    });
    media.append(thumb);

    // Always say something about the base model: an unrecognised family is a
    // fact worth showing (and fixable from the detail panel), silence is not.
    const baseKey = item.base_model || (item.source !== "none" ? "unknown" : "");
    if (baseKey) {
      media.append(el("span", {
        class: "card-badge",
        dataset: { base: baseKey },
        title: item.base_model ? undefined : t("base.unknownHint"),
        text: item.base_model
          ? (BASE_LABEL[item.base_model] || item.base_model.toUpperCase())
          : t("base.unknownShort"),
      }));
    }
    if (item.source === "none") {
      media.append(el("span", { class: "card-warn", text: t("badge.none") }));
    }

    const star = el("button", {
      class: "card-act",
      type: "button",
      "aria-pressed": favorites.has(item.id) ? "true" : "false",
      title: t("action.favorite"),
      "aria-label": t("action.favorite"),
    }, svgIcon("star"));
    star.addEventListener("click", (event) => {
      event.stopPropagation();
      onFavorite(item.id, !favorites.has(item.id));
    });

    const bin = el("button", {
      class: "card-act card-act-danger",
      type: "button",
      title: t("action.delete"),
      "aria-label": t("action.delete"),
    }, svgIcon("trash"));
    bin.addEventListener("click", (event) => {
      event.stopPropagation();
      onDelete?.(item.id);
    });

    media.append(el("span", { class: "card-actions" }, star, bin));
    media.append(el("span", { class: "card-pending", hidden: true }));

    const metaParts = [];
    if (item.width && item.height) metaParts.push(`${item.width}×${item.height}`);
    metaParts.push(item.source === "a1111" ? "A1111" : item.source === "none" ? "—" : "ComfyUI");

    media.append(el("span", { class: "card-info" },
      el("span", { class: "card-name", text: item.name }),
      item.snippet ? el("span", { class: "card-snippet", text: item.snippet }) : null,
      el("span", { class: "card-meta", text: metaParts.join(" · ") }),
    ));

    card.append(media);
    card.addEventListener("click", () => onSelect(item.id));
    card.addEventListener("dblclick", () => onZoom(item.id));
    card.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        onSelect(item.id);
      }
    });
    return card;
  }

  /* ---------- masonry ---------- */

  function columnCountFor(width) {
    if (desiredColumns > 0) return desiredColumns;
    const usable = Math.max(width, MIN_COLUMN);
    return Math.max(1, Math.floor((usable + GAP) / (MIN_COLUMN + GAP)));
  }

  function buildColumns(count) {
    gridEl.replaceChildren();
    columns = [];
    for (let index = 0; index < count; index += 1) {
      const column = el("div", { class: "masonry-col" });
      columns.push(column);
      gridEl.append(column);
    }
    columnCount = count;
  }

  function estimateHeight(item) {
    // Measuring the DOM here would read zero: thumbnails load after layout.
    const ratio = item.width && item.height ? item.height / item.width : 1.33;
    return columnWidth * ratio + INFO_HEIGHT;
  }

  function placeInShortest(card, item) {
    let target = 0;
    for (let index = 1; index < totals.length; index += 1) {
      if (totals[index] < totals[target]) target = index;
    }
    columns[target].append(card);
    totals[target] += estimateHeight(item) + GAP;
  }

  function relayout() {
    if (mode !== "masonry") return;
    const width = gridEl.clientWidth || 900;
    const count = columnCountFor(width);
    if (count !== columnCount || !gridEl.querySelector(".masonry-col")) {
      buildColumns(count);
      columnWidth = (width - GAP * (count - 1)) / count;
      totals = new Array(count).fill(0);
      for (const [id, card] of cards) {
        const item = items.get(id);
        if (item) placeInShortest(card, item);
      }
    }
  }

  /* ---------- public ---------- */

  function markPending(card, deadline) {
    card.dataset.pending = "true";
    const badge = card.querySelector(".card-pending");
    if (!badge) return;
    badge.hidden = false;
    const left = Math.max(0, Math.ceil(deadline - Date.now() / 1000));
    badge.textContent = `${left}s`;
  }

  function setPending(id, deadline) {
    pending.set(id, deadline);
    const card = cards.get(id);
    if (card) markPending(card, deadline);
  }

  function clearPending(id) {
    pending.delete(id);
    const card = cards.get(id);
    if (!card) return;
    delete card.dataset.pending;
    const badge = card.querySelector(".card-pending");
    if (badge) badge.hidden = true;
  }

  function tickPending(nowSeconds) {
    for (const [id, deadline] of pending) {
      const card = cards.get(id);
      if (!card) continue;
      const badge = card.querySelector(".card-pending");
      if (!badge) continue;
      const left = Math.max(0, Math.ceil(deadline - nowSeconds));
      badge.textContent = `${left}s`;
    }
  }

  function setSelectMode(on) {
    selectMode = Boolean(on);
    gridEl.dataset.select = selectMode ? "true" : "false";
    if (!selectMode) setPicked([]);
  }

  function setPicked(ids) {
    const next = new Set(ids);
    for (const [id, card] of cards) {
      const on = next.has(id);
      card.dataset.picked = on ? "true" : "false";
      card.setAttribute("aria-selected", on ? "true" : "false");
    }
    picked.clear();
    for (const id of next) picked.add(id);
    if (selectedId) {
      const card = cards.get(selectedId);
      if (card) card.setAttribute("aria-selected", next.has(selectedId) ? "true" : "false");
    }
  }

  function append(list) {
    const fresh = [];
    for (const item of list) {
      if (cards.has(item.id)) continue;
      const card = buildCard(item);
      cards.set(item.id, card);
      items.set(item.id, item);
      // The queue may already know this id (page loaded with deletions pending).
      if (pending.has(item.id)) markPending(card, pending.get(item.id));
      fresh.push([card, item]);
    }
    if (mode === "masonry") {
      if (!columns.length) relayout();
      for (const [card, item] of fresh) placeInShortest(card, item);
      return;
    }
    const fragment = document.createDocumentFragment();
    for (const [card] of fresh) fragment.append(card);
    gridEl.append(fragment);
  }

  function reset() {
    cards.clear();
    items.clear();
    selectedId = null;
    columns = [];
    columnCount = 0;
    totals = [];
    gridEl.replaceChildren();
  }

  function remove(id) {
    const card = cards.get(id);
    if (!card) return;
    card.remove();
    cards.delete(id);
    items.delete(id);
    if (selectedId === id) selectedId = null;
  }

  function setSelected(id) {
    if (selectedId === id) return;
    const previous = selectedId ? cards.get(selectedId) : null;
    if (previous) previous.setAttribute("aria-selected", "false");
    selectedId = id;
    const next = id ? cards.get(id) : null;
    if (next) {
      next.setAttribute("aria-selected", "true");
      next.scrollIntoView({ block: "nearest" });
    }
  }

  function setFavorite(id, on) {
    if (on) favorites.add(id);
    else favorites.delete(id);
    const star = cards.get(id)?.querySelector(".card-act");
    if (star) star.setAttribute("aria-pressed", on ? "true" : "false");
  }

  function setFavorites(ids) {
    favorites = new Set(ids || []);
    for (const [id, card] of cards) {
      const star = card.querySelector(".card-act");
      if (star) star.setAttribute("aria-pressed", favorites.has(id) ? "true" : "false");
    }
  }

  function moveSelection(delta) {
    const ids = [...cards.keys()];
    if (!ids.length) return null;
    const current = selectedId ? ids.indexOf(selectedId) : -1;
    const nextIndex = Math.min(ids.length - 1, Math.max(0, current + delta));
    return ids[nextIndex];
  }

  function setColumns(count) {
    desiredColumns = Math.max(0, Math.min(12, Number(count) || 0));
    if (desiredColumns > 0) {
      gridEl.dataset.cols = String(desiredColumns);
      gridEl.style.setProperty("--cols", String(desiredColumns));
    } else {
      delete gridEl.dataset.cols;
      gridEl.style.removeProperty("--cols");
    }
    if (mode === "masonry" && columnCountFor(gridEl.clientWidth || 900) !== columnCount) relayout();
  }

  function setLayout(layout) {
    const next = layout === "masonry" ? "masonry" : "grid";
    if (next === mode) return;
    mode = next;
    gridEl.dataset.layout = mode;
    gridEl.replaceChildren();
    columns = [];
    columnCount = 0;

    if (mode === "masonry") {
      columnCount = 0;
      relayout();
      return;
    }
    const fragment = document.createDocumentFragment();
    for (const card of cards.values()) fragment.append(card);
    gridEl.append(fragment);
  }

  let resizeTimer = null;
  window.addEventListener("resize", () => {
    if (mode !== "masonry") return;
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {
      if (columnCountFor(gridEl.clientWidth || 900) !== columnCount) relayout();
    }, 150);
  });

  return {
    append, reset, remove, setSelected, setFavorite, setFavorites, moveSelection, setLayout, setColumns,
    setPending, clearPending, tickPending, setSelectMode, setPicked,
    get size() { return cards.size; },
  };
}

export { BASE_LABEL };
