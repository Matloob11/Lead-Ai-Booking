/**
 * The composer for the QR-linked panel: text, attachments, voice notes, emoji,
 * replies and a pin.
 *
 * Its own module because app.js has three people working in it. Nothing here is
 * imported from there — the two helpers it needs (`el`, and the base-relative
 * URL) are small and derive from the document, not from app state, so a copy
 * costs less than a shared file that three sessions edit at once.
 *
 * It is built **once per open conversation**, not once per poll. app.js repaints
 * only `.thread__messages` between polls precisely so this survives: rebuilding
 * it every five seconds used to throw away whatever the agent was typing, along
 * with a half-recorded voice note and a picked file.
 *
 * Nothing a customer wrote or an agent typed goes through innerHTML. Every
 * caption, file name and quoted line on this bar is a text node.
 */

import { icon } from "./icons.js";

const MAX_BODY = 4096;

/**
 * Matches MAX_MEDIA_MB's default on the server, which is what /api/upload
 * enforces. Checked here as well so a 40 MB video is refused before it spends
 * two minutes going up, not after.
 */
const MAX_UPLOAD_BYTES = 25 * 1024 * 1024;

/** el("div.row", {onclick}, [child, "text"]) → HTMLElement. */
function el(spec, props = {}, children = []) {
  const [tag, ...classes] = spec.split(".");
  const node = document.createElement(tag || "div");
  if (classes.length) node.className = classes.join(" ");

  for (const [key, value] of Object.entries(props)) {
    if (value === undefined || value === null || value === false) continue;
    if (key.startsWith("on") && typeof value === "function") {
      node.addEventListener(key.slice(2).toLowerCase(), value);
    } else if (key === "class") {
      node.className = [node.className, value].filter(Boolean).join(" ");
    } else if (key in node && key !== "list") {
      node[key] = value;
    } else {
      node.setAttribute(key, value === true ? "" : value);
    }
  }

  for (const child of [children].flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

const clear = (node) => (node.replaceChildren(), node);

/**
 * Every URL is resolved against the document, never written absolute.
 *
 * nginx publishes this service under /qr/, so "/api/send" would leave for the
 * host root and arrive at Django — a different application that has never heard
 * of these routes.
 */
const apiBase = new URL("./", document.baseURI);
const onApi = (path) => new URL(String(path).replace(/^\//, ""), apiBase).href;

async function api(path, { method = "GET", body } = {}) {
  const init = { method, headers: { Accept: "application/json" } };
  if (body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }
  const response = await fetch(onApi(path), init);
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(payload?.error || payload?.detail || `${method} ${path} → HTTP ${response.status}`);
  }
  return payload;
}

function formatBytes(bytes) {
  const n = Number(bytes);
  if (!Number.isFinite(n) || n <= 0) return "";
  const units = ["B", "KB", "MB", "GB"];
  const i = Math.min(units.length - 1, Math.floor(Math.log(n) / Math.log(1024)));
  const value = n / 1024 ** i;
  return `${value >= 10 || i === 0 ? Math.round(value) : value.toFixed(1)} ${units[i]}`;
}

/** mm:ss, for a recording that is still running. */
const clock = (ms) => {
  const total = Math.floor(ms / 1000);
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
};

/** What WhatsApp calls each family of file, from what the browser calls it. */
function kindOfFile(file) {
  const mime = String(file.type || "").toLowerCase();
  if (mime.startsWith("image/")) return mime === "image/webp" ? "sticker" : "image";
  if (mime.startsWith("video/")) return "video";
  if (mime.startsWith("audio/")) return "audio";
  return "document";
}

/* ------------------------------------------------------------------ emoji */

/**
 * A curated set rather than the full Unicode table — the same decision the main
 * panel's picker makes, and for the same reasons: agents reach for the same few
 * dozen, a short list needs no search box, and the CSP rules out a picker
 * library from a CDN anyway.
 */
const EMOJI = [
  {
    name: "Common",
    characters:
      "😀 😃 😄 😁 😅 😂 🙂 😉 😊 😍 😘 😎 🤔 🙄 😐 😢 😭 😤 😡 🥺 😴 🤝 🙏 👍 👎 👏 💪 🙌 👌 ✌️ 👋 ✋".split(" "),
  },
  {
    name: "Work",
    characters:
      "✅ ❌ ⚠️ ❗ ❓ 📌 📎 📄 📷 🎤 🎬 📍 📞 📱 💬 📅 ⏰ ⏳ 🔔 🔍 ✏️ 📝 💰 💵 🏦 🧾 📊 🔑".split(" "),
  },
  {
    name: "Property",
    characters: "🏠 🏡 🏢 🏬 🏗️ 🏘️ 🌇 🛏️ 🛋️ 🚿 🚗 🌳 🌊 🔥 ⭐ 🎉 ❤️ 💯".split(" "),
  },
];

/* -------------------------------------------------------------- the thing */

/**
 * @param {object} conversation             the open conversation
 * @param {object} options
 * @param {object|null} [options.phone]     the session this chat is on
 * @param {() => Promise<void>} options.onSent  reload and repaint the messages
 * @returns {HTMLElement} the footer to put under the thread
 */
export function createComposer(conversation, { phone = null, onSent = async () => {} } = {}) {
  // A phone that is not ready cannot send, and offering the bar anyway would
  // let an agent type a reply that has nowhere to go.
  if (phone && phone.status !== "ready") {
    const name = phone.label || (phone.phone_number ? `+${phone.phone_number}` : `Phone #${phone.id}`);
    return el("div.composer.composer--locked", {}, [
      icon("alert", { size: 15 }),
      `${name} is ${String(phone.status).toLowerCase()} — messages cannot be sent until it is ready.`,
    ]);
  }

  const to = conversation.contact?.wa_id || conversation.wa_id || "";

  /** What is staged but not yet sent. */
  const draft = { file: null, previewUrl: "", replyTo: null, upload: null, recorder: null };

  /**
   * Everything this composer attached outside itself.
   *
   * The watchers below listen on `section.thread`, which app.js keeps and only
   * empties — so it outlives this composer. Opening a second chat builds a
   * second composer on the same element, and without a signal to cut them loose
   * the first one's listeners stay for the rest of the session, one more set
   * every time an agent clicks a different chat.
   */
  const attached = new AbortController();
  const { signal } = attached;

  /* ---------------------------------------------------------- the pieces */

  const problem = el("div.composer__error", { hidden: true });
  const replyBar = el("div.composer__reply", { hidden: true });
  const staged = el("div.composer__staged", { hidden: true });

  const input = el("textarea.composer__input", {
    rows: 1,
    placeholder: "Write a message…",
    maxlength: String(MAX_BODY),
  });

  const fileInput = el("input", { type: "file", hidden: true });

  const act = (glyph, title, extra = "") =>
    el("button.composer__act", { type: "button", title, class: extra }, [icon(glyph, { size: 17 })]);

  const attachBtn = act("paperclip", "Attach a file");
  const emojiBtn = act("smile", "Emoji");
  const micBtn = act("mic", "Record a voice note", "composer__mic");
  const send = el("button.composer__send", { type: "button", title: "Send  ·  Enter" }, [
    icon("send", { size: 17 }),
  ]);

  const bar = el("div.composer", {}, [attachBtn, emojiBtn, input, micBtn, send, fileInput]);
  const footer = el("footer.thread__foot", {}, [problem, replyBar, staged, bar]);

  /* ---------------------------------------------------------- complaints */

  const say = (message) => {
    problem.hidden = false;
    clear(problem).append(String(message));
  };
  const quiet = () => {
    problem.hidden = true;
    clear(problem);
  };

  const showSending = (busy) => {
    send.disabled = busy;
    send.title = busy ? "Sending…" : "Send  ·  Enter";
    clear(send).append(icon(busy ? "clock" : "send", { size: 17 }));
  };

  /* --------------------------------------------------------------- reply */

  function setReply(id, text) {
    draft.replyTo = id;
    replyBar.hidden = false;
    clear(replyBar).append(
      icon("reply", { size: 14 }),
      el("span.composer__reply-text", {}, [text || "Replying to an earlier message"]),
      el("button.composer__reply-x", { type: "button", title: "Cancel the reply", onclick: clearReply }, [
        icon("close", { size: 14 }),
      ])
    );
    input.focus();
  }

  function clearReply() {
    draft.replyTo = null;
    replyBar.hidden = true;
    clear(replyBar);
  }

  /**
   * Puts a Reply control on every bubble, and keeps putting it there.
   *
   * app.js replaces the whole message list on each poll, so anything added to a
   * bubble is gone five seconds later. Watching the thread and re-decorating is
   * what makes the control survive that, without app.js having to know this
   * module exists.
   */
  function watchBubbles() {
    const thread = footer.parentElement;
    if (!thread) return;

    const decorate = () => {
      for (const node of thread.querySelectorAll(".msg[data-id]:not([data-reply-ready])")) {
        node.setAttribute("data-reply-ready", "");
        node.append(
          el("button.msg__reply", { type: "button", title: "Reply to this message" }, [
            icon("reply", { size: 13 }),
          ])
        );
      }
    };

    const observer = new MutationObserver(() => {
      // The composer is replaced when the open chat changes; when that happens
      // this observer — and everything else this instance attached out here —
      // is watching a thread that is no longer ours.
      if (!footer.isConnected) {
        observer.disconnect();
        attached.abort();
        return;
      }
      decorate();
    });

    observer.observe(thread, { childList: true, subtree: true });
    decorate();

    // One listener for every bubble, now and later.
    thread.addEventListener(
      "click",
      (event) => {
        const button = event.target.closest?.(".msg__reply");
        if (!button) return;
        const bubble = button.closest(".msg");
        const id = bubble?.getAttribute("data-id");
        if (!id) return;
        setReply(Number(id), bubble.querySelector(".msg__body")?.textContent || "");
      },
      { signal }
    );
  }

  /* ---------------------------------------------------------- attachment */

  /** Stages a file and shows what will go, before anything is uploaded. */
  function stage(file) {
    if (!file) return;
    if (file.size > MAX_UPLOAD_BYTES) {
      return say(`${file.name} is ${formatBytes(file.size)} — the limit is ${formatBytes(MAX_UPLOAD_BYTES)}.`);
    }

    unstage();
    draft.file = file;
    quiet();

    const kind = kindOfFile(file);
    const preview = el("div.staged__preview");

    if (kind === "image" || kind === "sticker") {
      // Revoked in unstage(): an object URL pins the whole file in memory until
      // it is, and an agent going through a folder would pin every one of them.
      draft.previewUrl = URL.createObjectURL(file);
      preview.append(el("img.staged__thumb", { src: draft.previewUrl, alt: "" }));
    } else if (kind === "video") {
      draft.previewUrl = URL.createObjectURL(file);
      preview.append(el("video.staged__thumb", { src: draft.previewUrl, muted: true, playsinline: true }));
    } else {
      preview.append(el("div.staged__glyph", {}, [icon(kind === "audio" ? "mic" : "file", { size: 20 })]));
    }

    staged.hidden = false;
    clear(staged).append(
      preview,
      el("div.staged__about", {}, [
        el("div.staged__name", {}, [file.name || `${kind} file`]),
        el("div.staged__meta", {}, [`${kind} · ${formatBytes(file.size)}`]),
        el("div.staged__bar", { hidden: true }, [el("div.staged__fill")]),
      ]),
      el("button.staged__x", { type: "button", title: "Remove this file", onclick: unstage }, [
        icon("close", { size: 15 }),
      ])
    );

    input.placeholder = "Add a caption…";
    input.focus();
  }

  function unstage() {
    draft.upload?.abort();
    draft.upload = null;
    if (draft.previewUrl) URL.revokeObjectURL(draft.previewUrl);
    draft.previewUrl = "";
    draft.file = null;
    staged.hidden = true;
    clear(staged);
    input.placeholder = "Write a message…";
  }

  /**
   * Sends the bytes up, reporting how far it has got.
   *
   * XMLHttpRequest rather than fetch: fetch reports nothing about an upload in
   * progress, and a 40 MB video with no bar looks exactly like a panel that has
   * frozen. It is also what makes cancelling possible.
   *
   * @returns {Promise<string>} the path the send route can read the file from
   */
  function upload(file) {
    return new Promise((resolve, reject) => {
      const form = new FormData();
      form.append("file", file, file.name || "upload");

      const request = new XMLHttpRequest();
      draft.upload = request;

      const bar = staged.querySelector(".staged__bar");
      const fill = staged.querySelector(".staged__fill");
      if (bar) bar.hidden = false;

      request.upload.addEventListener("progress", (event) => {
        if (!event.lengthComputable || !fill) return;
        fill.style.width = `${Math.round((event.loaded / event.total) * 100)}%`;
      });

      request.addEventListener("load", () => {
        draft.upload = null;
        let payload = null;
        try {
          payload = JSON.parse(request.responseText || "null");
        } catch {}

        if (request.status === 404) {
          return reject(new Error("Uploading is not available on this server yet."));
        }
        if (request.status < 200 || request.status >= 300) {
          return reject(new Error(payload?.detail || payload?.error || `Upload failed — HTTP ${request.status}`));
        }

        // The field has been called several things across the two services;
        // whichever one arrives, it is the path the send route opens.
        const path =
          payload?.media_path || payload?.path || payload?.file_path || payload?.media?.file_path;
        if (!path) return reject(new Error("The upload succeeded but returned no file path."));
        resolve(path);
      });

      request.addEventListener("error", () => {
        draft.upload = null;
        reject(new Error("The upload did not reach the server."));
      });
      request.addEventListener("abort", () => {
        draft.upload = null;
        reject(new Error("Upload cancelled."));
      });

      // The session goes in the query, not the form: the route reads it before
      // the multipart body is parsed, so a field in the body arrives too late
      // and the ownership check it guards is quietly skipped.
      request.open("POST", `${onApi("api/upload")}?session_id=${encodeURIComponent(conversation.session_id)}`);
      request.send(form);
    });
  }

  /* ---------------------------------------------------------- voice note */

  /**
   * Hold the button, talk, let go to send.
   *
   * Opus in an Ogg container is what WhatsApp itself uses for a voice note;
   * Chrome will only give it inside WebM, so that is the fallback rather than a
   * failure. Whatever the browser agrees to is what gets uploaded.
   */
  const VOICE_TYPES = ["audio/ogg;codecs=opus", "audio/webm;codecs=opus", "audio/webm", "audio/mp4"];

  async function startRecording() {
    if (draft.recorder || !navigator.mediaDevices?.getUserMedia) {
      if (!navigator.mediaDevices?.getUserMedia) say("This browser will not give the panel a microphone.");
      return;
    }

    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (error) {
      return say(
        error?.name === "NotAllowedError"
          ? "The microphone was refused. Allow it for this page and try again."
          : `The microphone could not be opened: ${error.message}`
      );
    }

    const mimeType = VOICE_TYPES.find((type) => MediaRecorder.isTypeSupported?.(type)) || "";
    const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    const chunks = [];
    const startedAt = Date.now();
    let cancelled = false;

    const timer = el("span.rec__time", {}, ["0:00"]);
    const panel = el("div.composer__rec", {}, [
      el("span.rec__dot"),
      el("span.rec__label", {}, ["Recording"]),
      timer,
      el("button.rec__cancel", { type: "button" }, ["Cancel"]),
      el("button.rec__stop.btn.btn--sm", { type: "button" }, ["Send"]),
    ]);

    const tick = setInterval(() => (timer.textContent = clock(Date.now() - startedAt)), 200);

    const finish = () => {
      clearInterval(tick);
      panel.remove();
      stream.getTracks().forEach((track) => track.stop());
      draft.recorder = null;
      micBtn.classList.remove("is-on");
    };

    recorder.addEventListener("dataavailable", (event) => event.data.size && chunks.push(event.data));

    recorder.addEventListener("stop", async () => {
      const elapsed = Date.now() - startedAt;
      finish();
      if (cancelled) return;

      // Under a second is a slip of the finger, not a message.
      if (elapsed < 900) return say("That was too short to send. Hold the button while you speak.");

      const type = recorder.mimeType || mimeType || "audio/webm";
      const extension = type.includes("ogg") ? "ogg" : type.includes("mp4") ? "m4a" : "webm";
      const blob = new Blob(chunks, { type: type.split(";")[0] });
      const file = new File([blob], `voice-note.${extension}`, { type: blob.type });

      stage(file);
      await submit({ forceKind: "audio" });
    });

    panel.querySelector(".rec__cancel").addEventListener("click", () => {
      cancelled = true;
      recorder.stop();
    });
    panel.querySelector(".rec__stop").addEventListener("click", () => recorder.stop());

    draft.recorder = { recorder, stop: () => recorder.stop(), cancel: () => { cancelled = true; recorder.stop(); } };
    micBtn.classList.add("is-on");
    footer.insertBefore(panel, bar);
    quiet();
    recorder.start();
  }

  /* ------------------------------------------------------------ location */

  /**
   * A pin, asked for on the bar rather than in a modal.
   *
   * Coordinates leave as JSON numbers. The gateway on the other channel refuses
   * strings outright with "Invalid JSON format", and sending one shape here and
   * another there is exactly the divergence this project keeps closing.
   */
  function openLocation() {
    if (footer.querySelector(".composer__pin")) return;

    const lat = el("input.pin__input", { type: "text", inputmode: "decimal", placeholder: "Latitude" });
    const lon = el("input.pin__input", { type: "text", inputmode: "decimal", placeholder: "Longitude" });
    const name = el("input.pin__input", { type: "text", placeholder: "Name (optional)" });
    const address = el("input.pin__input", { type: "text", placeholder: "Address (optional)" });
    const trouble = el("div.pin__error", { hidden: true });

    const panel = el("div.composer__pin", {}, [
      el("div.pin__head", {}, [
        icon("location", { size: 15 }),
        el("span", {}, ["Send a location"]),
        el("button.pin__x", { type: "button", title: "Close", onclick: () => panel.remove() }, [
          icon("close", { size: 14 }),
        ]),
      ]),
      el("div.pin__grid", {}, [lat, lon]),
      name,
      address,
      trouble,
      el("div.pin__actions", {}, [
        el("button.btn.btn--ghost.btn--sm", { type: "button", onclick: useMyLocation }, [
          "Use this device",
        ]),
        el("button.btn.btn--sm", { type: "button", onclick: sendPin }, ["Send pin"]),
      ]),
    ]);

    function useMyLocation() {
      if (!navigator.geolocation) return complain("This browser will not share a location.");
      navigator.geolocation.getCurrentPosition(
        (position) => {
          lat.value = position.coords.latitude.toFixed(6);
          lon.value = position.coords.longitude.toFixed(6);
        },
        (error) => complain(`The device would not give its location: ${error.message}`)
      );
    }

    function complain(message) {
      trouble.hidden = false;
      clear(trouble).append(message);
    }

    async function sendPin() {
      const latitude = Number(lat.value.trim());
      const longitude = Number(lon.value.trim());

      if (!lat.value.trim() || !lon.value.trim() || Number.isNaN(latitude) || Number.isNaN(longitude)) {
        return complain("Latitude and longitude must both be numbers.");
      }
      if (latitude < -90 || latitude > 90 || longitude < -180 || longitude > 180) {
        return complain("Those coordinates are not on Earth.");
      }

      trouble.hidden = true;
      try {
        await api("api/send", {
          method: "POST",
          body: {
            session_id: conversation.session_id,
            to,
            kind: "location",
            latitude,
            longitude,
            name: name.value.trim(),
            address: address.value.trim(),
            reply_to_id: draft.replyTo,
          },
        });
        panel.remove();
        clearReply();
        await onSent();
      } catch (error) {
        complain(error.message);
      }
    }

    footer.insertBefore(panel, bar);
    lat.focus();
  }

  /* ---------------------------------------------------------------- send */

  async function submit({ forceKind = "" } = {}) {
    const body = input.value.trim();
    const file = draft.file;
    if (!body && !file) return;

    showSending(true);
    quiet();

    try {
      let mediaPath = "";
      if (file) mediaPath = await upload(file);

      await api("api/send", {
        method: "POST",
        body: {
          session_id: conversation.session_id,
          to,
          kind: forceKind || (file ? kindOfFile(file) : "text"),
          body,
          media_path: mediaPath || undefined,
          reply_to_id: draft.replyTo,
        },
      });

      input.value = "";
      unstage();
      clearReply();
      // Refetched rather than guessed: the row the server wrote carries the id
      // and status a locally invented bubble would not have.
      await onSent();
      showSending(false);
    } catch (error) {
      showSending(false);
      say(error.message);
    }
  }

  /* --------------------------------------------------------------- emoji */

  function toggleEmoji() {
    const open = footer.querySelector(".emoji");
    if (open) return open.remove();

    const insert = (character) => {
      const start = input.selectionStart ?? input.value.length;
      const end = input.selectionEnd ?? start;
      input.value = input.value.slice(0, start) + character + input.value.slice(end);
      const caret = start + character.length;
      input.setSelectionRange(caret, caret);
      input.focus();
    };

    const popup = el(
      "div.emoji",
      {},
      EMOJI.flatMap((group) => [
        el("div.emoji__title", {}, [group.name]),
        el(
          "div.emoji__grid",
          {},
          group.characters.map((character) =>
            el("button.emoji__item", { type: "button", onclick: () => insert(character) }, [character])
          )
        ),
      ])
    );

    const onOutside = (event) => {
      if (!popup.contains(event.target) && event.target !== emojiBtn) {
        popup.remove();
        document.removeEventListener("click", onOutside, true);
      }
    };

    footer.insertBefore(popup, bar);
    setTimeout(() => document.addEventListener("click", onOutside, true), 0);
  }

  /* -------------------------------------------------------- attach menu */

  function toggleAttachMenu() {
    const open = footer.querySelector(".attach");
    if (open) return open.remove();

    const pick = (accept) => {
      fileInput.accept = accept;
      fileInput.value = "";
      fileInput.click();
      menu.remove();
    };

    const menu = el("div.attach", {}, [
      el("button.attach__item", { type: "button", onclick: () => pick("image/*") }, [
        icon("image", { size: 16 }), "Photo",
      ]),
      el("button.attach__item", { type: "button", onclick: () => pick("video/*") }, [
        icon("video", { size: 16 }), "Video",
      ]),
      el("button.attach__item", { type: "button", onclick: () => pick("audio/*") }, [
        icon("mic", { size: 16 }), "Audio file",
      ]),
      el("button.attach__item", { type: "button", onclick: () => pick("") }, [
        icon("file", { size: 16 }), "Document",
      ]),
      el("button.attach__item", { type: "button", onclick: () => { menu.remove(); openLocation(); } }, [
        icon("location", { size: 16 }), "Location",
      ]),
    ]);

    const onOutside = (event) => {
      if (!menu.contains(event.target) && event.target !== attachBtn) {
        menu.remove();
        document.removeEventListener("click", onOutside, true);
      }
    };

    footer.insertBefore(menu, bar);
    setTimeout(() => document.addEventListener("click", onOutside, true), 0);
  }

  /* ---------------------------------------------------------- drag & drop */

  function watchDrops() {
    const thread = footer.parentElement;
    if (!thread) return;

    // Left behind by a previous composer if the chat was switched mid-drag.
    thread.querySelector(".dropveil")?.remove();

    const veil = el("div.dropveil", { hidden: true }, [
      el("div.dropveil__box", {}, [icon("file", { size: 26 }), "Drop the file to attach it"]),
    ]);
    thread.append(veil);
    signal.addEventListener("abort", () => veil.remove());

    let depth = 0;
    const carriesFiles = (event) => [...(event.dataTransfer?.types || [])].includes("Files");

    thread.addEventListener(
      "dragenter",
      (event) => {
        if (!carriesFiles(event)) return;
        event.preventDefault();
        // Counted, not toggled: dragging over a bubble fires `dragleave` for the
        // element being left even though the pointer never left the thread, and
        // the veil flickered off on every one of them.
        depth++;
        veil.hidden = false;
      },
      { signal }
    );
    thread.addEventListener(
      "dragover",
      (event) => carriesFiles(event) && event.preventDefault(),
      { signal }
    );
    thread.addEventListener(
      "dragleave",
      () => {
        depth = Math.max(0, depth - 1);
        if (!depth) veil.hidden = true;
      },
      { signal }
    );
    thread.addEventListener(
      "drop",
      (event) => {
        if (!carriesFiles(event)) return;
        event.preventDefault();
        depth = 0;
        veil.hidden = true;
        // One at a time: each send is its own message, and quietly dropping the
        // other four files an agent let go of would be worse than saying so.
        const files = [...(event.dataTransfer?.files || [])];
        if (files.length > 1) say("One file at a time — the first one is attached.");
        stage(files[0]);
      },
      { signal }
    );
  }

  /* --------------------------------------------------------------- wiring */

  attachBtn.addEventListener("click", toggleAttachMenu);
  emojiBtn.addEventListener("click", toggleEmoji);
  send.addEventListener("click", () => submit());
  fileInput.addEventListener("change", () => stage(fileInput.files?.[0]));

  micBtn.addEventListener("pointerdown", (event) => {
    event.preventDefault();
    startRecording();
  });

  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
    if (event.key === "Escape" && draft.replyTo) clearReply();
  });

  // Grows with what is being typed, up to the cap the stylesheet sets.
  input.addEventListener("input", () => {
    input.style.height = "auto";
    input.style.height = `${Math.min(120, input.scrollHeight)}px`;
  });

  // A picture in the clipboard is a screenshot nine times out of ten, and
  // saving it to disk first only to attach it is a detour.
  input.addEventListener("paste", (event) => {
    const file = [...(event.clipboardData?.files || [])][0];
    if (file) {
      event.preventDefault();
      stage(file);
    }
  });

  queueMicrotask(() => {
    input.focus();
    watchBubbles();
    watchDrops();
  });

  return footer;
}
