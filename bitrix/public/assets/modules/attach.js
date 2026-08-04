/**
 * Sending attachments, WhatsApp-style: pick a file, look at it, add a caption,
 * then send — never a blind upload the moment a file is chosen.
 *
 * Meta's own per-type ceilings are enforced here so an oversized file fails
 * instantly and locally instead of after a long upload the API will reject.
 */

import { inbox } from "../api/api.js";
import { el, clear, formatBytes, modal } from "../core/dom.js";
import { icon } from "../core/icons.js";

/** Meta Cloud API media limits, in bytes. */
export const MEDIA_LIMITS = {
  image: 5 * 1024 * 1024,
  video: 16 * 1024 * 1024,
  audio: 16 * 1024 * 1024,
  document: 100 * 1024 * 1024,
};

const LIMIT_LABEL = {
  image: "5 MB",
  video: "16 MB",
  audio: "16 MB",
  document: "100 MB",
};

/** Which WhatsApp message kind a file maps to. */
export function kindForFile(file) {
  const mime = file?.type || "";
  if (mime.startsWith("image/")) return "image";
  if (mime.startsWith("video/")) return "video";
  if (mime.startsWith("audio/")) return "audio";
  return "document";
}

/** @returns {string|null} an error to show, or null when the file is sendable. */
export function checkFile(file) {
  if (!file) return "No file selected.";
  if (!file.size) return "That file is empty.";

  const kind = kindForFile(file);
  if (file.size > MEDIA_LIMITS[kind]) {
    return `This ${kind} is ${formatBytes(file.size)}. WhatsApp will not accept a ${kind} larger than ${LIMIT_LABEL[kind]}.`;
  }
  return null;
}

/** File-picker presets behind the attach button. */
export const ATTACH_MENU = [
  { key: "media", icon: "image", label: "Photo or video", accept: "image/*,video/*" },
  { key: "document", icon: "file", label: "Document", accept: ".pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt,.csv,.zip" },
  { key: "audio", icon: "mic", label: "Audio", accept: "audio/*" },
];

/**
 * Preview → caption → upload → send. Resolves once the message is on its way;
 * the caller only has to refresh the thread.
 *
 * @param {File} file
 * @param {{conversationId: string, onSent: (message: object) => void}} options
 */
export function openAttachmentDialog(file, { conversationId, onSent }) {
  const kind = kindForFile(file);
  const problem = checkFile(file);

  const caption = el("textarea.field.attach__caption", {
    rows: 2,
    placeholder: kind === "document" ? "Caption (optional)" : "Add a caption (optional)",
  });

  const error = el("div.alert", { hidden: !problem }, [problem || ""]);
  const bar = el("div.attach__bar-fill");
  const progress = el("div.attach__progress", { hidden: true }, [el("div.attach__bar", {}, [bar])]);

  const sendBtn = el("button.btn.btn--primary", { type: "button", disabled: Boolean(problem) }, ["Send"]);
  const cancelBtn = el("button.btn.btn--ghost", { type: "button" }, ["Cancel"]);

  const body = el("div.modal__body", {}, [
    previewNode(file, kind),
    problem ? null : caption,
    error,
    progress,
    el("div.modal__actions", {}, [cancelBtn, sendBtn]),
  ]);

  let upload = null;
  const dialog = modal(titleFor(kind), body, { onClose: () => upload?.abort() });

  cancelBtn.addEventListener("click", () => dialog.close());

  sendBtn.addEventListener("click", async () => {
    sendBtn.disabled = true;
    cancelBtn.textContent = "Cancel";
    error.hidden = true;
    progress.hidden = false;
    bar.style.width = "0%";

    upload = inbox.uploadMedia(file, {
      conversationId,
      onProgress: (fraction) => {
        bar.style.width = `${Math.round(fraction * 100)}%`;
      },
    });

    try {
      const uploaded = await upload.promise;
      sendBtn.textContent = "Sending…";

      const message = await inbox.send(conversationId, {
        kind,
        media_id: uploaded.media_id,
        // The stored asset the upload just created. The backend can find it
        // from media_id alone, but naming it keeps the send off that lookup —
        // and it is what makes the reply carry a ready media_url, so the sent
        // photo renders straight away instead of after a refetch.
        asset_id: uploaded.asset_id,
        body: caption.value.trim(),
        filename: kind === "document" ? file.name : undefined,
      });

      dialog.close();
      onSent?.(message);
    } catch (failure) {
      upload = null;
      progress.hidden = true;
      sendBtn.disabled = false;
      sendBtn.textContent = "Send";
      error.hidden = false;
      // A closed 24h window comes back as 409 and is not a retryable failure.
      error.textContent =
        failure.code === "http_409"
          // A template does not reopen the window; only the customer writing
          // back does. It earns the right to be replied to, which is a
          // different thing and the one worth saying to somebody holding a file
          // they cannot send.
          ? "The 24-hour window has closed, so a file cannot be sent. Send a template and wait for a reply."
          : failure.message;
    }
  });

  // Straight to typing the caption is the common case.
  if (!problem) caption.focus();
  return dialog;
}

