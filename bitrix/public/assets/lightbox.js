/**
 * Full-screen image viewer.
 *
 * Hand-rolled on purpose: the panel runs under a CSP that blocks every external
 * host, so a CDN viewer library is not an option. Zoom and pan are a single CSS
 * transform, which is all this needs.
 */

import { el } from "./dom.js";

const MIN_SCALE = 1;
const MAX_SCALE = 8;
const WHEEL_SENSITIVITY = 0.0015;
const STEP = 1.4;

/**
 * @param {Array<{url: string, name?: string}>} images all images in the chat,
 *        in thread order, so the arrow keys walk the conversation
 * @param {number} startIndex which one was clicked
 */
export function openLightbox(images, startIndex = 0) {
  if (!images.length) return null;

  let index = Math.max(0, Math.min(images.length - 1, startIndex));
  let scale = 1;
  let tx = 0;
  let ty = 0;

  const img = el("img.lb__img", { alt: "", draggable: false });
  const stage = el("div.lb__stage", {}, [img]);
  const counter = el("div.lb__counter");
  const zoomLabel = el("div.lb__zoom");

  const download = el(
    "a.lb__btn",
    { title: "Download", download: "", target: "_blank", rel: "noopener" },
    ["⤓"]
  );

  const prevBtn = el("button.lb__nav.lb__nav--prev", { type: "button", title: "Pichli (←)", onclick: () => step(-1) }, ["‹"]);
  const nextBtn = el("button.lb__nav.lb__nav--next", { type: "button", title: "Agli (→)", onclick: () => step(1) }, ["›"]);

  const root = el("div.lb", { role: "dialog", "aria-modal": "true" }, [
    el("div.lb__bar", {}, [
      counter,
      el("div.lb__spacer"),
      el("button.lb__btn", { type: "button", title: "Zoom out (−)", onclick: () => zoomBy(1 / STEP) }, ["−"]),
      zoomLabel,
      el("button.lb__btn", { type: "button", title: "Zoom in (+)", onclick: () => zoomBy(STEP) }, ["+"]),
      el("button.lb__btn", { type: "button", title: "Reset (0)", onclick: reset }, ["⟲"]),
      download,
      el("button.lb__btn.lb__btn--close", { type: "button", title: "Band karein (Esc)", onclick: close }, ["✕"]),
    ]),
    prevBtn,
    stage,
    nextBtn,
  ]);

  /* --------------------------------------------------------------- render */

  function show() {
    const current = images[index];
    img.src = current.url;
    download.href = current.url;
    download.setAttribute("download", current.name || "image");
    counter.textContent = images.length > 1 ? `${index + 1} / ${images.length}` : current.name || "";
    prevBtn.hidden = images.length < 2;
    nextBtn.hidden = images.length < 2;
    reset();
  }

  function applyTransform() {
    img.style.transform = `translate(${tx}px, ${ty}px) scale(${scale})`;
    img.style.cursor = scale > 1 ? "grab" : "zoom-in";
    zoomLabel.textContent = `${Math.round(scale * 100)}%`;
  }

  function reset() {
    scale = 1;
    tx = 0;
    ty = 0;
    applyTransform();
  }

  function step(delta) {
    if (images.length < 2) return;
    index = (index + delta + images.length) % images.length;
    show();
  }

  /* ----------------------------------------------------------------- zoom */

  /** Zooms around a point so the pixel under the cursor stays put. */
  function zoomAt(factor, clientX, clientY) {
    const next = Math.max(MIN_SCALE, Math.min(MAX_SCALE, scale * factor));
    if (next === scale) return;

    const box = stage.getBoundingClientRect();
    const originX = clientX - box.left - box.width / 2;
    const originY = clientY - box.top - box.height / 2;
    const ratio = next / scale;

    tx = originX - (originX - tx) * ratio;
    ty = originY - (originY - ty) * ratio;
    scale = next;

    if (scale === MIN_SCALE) {
      tx = 0;
      ty = 0;
    }
    applyTransform();
  }

  function zoomBy(factor) {
    const box = stage.getBoundingClientRect();
    zoomAt(factor, box.left + box.width / 2, box.top + box.height / 2);
  }

  stage.addEventListener(
    "wheel",
    (event) => {
      event.preventDefault();
      zoomAt(Math.exp(-event.deltaY * WHEEL_SENSITIVITY), event.clientX, event.clientY);
    },
    { passive: false }
  );

  img.addEventListener("dblclick", (event) => {
    event.preventDefault();
    if (scale > 1) reset();
    else zoomAt(2.5, event.clientX, event.clientY);
  });

  /* ------------------------------------------------------ pan and pinch */

  const pointers = new Map();
  let pinchStart = null;

  stage.addEventListener("pointerdown", (event) => {
    if (event.target !== img && pointers.size === 0) return; // let backdrop clicks close
    pointers.set(event.pointerId, event);
    stage.setPointerCapture(event.pointerId);
    if (pointers.size === 2) pinchStart = { distance: pointerDistance(), scale };
    if (scale > 1) img.style.cursor = "grabbing";
  });

  stage.addEventListener("pointermove", (event) => {
    if (!pointers.has(event.pointerId)) return;
    const previous = pointers.get(event.pointerId);
    pointers.set(event.pointerId, event);

    if (pointers.size === 2 && pinchStart) {
      const distance = pointerDistance();
      if (distance > 0) {
        const [a, b] = [...pointers.values()];
        const target = (pinchStart.scale * distance) / pinchStart.distance;
        zoomAt(target / scale, (a.clientX + b.clientX) / 2, (a.clientY + b.clientY) / 2);
      }
      return;
    }

    if (scale > 1) {
      tx += event.clientX - previous.clientX;
      ty += event.clientY - previous.clientY;
      applyTransform();
      img.style.cursor = "grabbing";
    }
  });

  const endPointer = (event) => {
    pointers.delete(event.pointerId);
    if (pointers.size < 2) pinchStart = null;
    if (scale > 1) img.style.cursor = "grab";
  };
  stage.addEventListener("pointerup", endPointer);
  stage.addEventListener("pointercancel", endPointer);

  function pointerDistance() {
    const [a, b] = [...pointers.values()];
    return Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY);
  }

  /* -------------------------------------------------------------- close */

  // Only a click on the empty area closes; dragging the image must not.
  stage.addEventListener("click", (event) => {
    if (event.target === stage) close();
  });
  root.addEventListener("click", (event) => {
    if (event.target === root) close();
  });

  function onKey(event) {
    if (event.key === "Escape") close();
    else if (event.key === "ArrowLeft") step(-1);
    else if (event.key === "ArrowRight") step(1);
    else if (event.key === "+" || event.key === "=") zoomBy(STEP);
    else if (event.key === "-") zoomBy(1 / STEP);
    else if (event.key === "0") reset();
    else return;
    event.preventDefault();
  }

  function close() {
    document.removeEventListener("keydown", onKey, true);
    root.remove();
  }

  // Capture phase: the composer keeps focus underneath, and Esc there must
  // close the viewer rather than reach the textarea.
  document.addEventListener("keydown", onKey, true);
  document.body.append(root);
  show();
  root.focus?.();

  return { close };
}

/** Collects every ready image in a thread, in order, for arrow-key navigation. */
export function imagesInThread(messages) {
  return messages
    .filter((m) => ["image", "sticker"].includes(String(m.kind).toLowerCase()) && m.media_ready && m.media_url)
    .map((m) => ({ id: m.id, url: m.media_url, name: m.media_name || "image" }));
}
