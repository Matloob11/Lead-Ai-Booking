/**
 * Contact profile drawer beside the Official API thread — WhatsApp-style:
 * teal head, hero identity, Pin / Archive quick actions, blur-save name/notes,
 * media grid, tags, handovers. Click the dimmed chat (backdrop) to close.
 */

import { apiFetch } from "../core/bitrix-sso.js";
import { inbox } from "../api/api.js";
import { clear, el, formatBytes, initials, stamp, toast } from "../core/dom.js";
import { icon } from "../core/icons.js";
import { openLightbox } from "../core/lightbox.js";

const IMAGE_KINDS = new Set(["image", "sticker"]);

const fetchContact = (conversationId) =>
  apiFetch(`/api/inbox/conversations/${conversationId}/contact/`);

const patchContact = (conversationId, body) =>
  apiFetch(`/api/inbox/conversations/${conversationId}/contact/`, { method: "PATCH", body });

/** "3 Aug 2026, 14:20" — profiles are read across days, so the date matters. */
function fullStamp(iso) {
  if (!iso) return "";
  return new Date(iso).toLocaleString([], {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function section(title, ...children) {
  const titleNode =
    typeof title === "string" ? el("h3.cp-block__title", {}, [title]) : title;
  return el("section.cp-block", {}, [titleNode, ...children.flat()]);
}

function row(label, value) {
  return el("div.cp-row", {}, [
    el("span.cp-row__label", {}, [label]),
    el("span.cp-row__value", {}, [value || "—"]),
  ]);
}

/* ------------------------------------------------------------------ panel */

let current = null;

/**
 * @param {number|string} conversationId
 * @param {object}  [options]
 * @param {function} [options.onSaved]  (contact) => void
 * @param {function} [options.onOpenConversation] (id) => void
 */
export function openContactPanel(conversationId, { onSaved, onOpenConversation } = {}) {
  if (current) {
    const same = String(current.conversationId) === String(conversationId);
    current.close();
    if (same) return null;
  }

  const body = el("div.cp-body", {}, [el("div.cp-hint", {}, ["Loading…"])]);
  const closeBtn = el("button.cp-x", { type: "button", title: "Close", "aria-label": "Close" }, [
    icon("close", { size: 18 }),
  ]);
  const backdrop = el("button.cp-backdrop", {
    type: "button",
    "aria-label": "Close contact panel",
    onclick: () => close(),
  });
  const drawer = el(
    "aside.cp",
    { role: "dialog", "aria-modal": "true", "aria-label": "Contact" },
    [el("header.cp-head", {}, [el("div.cp-head__title", {}, ["Contact info"]), closeBtn]), body]
  );

  const onKey = (event) => {
    if (event.key === "Escape") close();
  };

  function close() {
    document.removeEventListener("keydown", onKey, true);
    backdrop.remove();
    drawer.remove();
    document.body.classList.remove("has-cp");
    if (current?.drawer === drawer) current = null;
  }

  closeBtn.addEventListener("click", close);
  document.addEventListener("keydown", onKey, true);
  document.body.append(backdrop, drawer);
  document.body.classList.add("has-cp");
  current = { conversationId, drawer, close };

  fetchContact(conversationId).then(
    (data) => render(data),
    (error) =>
      clear(body).append(el("div.cp-alert", {}, [`Could not load the profile: ${error.message}`]))
  );

  function render(data) {
    clear(body);
    body.append(
      identity(data),
      quickActions(data),
      editable(data),
      gallery(data),
      tagPicker(data),
      handledBy(data),
      activity(data),
      history(data),
      elsewhere(data)
    );
  }

  function identity(data) {
    const label = data.display_name || data.profile_name || data.wa_id;
    const phone = data.wa_id ? `+${data.wa_id}` : "";
    const phoneBtn = phone
      ? el(
          "button.cp-hero__phone",
          {
            type: "button",
            title: "Copy number",
            onclick: async () => {
              try {
                await navigator.clipboard.writeText(phone);
                toast("Number copied", "ok");
              } catch {
                toast("Could not copy", "err");
              }
            },
          },
          [phone]
        )
      : null;

    return el("div.cp-hero", {}, [
      el("div.cp-avatar.cp-avatar--lg", {}, [initials(label)]),
      el("div.cp-hero__name", {}, [label]),
      phoneBtn,
      data.profile_name && data.profile_name !== data.display_name
        ? el("div.cp-hero__wa", {}, [`WhatsApp · ${data.profile_name}`])
        : null,
    ]);
  }

  function quickActions(data) {
    const conv = data.conversation || {};
    let pinned = !!conv.is_pinned;
    let busy = false;
    const rowEl = el("div.cp-quick");

    async function toggle(field, value) {
      if (busy) return;
      busy = true;
      try {
        const updated = await inbox.setFlags(conversationId, { [field]: value });
        if (data.conversation) Object.assign(data.conversation, updated);
        pinned = !!updated.is_pinned;
        onSaved?.(data);
        paint();
        if (field === "is_pinned") {
          toast(value ? "Chat pinned" : "Chat unpinned", "ok");
        }
      } catch (err) {
        toast(err.message || "Could not save", "err");
      } finally {
        busy = false;
      }
    }

    function paint() {
      clear(rowEl).append(
        el(
          "button.cp-quick__btn",
          {
            type: "button",
            class: pinned ? "is-on" : "",
            onclick: () => toggle("is_pinned", !pinned),
          },
          [icon("pin", { size: 18 }), el("span", {}, [pinned ? "Unpin" : "Pin"])]
        )
      );
    }
    paint();
    return rowEl;
  }

  function editable(data) {
    const flash = el("span.cp-status.cp-status--ok", { hidden: true }, ["Saved"]);
    const fieldError = el("div.cp-field-error", { hidden: true });

    const name = el("input.cp-input.cp-input--with-clear", {
      type: "text",
      value: data.display_name || "",
      placeholder: data.profile_name || "Type a team name…",
      maxlength: "255",
      "aria-label": "Team name",
    });
    const clearBtn = el(
      "button.cp-clear",
      {
        type: "button",
        title: "Clear name",
        "aria-label": "Clear name",
        hidden: !name.value,
        onmousedown: (e) => e.preventDefault(),
        onclick: () => {
          name.value = "";
          clearBtn.hidden = true;
          name.focus();
        },
      },
      [icon("close", { size: 14 })]
    );
    name.addEventListener("input", () => {
      clearBtn.hidden = !name.value;
      fieldError.hidden = true;
    });

    const notes = el("textarea.cp-input.cp-notes", {
      rows: 4,
      placeholder: "What has been agreed, what they are looking for, budget…",
    });
    notes.value = data.notes || "";
    notes.addEventListener("input", () => {
      fieldError.hidden = true;
    });

    const hint = data.display_name
      ? el("span.cp-field__hint", {}, [`Current: ${data.display_name}`])
      : data.profile_name
        ? el("span.cp-field__hint", {}, [`From WhatsApp: ${data.profile_name}`])
        : null;

    let saving = false;
    async function save() {
      if (saving) return;
      const next = { display_name: name.value.trim(), notes: notes.value };
      if (next.display_name === (data.display_name || "") && next.notes === (data.notes || "")) return;

      saving = true;
      fieldError.hidden = true;
      flash.hidden = true;
      try {
        const fresh = await patchContact(conversationId, next);
        data.display_name = fresh.display_name;
        data.notes = fresh.notes;
        flash.hidden = false;
        flash.textContent = "Saved";
        flash.className = "cp-status cp-status--ok";
        setTimeout(() => {
          flash.hidden = true;
        }, 1600);
        onSaved?.(fresh);
        const heading = body.querySelector(".cp-hero__name");
        if (heading) heading.textContent = fresh.display_name || fresh.profile_name || fresh.wa_id;
      } catch (error) {
        fieldError.hidden = false;
        clear(fieldError).append(error.message || "Could not save");
        toast(error.message || "Could not save profile", "err");
      } finally {
        saving = false;
      }
    }

    name.addEventListener("blur", save);
    name.addEventListener("keydown", (event) => event.key === "Enter" && name.blur());
    notes.addEventListener("blur", save);

    return el("section.cp-block", {}, [
      el("h3.cp-block__title", {}, ["Name and notes", flash]),
      el("label.cp-field", {}, [
        el("span.cp-field__label", {}, ["Team name", hint]),
        el("div.cp-input-wrap", {}, [name, clearBtn]),
      ]),
      el("label.cp-field", {}, [el("span.cp-field__label", {}, ["Notes"]), notes]),
      fieldError,
      el("div.cp-note", {}, ["Only your team sees this. The customer never does."]),
    ]);
  }

  function tagPicker(data) {
    const container = el("div.cp-tags");
    const addRow = el("div.cp-tag-add");
    const conv = data.conversation || {};
    let activeIds = new Set((conv.labels || []).map((l) => l.id));
    let allLabels = [];

    async function loadTags() {
      clear(container).append(el("span.cp-muted", {}, ["Loading tags…"]));
      try {
        allLabels = await inbox.labels();
        renderTags();
      } catch (err) {
        clear(container).append(el("span.cp-muted", {}, [`Failed: ${err.message}`]));
      }
    }

    function renderTags() {
      clear(container);
      if (!allLabels.length) {
        container.append(el("span.cp-muted", {}, ["No labels yet — create one below."]));
      }
      for (const label of allLabels) {
        const isActive = activeIds.has(label.id);
        container.append(
          el(
            "button.cp-tag-chip",
            {
              type: "button",
              style: `border-color:${label.colour};background:${isActive ? label.colour : "transparent"};color:${isActive ? "#fff" : label.colour}`,
              onclick: async () => {
                if (isActive) activeIds.delete(label.id);
                else activeIds.add(label.id);
                renderTags();
                try {
                  const updated = await inbox.setFlags(conversationId, { label_ids: [...activeIds] });
                  if (data.conversation) data.conversation.labels = updated.labels;
                  onSaved?.(data);
                } catch (err) {
                  toast(`Tag update failed: ${err.message}`, "err");
                }
              },
            },
            [label.name]
          )
        );
      }
    }

    const nameInput = el("input.cp-input", {
      type: "text",
      placeholder: "New label name",
      maxlength: 64,
    });
    const addBtn = el("button.cp-btn", { type: "button" }, ["Add label"]);
    addBtn.addEventListener("click", async () => {
      const name = nameInput.value.trim();
      if (!name) return;
      addBtn.disabled = true;
      try {
        const created = await inbox.createLabel({ name, colour: "#25D366" });
        allLabels.push(created);
        activeIds.add(created.id);
        nameInput.value = "";
        renderTags();
        const updated = await inbox.setFlags(conversationId, { label_ids: [...activeIds] });
        if (data.conversation) data.conversation.labels = updated.labels;
        onSaved?.(data);
        toast("Label added", "ok");
      } catch (err) {
        toast(err.message || "Could not create label", "err");
      } finally {
        addBtn.disabled = false;
      }
    });
    clear(addRow).append(nameInput, addBtn);
    loadTags();

    return section(
      "Tags",
      container,
      addRow,
      el("div.cp-note", {}, ["Click a tag to toggle it on this chat. New labels are shared with the team."])
    );
  }

  function handledBy(data) {
    const agent = data.assigned_agent;
    const rows = [
      row("Our number", `${data.number?.title || "—"} · +${data.number?.phone_number || ""}`),
    ];

    if (agent) {
      rows.push(row("Agent", agent.community ? `${agent.display_name} · ${agent.community}` : agent.display_name));
      if (agent.bitrix_user_id) rows.push(row("Bitrix ID", agent.bitrix_user_id));
      const held = agent.numbers || [];
      rows.push(
        el("div.cp-row", {}, [
          el("span.cp-row__label", {}, [held.length > 1 ? "Their numbers" : "Their number"]),
          held.length
            ? el(
                "span.cp-row__value",
                {},
                held.map((n) =>
                  el("span.cp-num", {}, [
                    `${n.title}${n.title === n.phone_number ? "" : ` · +${n.phone_number}`}`,
                  ])
                )
              )
            : el("span.cp-row__value.cp-row__value--muted", {}, ["None assigned"]),
        ])
      );
    } else {
      rows.push(
        el("div.cp-note", {}, [
          "Nobody owns this chat yet. Anyone on the number can answer it; Transfer assigns it.",
        ])
      );
    }

    return section("Handled by", rows);
  }

  function activity(data) {
    const stats = data.stats || {};
    const conversation = data.conversation || {};
    return section(
      "Activity",
      el("div.cp-stats", {}, [
        el("div.cp-stat", {}, [el("b", {}, [String(stats.total ?? 0)]), el("span", {}, ["messages"])]),
        el("div.cp-stat", {}, [el("b", {}, [String(stats.inbound ?? 0)]), el("span", {}, ["received"])]),
        el("div.cp-stat", {}, [el("b", {}, [String(stats.outbound ?? 0)]), el("span", {}, ["sent"])]),
        stats.failed
          ? el("div.cp-stat.cp-stat--bad", {}, [el("b", {}, [String(stats.failed)]), el("span", {}, ["failed"])])
          : null,
      ]),
      row("First message", fullStamp(stats.first_message_at)),
      row("Known since", fullStamp(data.first_seen_at)),
      row(
        "Reply window",
        conversation.is_session_open
          ? `Open until ${fullStamp(conversation.session_expires_at)}`
          : "Closed — only a template can be sent"
      )
    );
  }

  function history(data) {
    const logs = data.assignment_history || [];
    if (!logs.length) {
      return section("Handovers", el("div.cp-note", {}, ["This chat has never been transferred."]));
    }

    return section(
      "Handovers",
      el(
        "ol.cp-timeline",
        {},
        logs.map((log) =>
          el("li.cp-event", {}, [
            el("div.cp-event__line", {}, [
              el("b", {}, [log.from_agent?.display_name || "Unassigned"]),
              " → ",
              el("b", {}, [log.to_agent?.display_name || "Unassigned"]),
            ]),
            log.reason ? el("div.cp-event__reason", {}, [log.reason]) : null,
            el("div.cp-event__meta", {}, [
              fullStamp(log.created_at),
              log.changed_by ? ` · by ${log.changed_by.display_name}` : "",
            ]),
          ])
        )
      )
    );
  }

  function gallery(data) {
    const media = data.media || [];
    const title = el("h3.cp-block__title", {}, [
      "Media",
      media.length ? el("span.cp-count", {}, [String(media.length)]) : null,
    ]);
    if (!media.length) {
      return section(title, el("div.cp-note", {}, ["No photos, videos, or files in this chat yet."]));
    }

    const images = media.filter((m) => IMAGE_KINDS.has(m.kind) || m.kind === "video");
    const files = media.filter((m) => !IMAGE_KINDS.has(m.kind) && m.kind !== "video");
    const parts = [];

    if (images.length) {
      const lightboxItems = images
        .filter((i) => i.url && IMAGE_KINDS.has(i.kind))
        .map((i) => ({ url: i.url, name: i.name, mime: i.mime }));
      parts.push(
        el(
          "div.cp-grid",
          {},
          images.map((m) => {
            const isVideo = m.kind === "video";
            if (m.url && IMAGE_KINDS.has(m.kind)) {
              const lbIndex = lightboxItems.findIndex((i) => i.url === m.url);
              return el("button.cp-thumb", {
                type: "button",
                title: m.name || m.kind,
                style: `background-image:url("${m.url}")`,
                onclick: () => openLightbox(lightboxItems, Math.max(0, lbIndex)),
              });
            }
            return el(
              "button.cp-tile",
              {
                type: "button",
                class: `cp-tile--${m.kind || "file"}`,
                title: m.name || m.kind,
                onclick: () => {
                  if (m.url) window.open(m.url, "_blank", "noopener,noreferrer");
                },
              },
              [icon(isVideo ? "video" : "image", { size: 18 }), el("span", {}, [m.kind || "file"])]
            );
          })
        )
      );
    }

    for (const file of files) {
      parts.push(
        el("a.cp-file", { href: file.url, target: "_blank", rel: "noopener" }, [
          icon("file", { size: 15 }),
          el("span.cp-file__name", {}, [file.name || file.kind]),
          el("span.cp-file__size", {}, [formatBytes(file.size)]),
        ])
      );
    }

    return section(title, parts);
  }

  function elsewhere(data) {
    const others = data.other_conversations || [];
    if (!others.length) return el("div", { hidden: true });

    return section(
      "Also talking to us on",
      el("div.cp-note", {}, ["The same customer, on another of our numbers."]),
      others.map((other) =>
        el(
          "button.cp-other",
          {
            type: "button",
            onclick: () => {
              close();
              onOpenConversation?.(other.id);
            },
          },
          [
            el("span.cp-other__num", {}, [other.contact?.name || `Chat #${other.id}`]),
            el("span.cp-other__when", {}, [stamp(other.last_message_at)]),
            el("span.cp-other__last", {}, [other.last_message_preview || ""]),
          ]
        )
      )
    );
  }

  return { close };
}

export function closeContactPanel() {
  current?.close();
}
