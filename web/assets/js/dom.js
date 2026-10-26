/* Small DOM helpers shared by the grid, the sidebar and the detail panel. */

import { lang } from "./i18n.js";

export function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key === "dataset") Object.assign(node.dataset, value);
    else if (key.startsWith("on") && typeof value === "function") {
      node.addEventListener(key.slice(2).toLowerCase(), value);
    } else node.setAttribute(key, value === true ? "" : String(value));
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

const ICON_PATHS = {
  search: '<circle cx="7" cy="7" r="4.4"/><path d="M10.4 10.4 13.6 13.6"/>',
  refresh: '<path d="M13 8a5 5 0 1 1-1.6-3.7"/><path d="M13.4 2.6v3.2h-3.2"/>',
  copy: '<rect x="5.2" y="5.2" width="8" height="8" rx="1.6"/><path d="M10.8 5.2V3.9A1.1 1.1 0 0 0 9.7 2.8H3.9A1.1 1.1 0 0 0 2.8 3.9v5.8a1.1 1.1 0 0 0 1.1 1.1h1.3"/>',
  download: '<path d="M8 2.6v7.2"/><path d="M5.2 7.2 8 10l2.8-2.8"/><path d="M2.8 12.4h10.4"/>',
  save: '<path d="M3.2 2.8h7.1l2.5 2.5v7.9H3.2z"/><path d="M5.6 2.8v4h4.2v-4"/><path d="M5.6 13.2V9.4h4.8v3.8"/>',
  image: '<rect x="2.4" y="3.2" width="11.2" height="9.6" rx="1.6"/><circle cx="5.9" cy="6.4" r="1.1"/><path d="M3 11.4 6.6 8.2l3 2.4 1.6-1.3 1.8 1.6"/>',
  star: '<path d="M8 2.4 9.8 6l3.8.5-2.8 2.7.7 3.9L8 11.3 4.5 13.1l.7-3.9L2.4 6.5 6.2 6z"/>',
  trash: '<path d="M3.4 4.6h9.2"/><path d="M6.2 4.6V3.2h3.6v1.4"/><path d="M4.6 4.6l.6 8.4h5.6l.6-8.4"/><path d="M6.8 7v3.6M9.2 7v3.6"/>',
  folder: '<path d="M2.4 4.6a1.2 1.2 0 0 1 1.2-1.2h2.6l1.2 1.4h4.9a1.2 1.2 0 0 1 1.2 1.2v5.6a1.2 1.2 0 0 1-1.2 1.2H3.6a1.2 1.2 0 0 1-1.2-1.2z"/>',
  all: '<rect x="2.6" y="2.6" width="4.6" height="4.6" rx="1.2"/><rect x="8.8" y="2.6" width="4.6" height="4.6" rx="1.2"/><rect x="2.6" y="8.8" width="4.6" height="4.6" rx="1.2"/><rect x="8.8" y="8.8" width="4.6" height="4.6" rx="1.2"/>',
  gear: '<circle cx="8" cy="8" r="2.2"/><path d="M8 1.9v1.5M8 12.6v1.5M2.6 8H1.1M14.9 8h-1.5M4.2 4.2 3.1 3.1M12.9 12.9l-1.1-1.1M11.8 4.2l1.1-1.1M3.1 12.9l1.1-1.1"/>',
  chevronLeft: '<path d="M10 3.4 5.6 8 10 12.6"/>',
  chevronRight: '<path d="M6 3.4 10.4 8 6 12.6"/>',
  zoom: '<circle cx="7.2" cy="7.2" r="4.2"/><path d="M10.3 10.3 13.4 13.4"/>',
  check: '<rect x="2.4" y="2.4" width="11.2" height="11.2" rx="2.4"/><path d="M5.2 8.2 7.2 10.2 10.9 6"/>',
  undo: '<path d="M3.2 7.4h6.1a3.3 3.3 0 1 1 0 6.6H6.2"/><path d="M5.4 4.6 2.6 7.4l2.8 2.8"/>',
  panelRight: '<rect x="1.8" y="2.8" width="7" height="10.4" rx="1.2"/><rect x="10.2" y="2.8" width="4" height="10.4" rx="1.2"/>',
  panelModal: '<rect x="2.2" y="2.6" width="11.6" height="10.8" rx="1.4"/><rect x="4.6" y="5" width="6.8" height="6" rx="1"/>',
  imageOnly: '<rect x="1.8" y="2.8" width="12.4" height="10.4" rx="1.4"/><circle cx="5.4" cy="6.2" r="1"/>',
};

export function svgIcon(name, strokeWidth = 1.4) {
  const path = ICON_PATHS[name] || "";
  const wrapper = el("span", { class: "icon", "aria-hidden": "true" });
  wrapper.innerHTML =
    `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="${strokeWidth}" ` +
    `stroke-linecap="round" stroke-linejoin="round">${path}</svg>`;
  return wrapper;
}

export function chip(text, tone = "muted", extraClass = "") {
  return el("span", { class: `chip ${extraClass}`.trim(), dataset: { tone }, text });
}

let toastTimer = null;

export function toast(message) {
  const node = document.getElementById("toast");
  if (!node) return;
  node.textContent = message;
  node.hidden = false;
  requestAnimationFrame(() => node.setAttribute("data-visible", "true"));
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    node.setAttribute("data-visible", "false");
    setTimeout(() => { node.hidden = true; }, 200);
  }, 2400);
}

export async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    // The clipboard API needs a secure context; fall back to a selection.
    const area = document.createElement("textarea");
    area.value = text;
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.append(area);
    area.select();
    const ok = document.execCommand("copy");
    area.remove();
    return ok;
  }
}

export function formatBytes(bytes) {
  if (!bytes) return "0 KB";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let index = 0;
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024;
    index += 1;
  }
  return `${value >= 10 || index === 0 ? Math.round(value) : value.toFixed(1)} ${units[index]}`;
}

const dateFormatter = new Intl.DateTimeFormat(lang === "zh" ? "zh-CN" : "en-GB", {
  year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
});

export function formatDate(epochSeconds) {
  if (!epochSeconds) return "—";
  return dateFormatter.format(new Date(epochSeconds * 1000));
}

export function formatNumber(value) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "number" && Number.isInteger(value)) {
    return value.toLocaleString(lang === "zh" ? "zh-CN" : "en-US");
  }
  return String(value);
}

export function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}
