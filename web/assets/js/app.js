/* Page wiring: filters, layout, paging and the scan poll. */

import { localizeStatic, t } from "./i18n.js";
import * as api from "./api.js";
import { createGrid } from "./grid.js";
import { renderDetail, renderDetailEmpty } from "./detail.js";
import { renderFolders, renderBases } from "./sidebar.js";
import { createSettings } from "./settings.js";
import { createUndoPanel } from "./undo.js";
import { createViewer } from "./viewer.js";
import { createManager } from "./manage.js";
import { sendWorkflowToCanvas } from "./send.js";
import { dom } from "./refs.js";
import { el, clear, toast, formatNumber, svgIcon } from "./dom.js";

const PAGE_SIZE = 60;

const state = {
  folder: "",
  root: "",
  base: "",
  favOnly: false,
  query: "",
  sort: "newest",
  layout: "grid",
  offset: 0,
  total: 0,
  loading: false,
  exhausted: false,
  selectedId: null,
  latestMtime: 0,
  scan: { running: false, indexed: 0, scanned: 0 },
  favorites: [],
  detailMode: "side",
  columns: 0,
  wheelNavigate: false,
  clickCloseViewer: true,
  selectMode: false,
  picked: new Set(),
  pending: new Map(),
  pendingPaused: false,
  serverOffset: 0,
  loadedIds: [],
  sidebar: { folders: [], bases: [] },
};


let grid = null;
let settings = null;
let undoPanel = null;
let viewer = null;
let manager = null;
let pendingTicker = null;
let observer = null;
let pollTimer = null;
let searchTimer = null;

/* ---------- status ---------- */

function setStatus(text, busy) {
  clear(dom.status);
  if (!text) {
    dom.status.hidden = true;
    return;
  }
  dom.status.hidden = false;
  if (busy) dom.status.append(el("span", { class: "spinner" }));
  dom.status.append(el("span", { text }));
}

/** The counter and the empty-state message always agree with ``state.total``. */
function updateCount() {
  dom.count.textContent = state.total
    ? t("count.items", { count: formatNumber(state.total) })
    : "—";

  dom.empty.hidden = state.total > 0;
  if (state.total) return;
  const filtered = state.favOnly || state.base || state.query;
  dom.emptyTitle.textContent = filtered ? t("empty.filtered") : t("empty.title");
  dom.emptyBody.textContent = filtered ? "" : t("empty.body");
}

function renderScanStatus() {
  if (state.scan && state.scan.running && (state.scan.scanned || 0) > 0) {
    setStatus(t("status.scanning", {
      done: formatNumber(state.scan.indexed || 0),
      total: formatNumber(state.scan.scanned || 0),
    }), true);
    return;
  }
  if (state.loading) return;
  if (!state.exhausted && state.total > 0) setStatus(t("status.more"), false);
  else setStatus("");
}

/* ---------- listing ---------- */

async function loadPage(reset) {
  if (state.loading) return;
  state.loading = true;
  if (reset) {
    state.offset = 0;
    state.exhausted = false;
    state.loadedIds = [];
    grid.reset();
  }
  setStatus(t("status.loading"), true);

  try {
    const data = await api.fetchItems({
      folder: state.folder,
      root: state.root,
      base: state.base,
      fav: state.favOnly ? 1 : 0,
      query: state.query,
      sort: state.sort,
      offset: state.offset,
      limit: PAGE_SIZE,
    });
    state.total = data.total;
    state.scan = data.scan || state.scan;
    grid.setFavorites(state.favorites);
    grid.append(data.items || []);
    for (const item of data.items || []) state.loadedIds.push(item.id);
    if (state.selectMode && state.picked.size) grid.setPicked([...state.picked]);
    state.offset += (data.items || []).length;
    state.exhausted = (data.items || []).length < PAGE_SIZE || state.offset >= data.total;

    if (state.selectedId) grid.setSelected(state.selectedId);
    updateCount();
  } catch (error) {
    console.error("gallery: could not load items", error);
    setStatus(t("toast.failed"));
  } finally {
    // Clear the flag before the status renders, or "loading" wins every time.
    state.loading = false;
    renderScanStatus();
  }
}

function loadMore() {
  if (state.loading || state.exhausted) return;
  loadPage(false);
}

/* ---------- sidebar ---------- */

async function loadSidebar() {
  try {
    const data = await api.fetchFolders();
    state.sidebar = { folders: data.folders || [], bases: data.bases || [] };
    drawSidebar();
  } catch (error) {
    console.error("gallery: could not load folders", error);
  }
}

