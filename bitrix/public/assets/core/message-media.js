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
  const mime = String(message.media_mime || "");
  // A template send stores its header file on the same row. The bubble kind
  // stays "template" (body and buttons), and the picture is drawn above it.
  let headerKind = "";
  if (kind === "template" && message.media_url) {
    if (mime.startsWith("video/")) headerKind = "video";
    else if (mime.startsWith("audio/")) headerKind = "audio";
    else if (mime.startsWith("image/")) headerKind = "image";
    else headerKind = "document";
  }
  if (kind === "template" && !headerKind) return null;
  const showKind = headerKind || kind;
  if (!["image", "audio", "video", "document", "sticker"].includes(showKind)) return null;

  if (message.media_failed) {
    const label =
      showKind === "audio"
        ? "Voice message unavailable"
        : showKind === "image" || showKind === "sticker"
          ? "Photo unavailable"
          : showKind === "video"
            ? "Video unavailable"
            : "File unavailable";
    return el("div.msg__media-failed", {}, [
      iconForKind(showKind, { size: 16 }) || icon("alert", { size: 15 }),
      label,
      el("span.msg__media-failed-hint", {}, ["Media was not saved on the server"]),
    ]);
  }

  if (!message.media_url) {
    if (message.direction === "out") {
      return el("div.msg__sent-media", {}, [
        iconForKind(showKind, { size: 16 }) || icon("paperclip", { size: 16 }),
        el("span.msg__sent-media-label", {}, [`${SENT_MEDIA_LABEL[showKind] || "File"} sent`]),
        el("span.msg__sent-media-hint", {}, ["Sent from this panel — preview not stored"]),
      ]);
    }
    return el("div.msg__pending", {}, [
      el("span.spinner.spinner--sm"),
      showKind === "audio" ? "Downloading voice message…" : "Downloading attachment…",
    ]);
  }

  if (!message.media_ready) {
    return el("div.msg__pending", {}, [
      el("span.spinner.spinner--sm"),
      showKind === "audio" ? "Downloading voice message…" : "Downloading attachment…",
    ]);
  }

  if (showKind === "image" || showKind === "sticker") return imageNode(message, onImageClick);
  if (showKind === "audio") {
    const name = message.media_name || "voice-message.ogg";
    return createVoicePlayer({
      src: message.media_url,
      downloadName: name,
      outbound: message.direction === "out",
    });
  }
  if (showKind === "video") return videoNode(message);
  return documentNode(message, formatBytes);
}
