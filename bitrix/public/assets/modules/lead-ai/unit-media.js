/**
 * Apartment photos in the Lead AI screen (batch 2e slice E, board T96): the studio and one-bedroom photo sets the
 * assistant sends on the rent track, by unit.
 *
 * Every set is the same type of unit, never the exact one (Q36): a studio customer gets a studio set and a
 * one-bedroom customer a one-bedroom set: the set whose listing refs hold the lead's listing ref (the photos they
 * saw on the portal), else the unit's default. The first photo goes with a caption that says so.
 *
 * GET /api/leadai/unit-media/ for every agent. Read only: the sets change only by their import
 * (`ops/wa.sh leadai-media-import`, from each set's set.json), never here. Set names are folder names and every
 * text goes in through el() as text, never as HTML.
 */

import { apiFetch } from "../../core/bitrix-sso.js";
import { clear, el, formatBytes } from "../../core/dom.js";
import { icon } from "../../core/icons.js";
import { screenModal } from "./thread.js";

const SETS_URL = "/api/leadai/unit-media/";
const FILE_URL = /^\/api\/leadai\/unit-media\/\d+\/file\/$/;
const REF = /^a7group-\d{1,6}$/;
const UNIT_WORDS = { studio: "Studio", one_br: "One-bedroom" };

let dialog = null;

/** The bar's button that opens the sets (screen.js puts it beside Shop media). */
export function unitMediaButton() {
  return el("button.lai-btn.lai-btn--ghost.lai-bar__media.lai-um-open", {
    type: "button",
    title: "The studio and one-bedroom photos the assistant sends to rent customers",
    onclick: () => openUnitMediaDialog(),
  }, [icon("album", { size: 15 }), "Apartment photos"]);
}

/** Closes the dialog if it is open (the screen it belongs to is closing). */
export function closeUnitMediaDialog() {
  dialog?.close();
}

export function openUnitMediaDialog() {
  if (dialog) return;
  const body = el("div.lai-set.lai-um", {}, [el("p.lai-set__note", {}, ["Loading…"])]);
  const self = screenModal("Apartment photos", body, {
    wide: true,
    onClose: () => {
      if (dialog === self) dialog = null;
    },
  });
  self.box.classList.add("lai-modal--settings", "lai-modal--media");
  dialog = self;
  load();

  async function load() {
    try {
      const data = await apiFetch(SETS_URL);
      if (dialog === self) render(data);
    } catch (error) {
      if (dialog !== self) return;
      clear(body).append(el("p.lai-set__note.lai-set__note--err", {}, [`Could not load the apartment photos: ${error.message}`]));
    }
  }

  function render(data) {
    if (!data || typeof data !== "object") return;
    const limits = data.limits || {};
    const units = Array.isArray(data.units) ? data.units : [];
    const captions = data.captions && typeof data.captions === "object" ? data.captions : {};
    clear(body).append(
      el("p.lai-set__p", {}, [
        "When a rent customer asks for photos, or confirms their unit and cluster, the assistant sends one set of their unit: " +
          "the set of the listing they enquired on, else the unit's default. Then it asks one question, usually to visit.",
      ]),
      el("p.lai-set__hint", {}, [
        "Every set shows the same type of unit, never the exact one: our agent shows the exact unit at the viewing. " +
          `A set holds up to ${Number(limits.photos) || 5} photos. Sets change only by their import (set.json), not here.`,
      ]),
      ...units.map((group) => unitSection(group, String(captions[group.unit] || ""))),
    );
  }

  function unitSection(group, caption) {
    const sets = Array.isArray(group.sets) ? group.sets : [];
    const label = String(group.label || UNIT_WORDS[group.unit] || group.unit || "");
    return el("section.lai-set__section.lai-um__unit", {}, [
      el("div.lai-media__head", {}, [
        el("h3.lai-set__h", {}, [label]),
        el("span.lai-media__count", {}, [`${sets.length} ${sets.length === 1 ? "set" : "sets"}`]),
      ]),
      caption ? el("p.lai-um__caption", {}, [el("span.lai-um__caption-label", {}, ["Caption on the first photo: "]), caption]) : null,
      sets.length ? el("ul.lai-um__sets", {}, sets.map(setCard)) : el("p.lai-set__hint.lai-media__empty", {}, ["No set imported yet: a customer who asks for photos is told we have none approved yet and invited to visit."]),
    ]);
  }

  function setCard(item) {
    const files = Array.isArray(item.files) ? item.files : [];
    const refs = (Array.isArray(item.for_listing_refs) ? item.for_listing_refs : []).map(String).filter((ref) => REF.test(ref));
    const marks = [el("span.lai-um__mark", {}, [String(item.label_text || item.label || "")])];
    if (item.default_for_unit) marks.unshift(el("span.lai-um__mark.lai-um__mark--default", {}, ["Default for the unit"]));
    if (item.sendable === false) marks.push(el("span.lai-um__mark.lai-um__mark--off", {}, ["Not sent"]));
    const facts = [];
    if (refs.length) facts.push(`For leads on ${refs.join(", ")}`);
    if (item.cluster) facts.push(`Cluster ${String(item.cluster)}`);
    const built = builtOn(item.verified_at);
    if (built) facts.push(`Built ${built}`);
    return el("li.lai-um__set", {}, [
      el("div.lai-um__set-head", {}, [el("span.lai-um__name", {}, [String(item.name || "")]), el("span.lai-um__marks", {}, marks)]),
      facts.length ? el("p.lai-media__meta", {}, [facts.join(" · ")]) : null,
      el("ol.lai-um__photos", {}, files.map((file, index) => photo(file, index + 1))),
    ]);
  }

  function photo(file, position) {
    const url = FILE_URL.test(String(file.url || "")) ? file.url : "";
    const isVideo = file.kind === "video";
    const name = String(file.file_name || "file");
    const preview = !isVideo && url
      ? el("img.lai-um__thumb", { src: url, alt: "", loading: "lazy", decoding: "async" })
      : el("span.lai-um__thumb.lai-media__thumb--icon", { "aria-hidden": "true" }, [icon(isVideo ? "video" : "image", { size: 18 })]);
    const link = url ? el("a.lai-um__link", { href: url, target: "_blank", rel: "noopener noreferrer", title: `${name} · ${formatBytes(file.size_bytes)}` }, [preview]) : preview;
    return el("li.lai-um__photo", { "aria-label": `Sent as number ${position}` }, [link, el("span.lai-um__pos", {}, [String(position)])]);
  }
}

function builtOn(value) {
  const day = String(value || "").slice(0, 10);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) return "";
  const [year, month, date] = day.split("-").map(Number);
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return `${date} ${months[month - 1] || ""} ${year}`.trim();
}