function drawSidebar() {
  renderFolders(dom.folderNav, {
    folders: state.sidebar.folders,
    state,
    favoritesCount: state.favorites.length,
    onSelect: (patch) => {
      Object.assign(state, patch);
      drawSidebar();
      manager.syncSelectBar();
      loadPage(true);
    },
  });
  renderBases(dom.baseList, {
    bases: state.sidebar.bases,
    selected: state.base,
    onSelect: (base) => {
      state.base = base;
      drawSidebar();
      loadPage(true);
    },
  });
}

/* ---------- layout ---------- */

function setLayout(layout, persist = true) {
  state.layout = layout === "masonry" ? "masonry" : "grid";
  grid.setLayout(state.layout);
  for (const group of [dom.layoutToggle, dom.layoutToggleDialog]) {
    if (!group) continue;
    for (const button of group.querySelectorAll(".seg")) {
      button.setAttribute("aria-pressed", button.dataset.layout === state.layout ? "true" : "false");
    }
  }
  if (persist) api.saveSettings({ layout: state.layout }).catch(() => {});
}

function toggleSidebar() {
  const collapsed = dom.app.dataset.sidebar === "collapsed";
  dom.app.dataset.sidebar = collapsed ? "" : "collapsed";
  const title = t(collapsed ? "sidebar.collapse" : "sidebar.expand");
  dom.sidebarToggle.title = title;
  dom.sidebarToggle.setAttribute("aria-label", title);
  const icon = document.getElementById("sidebar-icon");
  clear(icon);
  icon.append(svgIcon(collapsed ? "chevronLeft" : "chevronRight"));
}

/** Load this file's workflow onto the ComfyUI canvas (other tab, same origin). */
async function sendWorkflow(id) {
  try {
    const data = await api.fetchWorkflow(id);
    if (!data.workflow) {
      toast(t("toast.noWorkflow"));
      return;
    }
    toast(sendWorkflowToCanvas(data.workflow) ? t("toast.sentWorkflow") : t("toast.failed"));
  } catch {
    toast(t("toast.noWorkflow"));
  }
}

/* ---------- selection and actions ---------- */

function closeDetail() {
  if (dom.detailDialog.open) dom.detailDialog.close();
  renderDetailEmpty(dom.detail);
  dom.app.dataset.detail = "closed";
}

function clearSelection() {
  state.selectedId = null;
  grid.setSelected(null);
  closeDetail();
  closeLightbox();
}

async function selectItem(id) {
  state.selectedId = id;
  grid.setSelected(id);

  // "Image only" never renders a panel; the viewer is the detail view.
  if (state.detailMode === "image") {
    closeDetail();
    openLightbox(id);
    return;
  }

  try {
    const payload = await api.fetchItem(id);
    const handlers = {
      onZoom: openLightbox,
      onFavorite: toggleFavorite,
      onTrash: trashItem,
      onSendWorkflow: sendWorkflow,
      onClose: clearSelection,
      onBaseChange: (base) => changeBase(id, base),
    };
    if (state.detailMode === "modal") {
      closeLightbox();
      renderDetail(dom.detailDialogContent, payload, handlers);
      if (!dom.detailDialog.open) dom.detailDialog.showModal();
      dom.app.dataset.detail = "closed";
      return;
    }
    if (dom.detailDialog.open) dom.detailDialog.close();
    renderDetail(dom.detail, payload, handlers);
    dom.app.dataset.detail = "open";
  } catch (error) {
    console.error("gallery: could not load item", error);
    toast(t("toast.failed"));
  }
}

function stepSelection(delta) {
  const next = grid.moveSelection(delta);
  if (next) selectItem(next);
}

async function changeBase(id, base) {
  try {
    await api.setBase(id, base);
    await loadSidebar();
    await loadPage(true);
    await selectItem(id);
  } catch {
    toast(t("toast.failed"));
  }
}

function setDetailMode(mode, persist = true) {
  state.detailMode = ["side", "modal", "image"].includes(mode) ? mode : "side";
  for (const button of dom.detailToggle.querySelectorAll("[data-detail-mode]")) {
    button.setAttribute("aria-pressed", button.dataset.detailMode === state.detailMode ? "true" : "false");
  }
  if (persist) api.saveSettings({ detail_mode: state.detailMode }).catch(() => {});
  if (state.selectedId) selectItem(state.selectedId);
  else closeDetail();
}

function applyWheel(on) {
  state.wheelNavigate = Boolean(on);
}

function applyClickClose(on) {
  state.clickCloseViewer = on !== false;
}

function applyColumns(count) {
  state.columns = Math.max(0, Math.min(12, Number(count) || 0));
  grid.setColumns(state.columns);
}

async function toggleFavorite(id, on) {
  try {
    const result = await api.setFavorite(id, on);
    state.favorites = on
      ? [...new Set([...state.favorites, id])]
      : state.favorites.filter((item) => item !== id);
    grid.setFavorite(id, result.favorite);
    drawSidebar();
    if (state.favOnly && !result.favorite) {
      grid.remove(id);
      state.total = Math.max(0, state.total - 1);
      updateCount();
    }
    toast(t(result.favorite ? "toast.favorited" : "toast.unfavorited"));
  } catch {
    toast(t("toast.failed"));
  }
}

