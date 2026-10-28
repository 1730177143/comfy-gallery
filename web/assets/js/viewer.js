/* Full-screen image viewer with stepping.

   Used both as the "image only" detail mode and as the zoom target from the
   detail panel, so it owns its own navigation buttons and click-outside close. */

import { el, clear } from "./dom.js";
import { fileUrl } from "./api.js";

export function createViewer({
  lightbox, canvas, closeButton, prevButton, nextButton,
  onStep, wheelEnabled, clickClose,
}) {
  let open = false;
  let lastWheel = 0;
  let image = null;
  let token = 0;

  function close() {
    lightbox.hidden = true;
    open = false;
    token += 1;                 // cancel any in-flight decode
    if (image) {
      image.remove();
      image = null;
    }
    clear(canvas);
  }

  async function show(id) {
    const url = fileUrl(id);
    const mine = ++token;

    if (!image) {
      // First open: nothing to preserve, so the element can start loading at once.
      image = el("img", { src: url, alt: "" });
      canvas.append(image);
      lightbox.hidden = false;
      open = true;
      closeButton.focus();
      return;
    }

    lightbox.hidden = false;
    open = true;

    // Decode the next picture off-screen and only then swap it in. Replacing the
    // src of a live element makes the browser blank it while it loads, which is
    // the flicker you see when stepping with the wheel.
    try {
      const preload = new Image();
      preload.src = url;
      await preload.decode();
    } catch {
      /* decode() can reject for huge or unusual files; the swap below still works */
    }
    if (mine !== token || !image) return;   // a newer step won the race
    image.src = url;
  }

  closeButton.addEventListener("click", close);

  // Clicking anything that is not the picture leaves the viewer — but the
  // navigation arrows must keep stepping instead of closing it.
  lightbox.addEventListener("click", (event) => {
    if (!open) return;
    if (event.target === image) return;
    if (event.target.closest?.(".lightbox-nav")) return;
    if (clickClose && !clickClose()) return;
    close();
  });

  prevButton.addEventListener("click", () => onStep(-1));
  nextButton.addEventListener("click", () => onStep(1));

  // Optional wheel navigation, off unless the user turns it on: scrolling is the
  // expected behaviour and a stray tick should not swap the picture.
  // One image per gesture — a trackpad or a fast wheel fires a burst of events,
  // and stepping on each of them would fly through the library.
  lightbox.addEventListener("wheel", (event) => {
    if (!open || !wheelEnabled?.()) return;
    event.preventDefault();
    const now = Date.now();
    if (now - lastWheel < 240) return;
    if (Math.abs(event.deltaY) < 4) return;
    lastWheel = now;
    onStep(event.deltaY > 0 ? 1 : -1);
  }, { passive: false });

  return {
    open: show,
    close,
    get isOpen() { return open; },
  };
}
