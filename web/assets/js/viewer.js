/* Full-screen image viewer with stepping.

   Used both as the "image only" detail mode and as the zoom target from the
   detail panel, so it owns its own navigation buttons and click-outside close. */

import { el, clear } from "./dom.js";
import { fileUrl } from "./api.js";

export function createViewer({ lightbox, canvas, closeButton, prevButton, nextButton, onStep, wheelEnabled }) {
  let open = false;
  let lastWheel = 0;

  function show(id) {
    clear(canvas);
    canvas.append(el("img", { src: fileUrl(id), alt: "" }));
    lightbox.hidden = false;
    open = true;
    closeButton.focus();
  }

  function close() {
    lightbox.hidden = true;
    open = false;
    clear(canvas);
  }

  closeButton.addEventListener("click", close);
  lightbox.addEventListener("click", (event) => {
    if (event.target === lightbox) close();
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