async function trashItem(id) {
  try {
    const result = await api.trash(id);
    grid.remove(id);
    state.total = Math.max(0, state.total - 1);
    state.favorites = state.favorites.filter((item) => item !== id);
    state.selectedId = null;
    closeDetail();
    drawSidebar();
    updateCount();
    toast(t("toast.trashed", { folder: result.trash }));
  } catch {
    toast(t("toast.failed"));
  }
}

/* ---------- lightbox ---------- */

function openLightbox(id) {
  viewer.open(id);
}

function closeLightbox() {
  viewer.close();
}

/* ---------- polling ---------- */

async function poll() {
  try {
    const data = await api.fetchState();
    const wasRunning = state.scan && state.scan.running;
    state.scan = data.scan || state.scan;
    state.favorites = data.favorites || state.favorites;
    if (data.pending) manager.applyPending(data.pending, data.server_time, data.pending_paused);

    if (state.scan.running) {
      renderScanStatus();
    } else if (wasRunning) {
      await loadSidebar();
      await loadPage(true);
    }

    const latest = data.latest_mtime || 0;
    if (!state.latestMtime) {
      state.latestMtime = latest;
    } else if (latest > state.latestMtime) {
      state.latestMtime = latest;
      if (dom.area.scrollTop < 80) await loadPage(true);
      else dom.refresh.dataset.new = "true";
    }
  } catch {
    /* a transient poll failure is not worth surfacing */
  }
}

/* ---------- events ---------- */

function bindEvents() {
  dom.search.addEventListener("input", () => {
    clearTimeout(searchTimer);
    dom.searchClear.hidden = !dom.search.value;
    searchTimer = setTimeout(() => {
      state.query = dom.search.value.trim();
      loadPage(true);
    }, 220);
  });

  dom.searchClear.addEventListener("click", () => {
    dom.search.value = "";
    dom.searchClear.hidden = true;
    state.query = "";
    dom.search.focus();
    loadPage(true);
  });

  dom.sort.addEventListener("change", () => {
    state.sort = dom.sort.value;
    loadPage(true);
  });

  for (const group of [dom.layoutToggle, dom.layoutToggleDialog]) {
    if (!group) continue;
    group.addEventListener("click", (event) => {
      const button = event.target.closest(".seg");
      if (button) setLayout(button.dataset.layout);
    });
  }

  dom.refresh.addEventListener("click", async () => {
    dom.refresh.dataset.busy = "true";
    delete dom.refresh.dataset.new;
    try {
      await api.rescan();
    } catch {
      /* best effort: the index is still shown even if the scan call failed */
    }
    await loadSidebar();
    await loadPage(true);
    setTimeout(() => { dom.refresh.dataset.busy = "false"; }, 600);
  });

  dom.detailToggle.addEventListener("click", (event) => {
    const button = event.target.closest("[data-detail-mode]");
    if (button) setDetailMode(button.dataset.detailMode);
  });

  dom.detailPrev.addEventListener("click", () => stepSelection(-1));
  dom.detailNext.addEventListener("click", () => stepSelection(1));
  dom.detailDialog.addEventListener("click", (event) => {
    // A click on the backdrop lands on the dialog element itself.
    if (event.target === dom.detailDialog) dom.detailDialog.close();
  });
  dom.detailDialog.addEventListener("close", () => {
    if (state.detailMode === "modal") dom.app.dataset.detail = "closed";
  });

  dom.selectToggle.addEventListener("click", () => manager.setSelectMode(!state.selectMode));
  dom.selectExit.addEventListener("click", () => manager.setSelectMode(false));
  dom.selectAll.addEventListener("click", () => manager.setPicked(state.loadedIds));
  dom.selectNone.addEventListener("click", () => manager.setPicked([]));
  dom.selectFavorite.addEventListener("click", async () => {
    const ids = [...state.picked];
    if (!ids.length) return;
    // Inside the favourites view the only useful batch action is the opposite.
    const starring = !state.favOnly;
    try {
      await api.favoriteMany(ids, starring);
      state.favorites = starring
        ? [...new Set([...state.favorites, ...ids])]
        : state.favorites.filter((id) => !ids.includes(id));
      grid.setFavorites(state.favorites);
      drawSidebar();
      toast(t(starring ? "toast.favorited" : "toast.unfavorited"));
      manager.setPicked([]);
      if (!starring && state.favOnly) {
        // They no longer match the filter, so drop them from the grid.
        for (const id of ids) grid.remove(id);
        state.total = Math.max(0, state.total - ids.length);
        updateCount();
      }
    } catch {
      toast(t("toast.failed"));
    }
  });
  dom.selectDelete.addEventListener("click", () => manager.deleteItems([...state.picked]));
  dom.undoButton.addEventListener("click", () => undoPanel.open());

  dom.sidebarToggle.addEventListener("click", toggleSidebar);

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      if (state.selectMode) {
        manager.setSelectMode(false);
        return;
      }
      if (viewer?.isOpen) closeLightbox();
      else if (dom.detailDialog.open) dom.detailDialog.close();
      else if (dom.app.dataset.detail === "open") clearSelection();
      return;
    }
    const inViewer = Boolean(viewer?.isOpen) || dom.detailDialog.open;
    if (!inViewer) return;
    if (event.key === "ArrowRight") {
      event.preventDefault();
      stepSelection(1);
    } else if (event.key === "ArrowLeft") {
      event.preventDefault();
      stepSelection(-1);
    }
  });

  dom.grid.addEventListener("keydown", (event) => {
    const offsets = { ArrowRight: 1, ArrowLeft: -1, ArrowDown: 4, ArrowUp: -4 };
    const delta = offsets[event.key];
    if (!delta) return;
    event.preventDefault();
    const next = grid.moveSelection(delta);
    if (next) selectItem(next);
  });

  observer = new IntersectionObserver((entries) => {
    if (entries.some((entry) => entry.isIntersecting)) loadMore();
  }, { root: dom.area, rootMargin: "700px" });
  observer.observe(dom.sentinel);
}

