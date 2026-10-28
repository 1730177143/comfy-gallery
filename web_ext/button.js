/**
 * Adds the Gallery button to ComfyUI's own toolbar.
 *
 * The action bar API is the supported path on current frontends; older builds
 * get the same button inserted next to the settings group instead. The fallback
 * is decided by looking for the button the action bar was supposed to create,
 * so a frontend that silently ignores the API still ends up with a button.
 */
import { app } from "../../scripts/app.js";

const TOOLTIP = "Launch Gallery (Shift+Click opens in new window)";
const GALLERY_PATH = "/gallery";
const NEW_WINDOW = "width=1440,height=960,resizable=yes,scrollbars=yes,status=yes";
const BUTTON_GROUP_CLASS = "comfy-gallery-top-menu-group";
// The gallery page hands a workflow over through localStorage; see
// web/assets/js/send.js for the writing half.
const PENDING_KEY = "comfy-gallery:pending-workflow";
const PENDING_TTL = 60000;
const MAX_ATTACH_ATTEMPTS = 120;

const GALLERY_ICON = `
<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.3"
     stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
  <rect x="1.8" y="2.6" width="5.2" height="4.4" rx="1.1"/>
  <rect x="9" y="2.6" width="5.2" height="6.6" rx="1.1"/>
  <rect x="1.8" y="8.4" width="5.2" height="5" rx="1.1"/>
  <rect x="9" y="10.6" width="5.2" height="2.8" rx="1.1"/>
</svg>`;

function openGallery(event) {
  const url = `${window.location.origin}${GALLERY_PATH}`;
  if (event?.shiftKey) {
    window.open(url, "_blank", NEW_WINDOW);
    return;
  }
  window.open(url, "_blank");
}

function actionBarButtonExists() {
  return Boolean(document.querySelector(`button[aria-label="${TOOLTIP}"]`));
}

async function attachLegacyButton(attempt = 0) {
  if (document.querySelector(`.${BUTTON_GROUP_CLASS}`)) return;

  const settingsGroup = app.menu?.settingsGroup;
  if (!settingsGroup?.element?.parentElement) {
    if (attempt >= MAX_ATTACH_ATTEMPTS) {
      console.warn("comfy-gallery: could not find ComfyUI's settings button group");
      return;
    }
    requestAnimationFrame(() => attachLegacyButton(attempt + 1));
    return;
  }

  const { ComfyButton } = await import("../../scripts/ui/components/button.js");
  const { ComfyButtonGroup } = await import("../../scripts/ui/components/buttonGroup.js");

  const button = new ComfyButton({
    icon: "comfyui-gallery",
    tooltip: TOOLTIP,
    app,
    enabled: true,
    classList: "comfyui-button comfyui-menu-mobile-collapse primary",
  });
  button.element.setAttribute("aria-label", TOOLTIP);
  button.element.title = TOOLTIP;

  if (button.iconElement) {
    button.iconElement.innerHTML = GALLERY_ICON;
    button.iconElement.style.width = "1.15rem";
    button.iconElement.style.height = "1.15rem";
  }

  button.element.addEventListener("click", openGallery);

  const group = new ComfyButtonGroup(button);
  group.element.classList.add(BUTTON_GROUP_CLASS);
  settingsGroup.element.before(group.element);
}

async function loadPendingWorkflow() {
  let raw = null;
  try {
    raw = localStorage.getItem(PENDING_KEY);
  } catch {
    return;
  }
  if (!raw) return;
  try {
    localStorage.removeItem(PENDING_KEY);
  } catch {
    /* nothing to clean up */
  }

  let payload = null;
  try {
    payload = JSON.parse(raw);
  } catch {
    return;
  }
  if (!payload || !payload.workflow) return;
  if (Date.now() - (payload.at || 0) > PENDING_TTL) return;   // stale send

  // The canvas may still be initialising when a fresh tab opens.
  for (let attempt = 0; attempt < 40; attempt += 1) {
    if (typeof app.loadGraphData === "function" && app.graph) {
      try {
        await app.loadGraphData(payload.workflow);
      } catch (error) {
        console.warn("comfy-gallery: could not load the sent workflow", error);
      }
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
}

app.registerExtension({
  name: "Comfy.Gallery.TopBar",
  actionBarButtons: [
    {
      icon: "icon-[lucide--images] size-4",
      tooltip: TOOLTIP,
      onClick: openGallery,
    },
  ],
  async setup() {
    loadPendingWorkflow();
    window.addEventListener("storage", (event) => {
      if (event.key === PENDING_KEY) loadPendingWorkflow();
    });

    // The action bar mounts asynchronously; give Vue a few frames to render it
    // before deciding the API was not honoured.
    for (let frame = 0; frame < 12; frame += 1) {
      if (actionBarButtonExists()) return;
      await new Promise((resolve) => requestAnimationFrame(resolve));
    }
    await attachLegacyButton();
  },
});
