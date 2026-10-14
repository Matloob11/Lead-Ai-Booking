/**
 * Shop media in the Lead AI screen (board T30): what the assistant sends when a
 * shops customer picks a shop type (the type's video, then its photos in this
 * order, then its details card), and the office photo.
 *
 * GET /api/leadai/shop-media/ for every agent. A panel admin (can_edit) adds,
 * replaces, deletes and reorders the files; the server checks each one by its
 * bytes (an MP4 with H.264 video up to 16 MB, a JPEG or PNG photo up to 5 MB;
 * one video and up to six photos per type, one office photo) and answers why it
 * refused one, which is shown as it came.
 *
 * File names are whatever the uploader's computer called them: every text here
 * goes in through el() as text, never as HTML.
 */

import { el, clear, formatBytes, toast } from "../../core/dom.js";
import { icon } from "../../core/icons.js";
import { leadAiApi } from "./api.js";
import { screenModal } from "./thread.js";

const FILE_URL = /^\/api\/leadai\/shop-media\/\d+\/file\/$/;
const ACCEPT = { video: "video/mp4", photo: "image/jpeg,image/png" };
// A second click within this long confirms a delete.
const CONFIRM_MS = 6000;

let dialog = null;

/** Closes the dialog if it is open (the screen it belongs to is closing). */
export function closeShopMediaDialog() {
  dialog?.close();
}

