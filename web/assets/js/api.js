const BASE = "/gallery/api";

async function requestJSON(url, options) {
  const response = await fetch(url, { headers: { Accept: "application/json" }, ...options });
  if (!response.ok) {
    let detail = {};
    try {
      detail = await response.json();
    } catch {
      /* the body may not be JSON at all */
    }
    const error = new Error(detail.error || `HTTP ${response.status}`);
    error.status = response.status;
    error.code = detail.error;
    throw error;
  }
  return response.json();
}

export async function fetchItems({
  folder = "", root = "", base = "", fav = 0, query = "", sort = "newest", offset = 0, limit = 60,
}) {
  const params = new URLSearchParams({
    folder, root, base, q: query, sort,
    offset: String(offset), limit: String(limit),
  });
  if (fav) params.set("fav", "1");
  return requestJSON(`${BASE}/items?${params.toString()}`);
}

export function fetchItem(id) {
  return requestJSON(`${BASE}/item?id=${encodeURIComponent(id)}`);
}

export function fetchFolders() {
  return requestJSON(`${BASE}/folders`);
}

export function fetchState() {
  return requestJSON(`${BASE}/state`);
}

export function fetchSettings() {
  return requestJSON(`${BASE}/settings`);
}

export function saveSettings(patch) {
  return requestJSON(`${BASE}/settings`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
}

export function setFavorite(id, on) {
  return requestJSON(
    `${BASE}/favorite?id=${encodeURIComponent(id)}&on=${on ? 1 : 0}`,
    { method: "POST" },
  );
}

export function setBase(id, base) {
  return requestJSON(
    `${BASE}/base?id=${encodeURIComponent(id)}&base=${encodeURIComponent(base)}`,
    { method: "POST" },
  );
}

export function deleteItems(ids) {
  return requestJSON(`${BASE}/delete`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ids }),
  });
}

export function fetchPending(hold = false) {
  return requestJSON(`${BASE}/pending`, { method: hold ? "POST" : "GET" });
}

export function releasePending() {
  return requestJSON(`${BASE}/pending`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ release: true }),
  });
}

export function undoPending(ids) {
  return requestJSON(`${BASE}/pending/undo`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ids }),
  });
}

export function undoAllPending() {
  return requestJSON(`${BASE}/pending/undo?all=1`, { method: "POST" });
}

export function favoriteMany(ids, on) {
  return requestJSON(`${BASE}/favorite`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ids, on: on ? 1 : 0 }),
  });
}

export function trash(id) {
  return requestJSON(`${BASE}/trash?id=${encodeURIComponent(id)}`, { method: "POST" });
}

export function fetchWorkflow(id) {
  return requestJSON(`${BASE}/workflow?id=${encodeURIComponent(id)}`);
}

export function rescan() {
  return requestJSON(`${BASE}/rescan`, { method: "POST" });
}

export function exportWorkflow(id) {
  return requestJSON(`${BASE}/export-workflow?id=${encodeURIComponent(id)}`, { method: "POST" });
}

export function thumbUrl(id, size = 384) {
  return `${BASE}/thumb?id=${encodeURIComponent(id)}&s=${size}`;
}

export function fileUrl(id) {
  return `${BASE}/file?id=${encodeURIComponent(id)}`;
}
