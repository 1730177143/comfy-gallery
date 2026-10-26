/* Settings dialog: default layout, extra folders, paging and index maintenance. */

import { el, clear, toast } from "./dom.js";
import { t } from "./i18n.js";

/**
 * The dialog writes straight through to the settings endpoint. Anything that
 * changes what gets indexed calls ``onDataChanged`` so the caller can reload the
 * sidebar and the first page; layout changes only need ``applyLayout``.
 */
export function createSettings({ dialog, button, layoutGroups, applyLayout, applyColumns, applyWheel, onDataChanged }) {
  const refs = {
    rootList: dialog.querySelector("#root-list"),
    rootInput: dialog.querySelector("#root-input"),
    rootAdd: dialog.querySelector("#root-add-btn"),
    includeVideo: dialog.querySelector("#include-video"),
    wheelNav: dialog.querySelector("#wheel-nav"),
    pageSize: dialog.querySelector("#page-size"),
    columns: dialog.querySelector("#columns-input"),
    undoSeconds: dialog.querySelector("#undo-seconds"),
    dataDir: dialog.querySelector("#data-dir"),
    rescan: dialog.querySelector("#rescan-btn"),
    groups: layoutGroups,
  };

  async function save(patch) {
    const response = await fetch("/gallery/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  }

  async function load() {
    const response = await fetch("/gallery/api/settings", { headers: { Accept: "application/json" } });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  }

  function rootPaths(data) {
    return (data.roots || []).filter((root) => root.id !== "output").map((root) => root.path);
  }

  function renderRoots(data) {
    clear(refs.rootList);
    const paths = rootPaths(data);
    if (!paths.length) {
      refs.rootList.append(el("p", { class: "root-empty", text: t("settings.rootsEmpty") }));
      return;
    }
    for (const path of paths) {
      const row = el("div", { class: "root-row" }, el("span", { class: "root-path", text: path }));
      const remove = el("button", {
        class: "btn", type: "button", dataset: { variant: "danger" }, text: t("settings.remove"),
      });
      remove.addEventListener("click", () => writeRoots(paths.filter((item) => item !== path)));
      row.append(remove);
      refs.rootList.append(row);
    }
  }

  async function refresh() {
    try {
      const data = await load();
      const settings = data.settings || {};
      refs.includeVideo.checked = Boolean(settings.include_video);
      refs.wheelNav.checked = Boolean(settings.wheel_navigate);
      refs.pageSize.value = settings.page_size || 60;
      refs.columns.value = settings.columns || 0;
      refs.undoSeconds.value = settings.undo_seconds ?? 60;
      refs.dataDir.textContent = data.data_dir || "—";
      applyLayout(settings.layout || "grid", false);
      renderRoots(data);
    } catch (error) {
      console.error("gallery: could not load settings", error);
    }
  }

  async function writeRoots(paths) {
    try {
      await save({ extra_roots: paths });
      await refresh();
      await onDataChanged();
    } catch {
      toast(t("toast.failed"));
    }
  }

  function bind() {
    button.addEventListener("click", async () => {
      await refresh();
      if (typeof dialog.showModal === "function") dialog.showModal();
    });

    refs.includeVideo.addEventListener("change", async () => {
      try {
        await save({ include_video: refs.includeVideo.checked });
        await onDataChanged();
      } catch {
        toast(t("toast.failed"));
      }
    });

    refs.pageSize.addEventListener("change", async () => {
      try {
        await save({ page_size: Number(refs.pageSize.value) });
        await onDataChanged();
      } catch {
        toast(t("toast.failed"));
      }
    });

    refs.columns.addEventListener("change", async () => {
      const value = Number(refs.columns.value) || 0;
      applyColumns(value);
      try {
        await save({ columns: value });
      } catch {
        toast(t("toast.failed"));
      }
    });

    refs.wheelNav.addEventListener("change", async () => {
      applyWheel(refs.wheelNav.checked);
      try {
        await save({ wheel_navigate: refs.wheelNav.checked });
      } catch {
        toast(t("toast.failed"));
      }
    });

    refs.undoSeconds.addEventListener("change", async () => {
      try {
        await save({ undo_seconds: Number(refs.undoSeconds.value) || 0 });
      } catch {
        toast(t("toast.failed"));
      }
    });

    refs.rootAdd.addEventListener("click", async () => {
      const value = refs.rootInput.value.trim();
      if (!value) return;
      try {
        const data = await load();
        const paths = rootPaths(data);
        if (!paths.includes(value)) paths.push(value);
        refs.rootInput.value = "";
        await writeRoots(paths);
      } catch {
        toast(t("toast.failed"));
      }
    });

    refs.rescan.addEventListener("click", async () => {
      try {
        await fetch("/gallery/api/rescan", { method: "POST" });
        await onDataChanged();
      } catch {
        toast(t("toast.failed"));
      }
    });
  }

  return { bind, refresh };
}
