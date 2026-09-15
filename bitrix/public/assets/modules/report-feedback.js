/**
 * Report & Feedback — Official API hamburger.
 *
 * Every agent can file an issue with image/video. Admins see the open queue
 * and mark items solved. Own module so dirty inbox.js is not widened.
 */

import { asList, feedback } from "../api/api.js";
import { clear, el, formatBytes, modal, stamp, toast } from "../core/dom.js";

const ACCEPT = "image/jpeg,image/png,image/webp,image/gif,video/mp4,video/webm,video/quicktime,.mov";
const MAX_FILES = 4;
const IMAGE_MAX = 8 * 1024 * 1024;
const VIDEO_MAX = 28 * 1024 * 1024;

let mounted = false;
let tab = "new";

function flag(size = 16) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("width", String(size));
  svg.setAttribute("height", String(size));
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", "2");
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  svg.setAttribute("aria-hidden", "true");
  svg.classList.add("icon");
  const a = document.createElementNS("http://www.w3.org/2000/svg", "path");
  a.setAttribute("d", "M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z");
  const b = document.createElementNS("http://www.w3.org/2000/svg", "line");
  b.setAttribute("x1", "4");
  b.setAttribute("x2", "4");
  b.setAttribute("y1", "22");
  b.setAttribute("y2", "15");
  svg.append(a, b);
  return svg;
}

function lastMenuItemInSection(section) {
  let last = section;
  let next = section.nextElementSibling;
  while (next && !next.classList.contains("menu__section")) {
    last = next;
    next = next.nextElementSibling;
  }
  return last;
}

function injectMenu() {
  const menu = document.querySelector(".sidebar__menu");
  if (!menu) return false;

  let item = menu.querySelector("#rfb-menu-item");
  if (!item) {
    item = el(
      "button.btn.menu__item",
      { id: "rfb-menu-item", type: "button", onclick: () => openDesk() },
      [flag(16), "Report & Feedback"]
    );
    const tools = [...menu.querySelectorAll(".menu__section")].find(
      (node) => (node.textContent || "").trim() === "Inbox tools"
    );
    if (tools) lastMenuItemInSection(tools).after(item);
    else menu.append(item);
  }
  return true;
}

function glassSheet(dialog) {
  dialog.box.classList.add("rfb-modal");
  dialog.box.parentElement?.classList.add("rfb-scrim");
}

function fileKind(file) {
  const type = String(file?.type || "").toLowerCase();
  if (type.startsWith("image/")) return "image";
  if (type.startsWith("video/")) return "video";
  const name = String(file?.name || "").toLowerCase();
  if (/\.(jpe?g|png|webp|gif)$/.test(name)) return "image";
  if (/\.(mp4|webm|mov|3gp)$/.test(name)) return "video";
  return "";
}

function fileError(file) {
  const kind = fileKind(file);
  if (!kind) return "Use a JPEG, PNG, WebP, GIF, MP4, WebM or MOV file.";
  const limit = kind === "image" ? IMAGE_MAX : VIDEO_MAX;
  if (file.size > limit) {
    return kind === "image"
      ? `${file.name} is over 8 MB.`
      : `${file.name} is over 28 MB.`;
  }
  return "";
}

function pickedList(files, onRemove) {
  if (!files.length) return el("p.rfb-muted", {}, ["No files attached."]);
  return el(
    "ul.rfb-files",
    {},
    files.map((file, index) =>
      el("li.rfb-file", {}, [
        el("span.rfb-file__name", {}, [file.name]),
        el("span.rfb-file__meta", {}, [formatBytes(file.size) || fileKind(file)]),
        el("button.rfb-file__x", { type: "button", title: "Remove", onclick: () => onRemove(index) }, ["Remove"]),
      ])
    )
  );
}

function attachmentNode(row) {
  if (row.kind === "image") {
    return el("a.rfb-att", { href: row.url, target: "_blank", rel: "noopener" }, [
      el("img.rfb-att__img", { src: row.url, alt: row.file_name || "Image" }),
    ]);
  }
  if (row.kind === "video") {
    return el("video.rfb-att__vid", {
      src: row.url,
      controls: true,
      playsInline: true,
    });
  }
  return el("a.rfb-att__link", { href: row.url, target: "_blank", rel: "noopener" }, [
    row.file_name || "Attachment",
  ]);
}

function reportCard(row, { canSolve, onSolved }) {
  const note = canSolve && row.status === "open"
    ? el("textarea.rfb-field.rfb-field--note", {
        rows: 2,
        maxlength: 2000,
        placeholder: "Optional note for the agent",
      })
    : null;
  const actions = [];
  if (canSolve && row.status === "open") {
    const btn = el("button.btn.btn--primary.rfb-solve", { type: "button" }, ["Mark solved"]);
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      try {
        await feedback.solve(row.id, note?.value || "");
        toast("Report marked solved");
        onSolved?.();
      } catch (error) {
        toast(error?.message || "Could not mark solved", "err");
        btn.disabled = false;
      }
    });
    actions.push(btn);
  }

  const media = (row.attachments || []).map(attachmentNode);
  return el("article.rfb-card", { class: row.status === "solved" ? "rfb-card--done" : "" }, [
    el("div.rfb-card__top", {}, [
      el("strong.rfb-card__who", {}, [row.agent?.display_name || "Agent"]),
      el("span.rfb-card__when", {}, [stamp(row.created_at)]),
      el("span.rfb-pill", { class: row.status === "solved" ? "rfb-pill--ok" : "" }, [
        row.status === "solved" ? "Solved" : "Open",
      ]),
    ]),
    el("p.rfb-card__body", {}, [row.body || ""]),
    media.length ? el("div.rfb-atts", {}, media) : null,
    row.status === "solved" && row.admin_note
      ? el("p.rfb-card__note", {}, [`Admin: ${row.admin_note}`])
      : null,
    row.status === "solved" && row.solved_by
      ? el("p.rfb-muted", {}, [`Solved by ${row.solved_by.display_name || "admin"}`])
      : null,
    note,
    actions.length ? el("div.rfb-card__actions", {}, actions) : null,
  ]);
}