export function openShopMediaDialog() {
  if (dialog) return;
  const body = el("div.lai-set.lai-media", {}, [el("p.lai-set__note", {}, ["Loading…"])]);
  const self = screenModal("Shop media", body, {
    wide: true,
    onClose: () => {
      if (dialog === self) dialog = null;
    },
  });
  self.box.classList.add("lai-modal--settings", "lai-modal--media");
  dialog = self;
  const status = el("p.lai-set__note.lai-media__status", { role: "status" });
  let busy = false;
  let last = null; // the library as last drawn, drawn again after a refusal

  load();

  async function load() {
    try {
      const data = await leadAiApi.shopMedia();
      if (dialog === self) render(data);
    } catch (error) {
      if (dialog !== self) return;
      clear(body).append(el("p.lai-set__note.lai-set__note--err", {}, [`Could not load the shop media: ${error.message}`]));
    }
  }

  /** One change at a time; the answer is the whole library, drawn again. */
  async function change(work, done) {
    if (busy) return;
    busy = true;
    body.setAttribute("aria-busy", "true");
    for (const node of body.querySelectorAll("button, input")) node.disabled = true;
    say("");
    try {
      const data = await work();
      if (dialog !== self) return;
      render(data);
      if (done) toast(done);
    } catch (error) {
      if (dialog !== self) return;
      if (last) render(last);
      say(error?.message || "That did not work.", true);
    } finally {
      busy = false;
      body.removeAttribute("aria-busy");
    }
  }

  function say(text, isError = false) {
    status.textContent = text;
    status.classList.toggle("lai-set__note--err", Boolean(text) && isError);
  }

  function render(data) {
    if (!data || typeof data !== "object") return;
    last = data;
    const canEdit = Boolean(data.can_edit);
    const limits = data.limits || {};
    const groups = Array.isArray(data.shops) ? data.shops : [];
    clear(body).append(
      el("p.lai-set__p", {}, [
        "When a shops customer picks a type, the assistant sends its video first, then its photos in the order below, then the type's details.",
      ]),
      el("p.lai-set__hint", {}, [
        `Videos: MP4 (H.264), at most ${Number(limits.video_mb) || 16} MB. Photos: JPEG or PNG, at most ${Number(limits.photo_mb) || 5} MB. ` +
          "Each type takes one video and up to six photos; the office takes one photo.",
      ]),
      ...groups.map((group) => groupSection(group, canEdit)),
      canEdit ? null : el("p.lai-set__note", {}, ["Only a panel admin can change the shop media."]),
      status
    );
  }

  function groupSection(group, canEdit) {
    const items = Array.isArray(group.items) ? group.items : [];
    const videos = items.filter((item) => item.kind === "video");
    const photos = items.filter((item) => item.kind === "photo");
    const room = group.limits || {};
    const counts = [];
    if (Number(room.videos) > 0) counts.push(`${videos.length} of ${room.videos} video`);
    counts.push(`${photos.length} of ${Number(room.photos) || 0} ${Number(room.photos) === 1 ? "photo" : "photos"}`);
    const label = String(group.label || group.shop || "");
    const list = items.length
      ? el(
          "ol.lai-media__list",
          {},
          items.map((item, index) => fileRow(group, item, index + 1, photos, videos, canEdit))
        )
      : el("p.lai-set__hint.lai-media__empty", {}, ["No files yet."]);
    const full = videos.length >= (Number(room.videos) || 0) && photos.length >= (Number(room.photos) || 0);
    return el("section.lai-set__section.lai-media__group", {}, [
      el("div.lai-media__head", {}, [
        el("h3.lai-set__h", {}, [label]),
        el("span.lai-media__count", {}, [counts.join(" · ")]),
      ]),
      list,
      canEdit ? addControl(group, label, full, Number(room.videos) > 0) : null,
    ]);
  }

  function fileRow(group, item, position, photos, videos, canEdit) {
    const name = String(item.file_name || "file");
    const isVideo = item.kind === "video";
    const url = FILE_URL.test(String(item.url || "")) ? item.url : "";
    const preview = !isVideo && url
      ? el("img.lai-media__thumb", { src: url, alt: "", loading: "lazy", decoding: "async" })
      : el("span.lai-media__thumb.lai-media__thumb--icon", { "aria-hidden": "true" }, [icon(isVideo ? "video" : "image", { size: 18 })]);
    const facts = [isVideo ? "Video" : "Photo", formatBytes(item.size_bytes)].filter(Boolean);
    if (item.uploaded_by) facts.push(`by ${String(item.uploaded_by)}`);
    const actions = canEdit ? rowActions(group, item, name, photos, videos) : null;
    return el("li.lai-media__item", {}, [
      el("span.lai-media__pos", { "aria-label": `Sent as number ${position}` }, [String(position)]),
      preview,
      el("span.lai-media__body", {}, [
        url
          ? el("a.lai-media__name", { href: url, target: "_blank", rel: "noopener noreferrer", title: "Open the file" }, [name])
          : el("span.lai-media__name", {}, [name]),
        el("span.lai-media__meta", {}, [facts.join(" · ")]),
      ]),
      actions,
    ]);
  }

  function rowActions(group, item, name, photos, videos) {
    const nodes = [];
    if (item.kind === "photo") {
      const at = photos.findIndex((photo) => photo.id === item.id);
      const move = (step) => {
        const order = photos.map((photo) => photo.id);
        [order[at], order[at + step]] = [order[at + step], order[at]];
        // The video always goes first; the server wants every file of the shop once.
        const ids = [...videos.map((video) => video.id), ...order];
        change(() => leadAiApi.reorderShopMedia(group.shop, ids));
      };
      nodes.push(
        el("button.lai-btn.lai-btn--ghost.lai-btn--sm", {
          type: "button",
          disabled: at <= 0,
          "aria-label": `Move ${name} up`,
          title: "Send it earlier",
          onclick: () => move(-1),
        }, ["Up"]),
        el("button.lai-btn.lai-btn--ghost.lai-btn--sm", {
          type: "button",
          disabled: at < 0 || at >= photos.length - 1,
          "aria-label": `Move ${name} down`,
          title: "Send it later",
          onclick: () => move(1),
        }, ["Down"])
      );
    }
    const picker = el("input.lai-media__file", {
      type: "file",
      accept: ACCEPT[item.kind] || ACCEPT.photo,
      hidden: true,
      onchange: () => {
        const file = picker.files?.[0];
        picker.value = "";
        if (file) change(() => leadAiApi.replaceShopMedia(item.id, file), "File replaced.");
      },
    });
    nodes.push(
      picker,
      el("button.lai-btn.lai-btn--ghost.lai-btn--sm", {
        type: "button",
        "aria-label": `Replace ${name}`,
        title: "Put another file in its place",
        onclick: () => picker.click(),
      }, ["Replace"])
    );
    let armed = null;
    const remove = el("button.lai-btn.lai-btn--ghost.lai-btn--sm.lai-media__delete", {
      type: "button",
      "aria-label": `Delete ${name}`,
      title: "Take it out of the library",
      onclick: () => {
        if (!armed) {
          // A second click confirms: nothing is deleted by one stray click.
          remove.textContent = "Delete?";
          remove.classList.add("is-armed");
          armed = setTimeout(() => {
            armed = null;
            remove.replaceChildren(icon("trash", { size: 13 }), "Delete");
            remove.classList.remove("is-armed");
          }, CONFIRM_MS);
          return;
        }
        clearTimeout(armed);
        armed = null;
        change(() => leadAiApi.deleteShopMedia(item.id), "File deleted. Messages already sent keep it.");
      },
    }, [icon("trash", { size: 13 }), "Delete"]);
    nodes.push(remove);
    return el("span.lai-media__actions", {}, nodes);
  }

  function addControl(group, label, full, takesVideo) {
    const picker = el("input.lai-media__file", {
      type: "file",
      accept: takesVideo ? `${ACCEPT.video},${ACCEPT.photo}` : ACCEPT.photo,
      hidden: true,
      onchange: () => {
        const file = picker.files?.[0];
        picker.value = "";
        if (file) change(() => leadAiApi.addShopMedia(group.shop, file), "File added.");
      },
    });
    return el("div.lai-set__actions.lai-set__actions--start", {}, [
      picker,
      el("button.lai-btn.lai-btn--sm", {
        type: "button",
        disabled: full,
        title: full ? "This one is full: replace or delete a file first." : "",
        onclick: () => picker.click(),
      }, [icon("plus", { size: 13 }), takesVideo ? `Add a video or photo to ${label}` : `Add the ${label.toLowerCase()} photo`]),
    ]);
  }
}
