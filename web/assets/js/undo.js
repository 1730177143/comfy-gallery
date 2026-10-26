/* The undo queue: files waiting out their deletion window.

   Opening the panel holds the server-side timers, so every remaining time in
   here is frozen until the panel is closed or the tab goes away. */

import { el, clear, toast } from "./dom.js";
import { t } from "./i18n.js";
import * as api from "./api.js";

export function createUndoPanel({ dialog, onChange, onPreview }) {
  const gridEl = dialog.querySelector("#undo-grid");
  const emptyEl = dialog.querySelector("#undo-empty");
  const selectToggle = dialog.querySelector("#undo-select-toggle");
  const pickedBtn = dialog.querySelector("#undo-picked");
  const allBtn = dialog.querySelector("#undo-all");
  const closeBtn = dialog.querySelector("#undo-close");

  let items = [];
  let offset = 0;          // server clock minus this browser's clock
  let picking = false;
  let heartbeat = null;
  let ticker = null;
  let paused = false;
  const picked = new Set();

  function held() {
    return dialog.open || paused;
  }

  /** Seconds to show: while held, trust the server's frozen value. */
  function remaining(item) {
    if (held() && typeof item.remaining === "number") return Math.max(0, Math.ceil(item.remaining));
    return Math.max(0, Math.ceil(item.deadline - (Date.now() / 1000 + offset)));
  }

  function row(item) {
    const left = remaining(item);
    // The preview is small on purpose (the panel is a queue, not a gallery), so
    // clicking it opens the full image in the viewer.
    const thumb = el("img", {
      class: "undo-thumb",
      src: api.thumbUrl(item.id, 512),
      alt: "",
      loading: "lazy",
      title: t("action.zoom"),
    });
    thumb.addEventListener("click", () => onPreview?.(item.id));

    const node = el("div", { class: "undo-item", dataset: { id: item.id, picked: picked.has(item.id) ? "true" : "false" } },
      thumb,
      el("div", { class: "undo-body" },
        el("span", { class: "undo-name", text: item.name, title: item.folder ? `${item.folder}/${item.name}` : item.name }),
        el("span", { class: "undo-left" }, el("span", { class: "undo-left-value", text: t("undo.remaining", { s: left }) })),
      ),
    );

    if (picking) {
      const box = el("input", { type: "checkbox", class: "undo-check", "aria-label": t("undo.select") });
      box.checked = picked.has(item.id);
      box.addEventListener("change", () => {
        if (box.checked) picked.add(item.id);
        else picked.delete(item.id);
        node.dataset.picked = box.checked ? "true" : "false";
        syncPickedButton();
      });
      node.append(box);
    }

    const undo = el("button", { class: "btn", type: "button" }, el("span", { text: t("undo.item") }));
    undo.addEventListener("click", async () => {
      node.dataset.busy = "true";
      try {
        await api.undoPending([item.id]);
        picked.delete(item.id);
        toast(t("toast.undone"));
        await onChange();
      } catch {
        toast(t("toast.failed"));
        node.dataset.busy = "false";
      }
    });
    node.append(undo);
    return node;
  }

  function syncPickedButton() {
    pickedBtn.hidden = !picking || picked.size === 0;
    pickedBtn.textContent = t("undo.picked", { n: picked.size });
  }

  function draw() {
    clear(gridEl);
    emptyEl.hidden = items.length > 0;
    allBtn.disabled = items.length === 0;
    for (const item of items) gridEl.append(row(item));
    selectToggle.setAttribute("aria-pressed", picking ? "true" : "false");
    allBtn.classList.toggle("is-empty", items.length === 0);
    syncPickedButton();
  }

  function tick() {
    for (const node of gridEl.querySelectorAll(".undo-item")) {
      const item = items.find((entry) => entry.id === node.dataset.id);
      const label = node.querySelector(".undo-left-value");
      if (item && label) label.textContent = t("undo.remaining", { s: remaining(item) });
    }
  }

  async function refresh() {
    try {
      const data = await api.fetchPending(true);   // POST = heartbeat
      items = data.items || [];
      offset = (data.server_time || Date.now() / 1000) - Date.now() / 1000;
      draw();
    } catch (error) {
      console.error("gallery: could not load the undo queue", error);
    }
  }

  async function undoAll() {
    try {
      await api.undoAllPending();
      picked.clear();
      toast(t("toast.undone"));
      await onChange();
    } catch {
      toast(t("toast.failed"));
    }
  }

  async function undoPicked() {
    if (!picked.size) return;
    try {
      await api.undoPending([...picked]);
      picked.clear();
      toast(t("toast.undone"));
      await onChange();
    } catch {
      toast(t("toast.failed"));
    }
  }

  async function syncQueue() {
    try {
      const data = await api.fetchPending(true);   // POST = keep the hold alive
      items = data.items || [];
      offset = (data.server_time || Date.now() / 1000) - Date.now() / 1000;
      paused = Boolean(data.paused);
      if (items.length !== gridEl.querySelectorAll(".undo-item").length) draw();
      else tick();
    } catch {
      /* a missed heartbeat only costs a tick */
    }
  }

  function startTimers() {
    stopTimers();
    heartbeat = setInterval(syncQueue, 2500);
    ticker = setInterval(tick, 1000);
  }

  function stopTimers() {
    if (heartbeat) clearInterval(heartbeat);
    if (ticker) clearInterval(ticker);
    heartbeat = null;
    ticker = null;
  }

  async function open() {
    picking = false;
    picked.clear();
    await refresh();
    if (typeof dialog.showModal === "function") dialog.showModal();
    // showModal focuses the first control, which paints a focus ring on the
    // close button; the dialog itself is the sensible initial focus.
    dialog.focus();
    startTimers();
  }

  function close() {
    stopTimers();
    paused = false;
    api.releasePending().catch(() => {});   // let the countdown run again now
    if (dialog.open) dialog.close();
  }

  selectToggle.addEventListener("click", () => {
    picking = !picking;
    if (!picking) picked.clear();
    draw();
  });
  pickedBtn.addEventListener("click", undoPicked);
  allBtn.addEventListener("click", undoAll);
  closeBtn.addEventListener("click", close);
  dialog.addEventListener("close", () => {
    stopTimers();
    paused = false;
    api.releasePending().catch(() => {});
  });
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) close();
  });

  return {
    open,
    close,
    /** Called from the page poll: keeps the list and the countdowns in sync. */
    setItems(list, serverTime, isPaused) {
      items = list || [];
      if (serverTime) offset = serverTime - Date.now() / 1000;
      if (typeof isPaused === "boolean") paused = isPaused;
      if (dialog.open) {
        if (items.length !== gridEl.querySelectorAll(".undo-item").length) draw();
        else tick();
      }
      return items.length;
    },
    tick,
  };
}