function titleFor(kind) {
  if (kind === "image") return "Send a photo";
  if (kind === "video") return "Send a video";
  if (kind === "audio") return "Send audio";
  return "Send a document";
}

/** Thumbnail for images/video, a file card for everything else. */
function previewNode(file, kind) {
  const meta = el("div.attach__meta", {}, [
    el("div.attach__name", { title: file.name }, [file.name]),
    el("div.attach__size", {}, [formatBytes(file.size), file.type ? ` · ${file.type}` : ""]),
  ]);

  if (kind === "image" || kind === "video") {
    const url = URL.createObjectURL(file);
    const media =
      kind === "image"
        ? el("img.attach__thumb", { src: url, alt: file.name })
        : el("video.attach__thumb", { src: url, controls: true, preload: "metadata" });
    // The object URL lives as long as the node that uses it.
    media.addEventListener("load", () => URL.revokeObjectURL(url), { once: true });
    return el("div.attach__preview", {}, [media, meta]);
  }

  return el("div.attach__preview.attach__preview--file", {}, [
    el("div.attach__icon", {}, [icon(kind === "audio" ? "mic" : "file", { size: 30 })]),
    meta,
  ]);
}

/**
 * Wires the attach button, drag & drop and clipboard paste onto one handler.
 * Returns a teardown so the listeners die with the composer.
 */
export function bindFileSources({ button, dropZone, pasteTarget, onFile, extraItems = [] }) {
  const input = el("input", { type: "file", hidden: true });
  document.body.append(input);

  input.addEventListener("change", () => {
    const [file] = input.files || [];
    if (file) onFile(file);
    input.value = ""; // so the same file can be picked twice in a row
  });

  const pick = (accept) => {
    input.accept = accept || "";
    input.click();
  };

  const menu = attachMenu(button, pick, extraItems);

  const onDragOver = (event) => {
    if (!event.dataTransfer?.types?.includes("Files")) return;
    event.preventDefault();
    dropZone.classList.add("is-dropping");
  };
  const onDragLeave = (event) => {
    if (event.relatedTarget && dropZone.contains(event.relatedTarget)) return;
    dropZone.classList.remove("is-dropping");
  };
  const onDrop = (event) => {
    if (!event.dataTransfer?.files?.length) return;
    event.preventDefault();
    dropZone.classList.remove("is-dropping");
    onFile(event.dataTransfer.files[0]);
  };

  const onPaste = (event) => {
    const item = [...(event.clipboardData?.items || [])].find((i) => i.kind === "file");
    if (!item) return;
    const file = item.getAsFile();
    if (!file) return;
    event.preventDefault();
    onFile(file);
  };

  dropZone.addEventListener("dragover", onDragOver);
  dropZone.addEventListener("dragleave", onDragLeave);
  dropZone.addEventListener("drop", onDrop);
  pasteTarget.addEventListener("paste", onPaste);

  return () => {
    menu.destroy();
    input.remove();
    dropZone.removeEventListener("dragover", onDragOver);
    dropZone.removeEventListener("dragleave", onDragLeave);
    dropZone.removeEventListener("drop", onDrop);
    pasteTarget.removeEventListener("paste", onPaste);
  };
}

/** The small Photo/Document/Audio popup anchored to the attach button. */
function attachMenu(button, pick, extraItems = []) {
  let open = null;

  const close = () => {
    open?.remove();
    open = null;
    document.removeEventListener("click", onOutside, true);
  };

  const onOutside = (event) => {
    if (open && !open.contains(event.target) && event.target !== button) close();
  };

  const toggle = (event) => {
    event.preventDefault();
    if (open) return close();

    // Anything else that puts content into a message — the shared library, a
    // location pin, a saved reply — belongs in this menu too. One button in the
    // composer instead of four, and the grouping matches how an agent thinks
    // about it: "add something".
    const fileItems = ATTACH_MENU.map((entry) =>
      el(
        "button.attach-menu__item",
        {
          type: "button",
          onclick: () => {
            close();
            pick(entry.accept);
          },
        },
        [icon(entry.icon, { size: 17 }), entry.label]
      )
    );

    const extras = extraItems.map((entry) =>
      el(
        "button.attach-menu__item",
        {
          type: "button",
          onclick: () => {
            close();
            entry.onSelect?.();
          },
        },
        [icon(entry.icon, { size: 17 }), entry.label]
      )
    );

    open = el(
      "div.attach-menu",
      {},
      [...fileItems, ...(extras.length ? [el("div.attach-menu__sep")] : []), ...extras]
    );

    button.parentElement.append(open);
    document.addEventListener("click", onOutside, true);
  };

  button.addEventListener("click", toggle);
  return { destroy: () => { close(); button.removeEventListener("click", toggle); } };
}
