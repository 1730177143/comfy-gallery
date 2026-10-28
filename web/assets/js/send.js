/* Hand a workflow over to the ComfyUI canvas.

   The gallery is a separate page from the canvas, so the workflow travels
   through localStorage: this page writes it, then opens (or focuses) the ComfyUI
   tab, whose own extension picks it up on load or through a storage event. */

const PENDING_KEY = "comfy-gallery:pending-workflow";
const TAB_NAME = "comfyui-canvas";

export function sendWorkflowToCanvas(workflow) {
  if (!workflow || typeof workflow !== "object") return false;
  try {
    localStorage.setItem(PENDING_KEY, JSON.stringify({ workflow, at: Date.now() }));
  } catch {
    return false;
  }
  // Reuses a tab opened by an earlier send; otherwise a fresh canvas tab loads
  // the pending workflow during its own start-up.
  window.open("/", TAB_NAME);
  return true;
}