/* ---------- boot ---------- */

async function boot() {
  localizeStatic();
  document.getElementById("search-icon")?.append(svgIcon("search"));
  document.getElementById("refresh-icon")?.append(svgIcon("refresh"));
  document.getElementById("settings-icon")?.append(svgIcon("gear"));
  document.getElementById("sidebar-icon")?.append(svgIcon("chevronRight"));
  document.getElementById("select-icon")?.append(svgIcon("check"));
  document.getElementById("undo-icon")?.append(svgIcon("undo"));
  for (const [mode, icon] of [["side", "panelRight"], ["modal", "panelModal"], ["image", "imageOnly"]]) {
    document.querySelector(`#detail-toggle [data-detail-mode="${mode}"]`)?.append(svgIcon(icon));
  }

  grid = createGrid({
    gridEl: dom.grid,
    onSelect: (id) => (state.selectMode ? manager.togglePick(id) : selectItem(id)),
    onZoom: openLightbox,
    onFavorite: toggleFavorite,
    onDelete: (id) => manager.deleteItems([id]),
    onSendWorkflow: sendWorkflow,
  });
  dom.grid.setAttribute("role", "listbox");
  dom.grid.setAttribute("aria-label", t("search.label"));
  closeDetail();

  viewer = createViewer({
    lightbox: dom.lightbox,
    canvas: dom.lightboxCanvas,
    closeButton: dom.lightboxClose,
    prevButton: dom.lightboxPrev,
    nextButton: dom.lightboxNext,
    onStep: stepSelection,
    wheelEnabled: () => state.wheelNavigate,
    clickClose: () => state.clickCloseViewer,
  });

  manager = createManager({
    dom,
    state,
    grid,
    api,
    toast,
    t,
    updateCount,
    clearSelection,
    getUndoPanel: () => undoPanel,
  });

  undoPanel = createUndoPanel({
    dialog: dom.undoDialog,
    onChange: async () => { await manager.refreshQueue(); },
    onPreview: (id) => viewer.open(id),
  });

  settings = createSettings({
    dialog: dom.dialog,
    button: document.getElementById("settings-btn"),
    layoutGroups: [dom.layoutToggle, dom.layoutToggleDialog],
    applyLayout: setLayout,
    applyColumns,
    applyWheel,
    applyClickClose,
    onDataChanged: async () => {
      await loadSidebar();
      await loadPage(true);
    },
  });
  settings.bind();

  bindEvents();

  const initial = await api.fetchState().catch(() => null);
  if (initial) {
    state.favorites = initial.favorites || [];
    manager.applyPending(initial.pending || [], initial.server_time);
    setLayout(initial.layout || "grid", false);
    applyColumns(initial.columns || 0);
    applyWheel(initial.wheel_navigate);
    applyClickClose(initial.click_close_viewer);
    setDetailMode(initial.detail_mode || "side", false);
  }

  pendingTicker = setInterval(() => {
    if (state.pending.size && !state.pendingPaused) grid.tickPending(manager.gridNow());
  }, 1000);

  renderScanStatus();
  await loadSidebar();
  await loadPage(true);

  pollTimer = setInterval(poll, 5000);
  window.addEventListener("beforeunload", () => {
    clearInterval(pollTimer);
    clearInterval(pendingTicker);
  });
}

boot();
