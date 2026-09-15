/**
 * Rich media bubbles for the Official API thread — voice, image, video, documents.
 * Kept out of inbox.js so message rendering can evolve without widening a shared file.
 */

import { el, clear } from "./dom.js";
import { icon, iconForKind } from "./icons.js";
import { createVoicePlayer } from "./voice-player.js";

function imageNode(message, onImageClick) {
  const wrap = el("div.msg__image-wrap");
  const skeleton = el("div.msg__image-skeleton", { "aria-hidden": "true" });
  const img = el("img.msg__image", {
    src: message.media_url,
    alt: message.media_name || "Photo",
    loading: "lazy",
    title: "View full size",
  });

  img.addEventListener("load", () => skeleton.remove());
  img.addEventListener("error", () => {
    wrap.replaceWith(
      el("div.msg__media-failed", {}, [
        icon("alert", { size: 15 }),
        "Photo could not be loaded",
      ])
    );
  });
  img.addEventListener("click", () => onImageClick?.(message));

  wrap.append(skeleton, img);
  return wrap;
}

function videoNode(message) {
  const video = el("video.msg__video", {
    src: message.media_url,
    controls: true,
    preload: "metadata",
    playsInline: true,
  });

  video.addEventListener("error", () => {
    video.replaceWith(
      el("div.msg__media-failed", {}, [
        icon("alert", { size: 15 }),
        "Video could not be loaded",
      ])
    );
  });

  return el("div.msg__video-wrap", {}, [
    el("div.msg__video-badge", {}, [icon("video", { size: 14 }), "Video"]),
    video,
  ]);
}

function docKind(name) {
  const ext = String(name || "")
    .split(".")
    .pop()
    ?.toLowerCase();
  if (ext === "pdf") return { label: "PDF", mod: "pdf", iconName: "fileText" };
  if (["doc", "docx"].includes(ext)) return { label: "Word", mod: "word", iconName: "fileText" };
  if (["xls", "xlsx", "csv"].includes(ext)) return { label: "Spreadsheet", mod: "sheet", iconName: "fileText" };
  if (["ppt", "pptx"].includes(ext)) return { label: "Presentation", mod: "slide", iconName: "fileText" };
  if (["zip", "rar", "7z"].includes(ext)) return { label: "Archive", mod: "zip", iconName: "file" };
  return { label: "Document", mod: "file", iconName: "file" };
}

function documentNode(message, formatBytes) {
  const name = message.media_name || "Document";
  const kind = docKind(name);
  const ext = String(name).split(".").pop()?.toUpperCase();
  const size = formatBytes?.(message.media_size);
  const sub = [kind.label !== "Document" ? kind.label : ext && ext.length <= 5 ? ext : null, size]
    .filter(Boolean)
    .join(" · ") || "Download";

  return el(
    "a.msg__doc",
    {
      href: message.media_url,
      target: "_blank",
      rel: "noopener",
      download: name,
      class: `msg__doc--${kind.mod}`,
    },
    [
      el("div.msg__doc-icon", { class: `msg__doc-icon--${kind.mod}` }, [
        icon(kind.iconName, { size: 22 }),
      ]),
      el("div.msg__doc-meta", {}, [
        el("div.msg__doc-name", { title: name }, [name]),
        el("div.msg__doc-sub", {}, [sub]),
      ]),
      el("div.msg__doc-dl", { title: "Open file" }, [icon("download", { size: 17 })]),
    ]
  );
}

const SENT_MEDIA_LABEL = {
  image: "Photo",
  sticker: "Sticker",
  video: "Video",
  audio: "Voice message",
  document: "Document",
};

/**
 * @param {object} message inbox message row
 * @param {{ onImageClick?: Function, formatBytes?: Function }} handlers
 */
export function mediaMessageNode(message, { onImageClick, formatBytes } = {}) {
  const kind = String(message.kind || "").toLowerCase();
  if (!["image", "audio", "video", "document", "sticker"].includes(kind)) return null;

  if (message.media_failed) {
    const label =
      kind === "audio"
        ? "Voice message unavailable"
        : kind === "image" || kind === "sticker"
          ? "Photo unavailable"
          : kind === "video"
            ? "Video unavailable"
            : "File unavailable";
    return el("div.msg__media-failed", {}, [
      iconForKind(kind, { size: 16 }) || icon("alert", { size: 15 }),
      label,
      el("span.msg__media-failed-hint", {}, ["Media was not saved on the server"]),
    ]);
  }

  if (!message.media_url) {
    if (message.direction === "out") {
      return el("div.msg__sent-media", {}, [
        iconForKind(kind, { size: 16 }) || icon("paperclip", { size: 16 }),
        el("span.msg__sent-media-label", {}, [`${SENT_MEDIA_LABEL[kind] || "File"} sent`]),
        el("span.msg__sent-media-hint", {}, ["Sent from this panel — preview not stored"]),
      ]);
    }
    return el("div.msg__pending", {}, [
      el("span.spinner.spinner--sm"),
      kind === "audio" ? "Downloading voice message…" : "Downloading attachment…",
    ]);
  }

  if (!message.media_ready) {
    return el("div.msg__pending", {}, [
      el("span.spinner.spinner--sm"),
      kind === "audio" ? "Downloading voice message…" : "Downloading attachment…",
    ]);
  }

  const outbound = message.direction === "out";

  if (kind === "image" || kind === "sticker") return imageNode(message, onImageClick);
  if (kind === "audio") {
    const name = message.media_name || "voice-message.ogg";
    return createVoicePlayer({
      src: message.media_url,
      downloadName: name,
      outbound: message.direction === "out",
    });
  }
  if (kind === "video") return videoNode(message);
  return documentNode(message, formatBytes);
}