async function paintQueue(host, status) {
  clear(host).append(el("p.rfb-muted", {}, ["Loading…"]));
  try {
    const payload = await feedback.list(status);
    const rows = asList(payload, "results");
    const canSolve = Boolean(payload?.can_solve);
    clear(host);
    if (!rows.length) {
      host.append(
        el("p.rfb-muted", {}, [
          status === "solved" ? "No solved reports yet." : "No open reports.",
        ])
      );
      return;
    }
    rows.forEach((row) =>
      host.append(reportCard(row, { canSolve, onSolved: () => paintQueue(host, status) }))
    );
  } catch (error) {
    clear(host).append(el("p.rfb-err", {}, [error?.message || "Could not load reports."]));
  }
}

function paintTabs(host, current, onPick) {
  clear(host);
  [
    ["new", "New report"],
    ["open", "Open"],
    ["solved", "Solved"],
  ].forEach(([id, label]) => {
    host.append(
      el(
        "button.rfb-tab",
        {
          type: "button",
          class: current === id ? "rfb-tab--on" : "",
          onclick: () => onPick(id),
        },
        [label]
      )
    );
  });
}

function openDesk() {
  const tabs = el("div.rfb-tabs");
  const compose = el("div.rfb-pane");
  const queue = el("div.rfb-pane.rfb-pane--queue");
  const files = [];
  const body = el("textarea.rfb-field.rfb-field--area", {
    rows: 6,
    maxlength: 4000,
    placeholder: "What happened? Include the chat, number, or screen where you saw it.",
  });
  const picker = el("input", {
    type: "file",
    accept: ACCEPT,
    multiple: true,
    hidden: true,
  });
  const fileHost = el("div");
  const status = el("p.rfb-note");
  const send = el("button.btn.btn--primary.rfb-save", { type: "button" }, ["Submit report"]);

  const refreshFiles = () => {
    clear(fileHost).append(
      pickedList(files, (index) => {
        files.splice(index, 1);
        refreshFiles();
      })
    );
  };
  refreshFiles();

  picker.addEventListener("change", () => {
    for (const file of [...picker.files]) {
      const error = fileError(file);
      if (error) {
        toast(error, "err");
        continue;
      }
      if (files.length >= MAX_FILES) {
        toast(`Attach at most ${MAX_FILES} files.`, "err");
        break;
      }
      files.push(file);
    }
    picker.value = "";
    refreshFiles();
  });

  send.addEventListener("click", async () => {
    const text = body.value.trim();
    if (!text) {
      status.textContent = "Describe the issue before submitting.";
      status.className = "rfb-note rfb-note--err";
      return;
    }
    send.disabled = true;
    status.className = "rfb-note";
    status.textContent = "Sending…";
    try {
      await feedback.create({ body: text, files });
      body.value = "";
      files.splice(0, files.length);
      refreshFiles();
      status.className = "rfb-note rfb-note--ok";
      status.textContent = "Submitted. An admin will review this report.";
      toast("Report submitted");
    } catch (error) {
      status.className = "rfb-note rfb-note--err";
      status.textContent = error?.message || "Could not submit.";
    } finally {
      send.disabled = false;
    }
  });

  compose.append(
    el("p.rfb-lead", {}, [
      "Tell an admin what is broken or missing. You can attach screenshots or a short video.",
    ]),
    body,
    el("div.rfb-attach", {}, [
      el(
        "button.btn.btn--ghost.rfb-attach-btn",
        { type: "button", onclick: () => picker.click() },
        ["Attach image or video"]
      ),
      el("span.rfb-muted", {}, ["JPEG, PNG, WebP, GIF, MP4, WebM or MOV. Max 4 files."]),
      picker,
    ]),
    fileHost,
    el("div.rfb-actions", {}, [send]),
    status
  );

  const show = (next) => {
    tab = next;
    paintTabs(tabs, tab, show);
    compose.hidden = tab !== "new";
    queue.hidden = tab === "new";
    if (tab !== "new") paintQueue(queue, tab);
  };

  const dialog = modal(
    "Report & Feedback",
    el("div.modal__body.rfb", {}, [tabs, compose, queue]),
    { wide: true }
  );
  glassSheet(dialog);
  show(tab);
}

function mount() {
  if (mounted) return;
  mounted = true;
  injectMenu();
  const root = document.getElementById("root") || document.body;
  const observer = new MutationObserver(() => injectMenu());
  observer.observe(root, { childList: true, subtree: true });
}

window.addEventListener("wa:ready", mount);
if (document.querySelector(".sidebar__menu")) mount();
else {
  const boot = new MutationObserver(() => {
    if (document.querySelector(".sidebar__menu")) {
      boot.disconnect();
      mount();
    }
  });
  boot.observe(document.documentElement, { childList: true, subtree: true });
}
