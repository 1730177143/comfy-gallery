/* Hand a workflow over to the ComfyUI canvas.

   The gallery is a separate page from the canvas. When a canvas tab is already
   open we hand the workflow straight to it over a BroadcastChannel, and that tab
   calls app.loadGraphData() — which opens a *new* workflow tab, leaving whatever
   the user was working on untouched. Nothing navigates, so the ComfyUI page is
   never reloaded.

   Only when no canvas answers do we fall back to opening one, and only then is
   the workflow left in localStorage for the extension to pick up on boot. */

const PENDING_KEY = "comfy-gallery:pending-workflow";
const CHANNEL = "comfy-gallery";
const PING_MS = 500;
const TAB_NAME = "comfyui-canvas";

/** @returns {Promise<"sent"|"opened"|"no-workflow"|"failed">} */
export async function sendWorkflowToCanvas(workflow) {
  if (!workflow || typeof workflow !== "object") return "no-workflow";

  let channel = null;
  try {
    channel = new BroadcastChannel(CHANNEL);
  } catch {
    return stash(workflow);
  }

  const responder = await new Promise((resolve) => {
    const finish = (value) => {
      clearTimeout(timer);
      channel.removeEventListener("message", onMessage);
      resolve(value);
    };
    const onMessage = (event) => {
      const data = event.data || {};
      if (data.type === "comfy-gallery:alive" && data.id) finish(data.id);
    };
    const timer = setTimeout(() => finish(""), PING_MS);
    channel.addEventListener("message", onMessage);
    channel.postMessage({ type: "comfy-gallery:who" });
  });

  if (responder) {
    // Addressed to the canvas that answered first, so several open ComfyUI tabs
    // cannot all load the same workflow.
    channel.postMessage({ type: "comfy-gallery:open", workflow, target: responder });
    setTimeout(() => channel.close(), 1000);
    return "sent";
  }

  channel.close();
  return stash(workflow);
}

function stash(workflow) {
  try {
    localStorage.setItem(PENDING_KEY, JSON.stringify({ workflow, at: Date.now() }));
  } catch {
    return "failed";
  }
  // Reuses a canvas tab opened by an earlier send, otherwise opens one.
  window.open("/", TAB_NAME);
  return "opened";
}
