/* Selection, deletion and the pending-deletion queue.

   Kept out of the page entry point: these are the only pieces that mutate several
   cards at once, and they are easier to follow (and to test by hand) on their own. */

export function createManager({ dom, state, grid, api, toast, t, updateCount, clearSelection, getUndoPanel }) {
function gridNow() {
  return Date.now() / 1000 + state.serverOffset;
}

function setPicked(ids) {
  state.picked = new Set(ids);
  grid.setPicked([...state.picked]);
  syncSelectBar();
}

function togglePick(id) {
  if (state.picked.has(id)) state.picked.delete(id);
  else state.picked.add(id);
  setPicked([...state.picked]);
}

function syncSelectBar() {
  const active = state.selectMode;
  dom.selectToggle.setAttribute("aria-pressed", active ? "true" : "false");
  dom.selectToggle.title = t(active ? "select.exit" : "select.enter");
  dom.selectToggle.setAttribute("aria-label", dom.selectToggle.title);
  dom.selectbar.hidden = !active;
  if (!active) return;
  dom.selectbarCount.textContent = t("select.count", { n: state.picked.size });
  // Inside the favourites view the only meaningful batch action is the opposite.
  dom.selectFavorite.textContent = t(state.favOnly ? "select.unfavorite" : "select.favorite");
  dom.selectFavorite.disabled = state.picked.size === 0;
  dom.selectDelete.disabled = state.picked.size === 0;
}

function setSelectMode(on) {
  state.selectMode = Boolean(on);
  if (!state.selectMode) state.picked = new Set();
  grid.setSelectMode(state.selectMode);
  grid.setPicked([...state.picked]);
  syncSelectBar();
}

function updateUndoButton() {
  const count = state.pending.size;
  dom.undoCount.hidden = count === 0;
  dom.undoCount.textContent = String(count);
  dom.undoButton.dataset.active = count > 0 ? "true" : "false";
}

/** Merge the server's queue into the grid, the toolbar and the undo panel. */
function applyPending(list, serverTime, pausedFlag) {
  if (serverTime) state.serverOffset = serverTime - Date.now() / 1000;
  if (typeof pausedFlag === "boolean") state.pendingPaused = pausedFlag;
  const now = gridNow();
  const incoming = new Map((list || []).map((item) => [item.id, item.deadline]));

  for (const [id, deadline] of [...state.pending]) {
    if (incoming.has(id)) continue;
    state.pending.delete(id);
    grid.clearPending(id);
    // Gone from the queue: either undone (keep the card) or expired (drop it).
    if (deadline <= now + 1) {
      grid.remove(id);
      state.total = Math.max(0, state.total - 1);
    }
  }
  for (const [id, deadline] of incoming) {
    if (!state.pending.has(id)) grid.setPending(id, deadline);
    state.pending.set(id, deadline);
  }
  if (!state.pendingPaused) grid.tickPending(now);
  updateUndoButton();
  getUndoPanel()?.setItems(list || [], serverTime, state.pendingPaused);
  updateCount();
}

async function deleteItems(ids) {
  const targets = [...new Set(ids)].filter(Boolean);
  if (!targets.length) return;
  try {
    const result = await api.deleteItems(targets);
    const seconds = result.undo_seconds || 0;
    applyPending(result.pending || [], null);
    if (seconds > 0) {
      toast(t("toast.queued", { s: seconds }));
    } else {
      for (const row of result.results || []) {
        if (row.deleted) grid.remove(row.id);
      }
      state.total = Math.max(0, state.total - targets.length);
      updateCount();
      toast(t("toast.deleted", { folder: ".gallery-trash" }));
      if (state.selectedId && targets.includes(state.selectedId)) clearSelection();
    }
    setPicked([]);
  } catch (error) {
    console.error("gallery: delete failed", error);
    toast(t("toast.failed"));
  }
}

  /** After an undo the queue changed, so re-read it and repaint the cards. */
  async function refreshQueue() {
    try {
      const data = await api.fetchPending(false);
      applyPending(data.items || [], data.server_time, data.paused);
    } catch {
      toast(t("toast.failed"));
    }
  }

  return {
    gridNow, setPicked, togglePick, syncSelectBar, setSelectMode,
    updateUndoButton, applyPending, deleteItems, refreshQueue,
  };
}
