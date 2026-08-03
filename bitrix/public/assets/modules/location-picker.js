/**
 * Location Picker Modal: send property pins & parse Google Maps links.
 */

import { el, modal } from "../core/dom.js";
import { icon } from "../core/icons.js";

export function openLocationModal({ onSendLocation }) {
  const mapsLinkInput = el("input.field", {
    type: "text",
    placeholder: "e.g. https://maps.google.com/?q=25.0657,55.1713",
  });

  const latInput = el("input.field", { type: "number", step: "any", placeholder: "e.g. 25.0657" });
  const lngInput = el("input.field", { type: "number", step: "any", placeholder: "e.g. 55.1713" });
  const nameInput = el("input.field", { type: "text", placeholder: "e.g. Damac Hills 2 Sales Centre" });
  const addressInput = el("input.field", { type: "text", placeholder: "e.g. Dubailand, Dubai" });

  const errorEl = el("div.alert", { hidden: true });
  const sendBtn = el("button.btn.btn--primary", { type: "button" }, [
    icon("mapPin", { size: 15 }),
    " Send Location Pin",
  ]);

  // Google Maps URL parser helper
  mapsLinkInput.addEventListener("input", () => {
    const val = mapsLinkInput.value.trim();
    if (!val) return;

    // Pattern 1: @25.0657,55.1713
    let match = val.match(/@(-?\d+\.\d+),(-?\d+\.\d+)/);
    if (!match) {
      // Pattern 2: ?q=25.0657,55.1713 or ll=25.0657,55.1713
      match = val.match(/[?&](?:q|ll)=(-?\d+\.\d+),(-?\d+\.\d+)/);
    }
    if (!match) {
      // Pattern 3: plain coordinates 25.0657, 55.1713
      match = val.match(/(-?\d+\.\d+)[\s,]+(-?\d+\.\d+)/);
    }

    if (match) {
      latInput.value = match[1];
      lngInput.value = match[2];
      errorEl.hidden = true;
    }
  });

  const form = el("div.tplc-form", { style: "gap: 12px;" }, [
    el("label.tplc-field", {}, [
      el("span", {}, ["Paste Google Maps Link (Auto Extract)"]),
      mapsLinkInput,
      el("span", { style: "font-size: 11px; opacity: 0.7;" }, ["Paste any Google Maps link or coordinates to auto-fill lat/lng"]),
    ]),
    el("div", { style: "display: grid; grid-template-columns: 1fr 1fr; gap: 10px;" }, [
      el("label.tplc-field", {}, [el("span", {}, ["Latitude *"]), latInput]),
      el("label.tplc-field", {}, [el("span", {}, ["Longitude *"]), lngInput]),
    ]),
    el("label.tplc-field", {}, [el("span", {}, ["Location Name (Optional)"]), nameInput]),
    el("label.tplc-field", {}, [el("span", {}, ["Address (Optional)"]), addressInput]),
    errorEl,
    el("div.tplc-actions", {}, [sendBtn]),
  ]);

  const dialog = modal("Send Location Pin", form);

  sendBtn.addEventListener("click", async () => {
    const lat = parseFloat(latInput.value);
    const lng = parseFloat(lngInput.value);

    if (isNaN(lat) || lat < -90 || lat > 90) {
      errorEl.textContent = "Please enter a valid Latitude (-90 to 90).";
      errorEl.hidden = false;
      return;
    }
    if (isNaN(lng) || lng < -180 || lng > 180) {
      errorEl.textContent = "Please enter a valid Longitude (-180 to 180).";
      errorEl.hidden = false;
      return;
    }

    sendBtn.disabled = true;
    sendBtn.textContent = "Sending location…";
    errorEl.hidden = true;

    try {
      await onSendLocation({
        latitude: lat,
        longitude: lng,
        name: nameInput.value.trim() || undefined,
        address: addressInput.value.trim() || undefined,
      });
      dialog.close();
    } catch (err) {
      sendBtn.disabled = false;
      sendBtn.replaceChildren(icon("mapPin", { size: 15 }), " Send Location Pin");
      errorEl.textContent = err.message || "Failed to send location pin.";
      errorEl.hidden = false;
    }
  });

  return dialog;
}
