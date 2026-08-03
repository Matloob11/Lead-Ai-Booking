/**
 * The person behind a chat, in a drawer beside it.
 *
 * Everything the panel knows about one customer, on one surface: what to call
 * them, what has been agreed with them, who is handling them and on which of
 * our numbers, every handover the chat has been through, and every file that
 * has passed either way.
 *
 * Two of those fields are ours to write — the name and the notes — and they are
 * saved where they are read rather than behind an edit mode, because the moment
 * an agent learns a customer's real name is the moment they are looking at this.
 *
 * Phone-width and fixed to the right edge: it sits beside the thread the way a
 * profile does in WhatsApp, and the conversation stays visible behind it.
 */

import { apiFetch } from "../core/bitrix-sso.js";
import { inbox } from "../api/api.js";
import { clear, el, formatBytes, initials, stamp } from "../core/dom.js";
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
  return el("section.cp-block", {}, [el("h3.cp-block__title", {}, [title]), ...children.flat()]);
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
 * @param {function} [options.onSaved]  (contact) => void, after a name or note
 *                                      is written — the list shows the name too
 * @param {function} [options.onOpenConversation] (id) => void, for the other
 *                                      chats this customer has with us
 */
export function openContactPanel(conversationId, { onSaved, onOpenConversation } = {}) {
  // Only ever one open, and clicking the same profile again closes it.
  if (current) {
    const same = String(current.conversationId) === String(conversationId);
    current.close();
    if (same) return null;
  }

  const body = el("div.cp-body", {}, [el("div.cp-hint", {}, ["Loading…"])]);
  const closeBtn = el("button.cp-x", { type: "button", title: "Close" }, [icon("close", { size: 18 })]);
  const drawer = el("aside.cp", {}, [
    el("header.cp-head", {}, [el("div.cp-head__title", {}, ["Contact"]), closeBtn]),
    body,
  ]);

  const onKey = (event) => {
    if (event.key === "Escape") close();
  };

  function close() {
    document.removeEventListener("keydown", onKey, true);
    drawer.remove();
    document.body.classList.remove("has-cp");
    if (current?.drawer === drawer) current = null;
  }

  closeBtn.addEventListener("click", close);
  document.addEventListener("keydown", onKey, true);
  document.body.append(drawer);
  document.body.classList.add("has-cp");
  current = { conversationId, drawer, close };

  fetchContact(conversationId).then(
    (data) => render(data),
    (error) => clear(body).append(el("div.alert", {}, [`Could not load the profile: ${error.message}`]))
  );

  /* ---------------------------------------------------------- rendering */

  function render(data) {
    clear(body);

    body.append(
      identity(data),
      editable(data),
      tagPicker(data),
      handledBy(data),
      activity(data),
      history(data),
      gallery(data),
      elsewhere(data)
    );
  }

  function identity(data) {
    const label = data.display_name || data.profile_name || data.wa_id;
    return el("div.cp-identity", {}, [
      el("div.cp-avatar", {}, [initials(label)]),
      el("div.cp-identity__text", {}, [
        el("div.cp-identity__name", {}, [label]),
        el("div.cp-identity__wa", {}, [`+${data.wa_id}`]),
        // What they call themselves on WhatsApp, kept visible even once an
        // agent has renamed them — it is how the customer signs their own
        // messages, and worth being able to check against.
        data.profile_name && data.profile_name !== data.display_name
          ? el("div.cp-identity__profile", {}, [`WhatsApp name: ${data.profile_name}`])
          : null,
      ]),
    ]);
  }

  /** The two fields that are ours to write. Saved where they are read. */
  function editable(data) {
    const flash = el("span.cp-saved", { hidden: true }, ["Saved"]);

    const name = el("input.cp-input", {
      type: "text",
      value: data.display_name || "",
      placeholder: data.profile_name || "Name this contact",
      maxlength: "255",
    });

    const notes = el("textarea.cp-input.cp-notes", {
      rows: 4,
      placeholder: "What has been agreed, what they are looking for, budget…",
    });
    notes.value = data.notes || "";

    let saving = false;
    async function save() {
      if (saving) return;
      const next = { display_name: name.value.trim(), notes: notes.value };
      if (next.display_name === (data.display_name || "") && next.notes === (data.notes || "")) return;

      saving = true;
      try {
        const fresh = await patchContact(conversationId, next);
        data.display_name = fresh.display_name;
        data.notes = fresh.notes;
        flash.hidden = false;
        setTimeout(() => (flash.hidden = true), 1600);
        onSaved?.(fresh);
        // The heading carries the name, so it has to follow the field.
        const heading = body.querySelector(".cp-identity__name");
        if (heading) heading.textContent = fresh.display_name || fresh.profile_name || fresh.wa_id;
      } catch (error) {
        flash.hidden = false;
        flash.textContent = error.message;
        setTimeout(() => {
          flash.hidden = true;
          flash.textContent = "Saved";
        }, 4000);
      } finally {
        saving = false;
      }
    }

    name.addEventListener("blur", save);
    name.addEventListener("keydown", (event) => event.key === "Enter" && name.blur());
    notes.addEventListener("blur", save);

    return el("section.cp-block", {}, [
      el("h3.cp-block__title", {}, ["Name and notes", flash]),
      el("label.cp-field", {}, [el("span", {}, ["Name"]), name]),
      el("label.cp-field", {}, [el("span", {}, ["Notes"]), notes]),
      el("div.cp-note", {}, ["Only your team sees this. The customer never does."]),
    ]);
  }

  function tagPicker(data) {
    const container = el("div.cp-tags", { style: "display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px;" });
    const conv = data.conversation || {};
    let activeIds = new Set((conv.labels || []).map((l) => l.id));

    async function loadTags() {
      clear(container).append(el("span.cp-note", {}, ["Loading tags…"]));
      try {
        const allLabels = await inbox.labels();
        renderTags(allLabels);
      } catch (err) {
        clear(container).append(el("span.cp-note", {}, [`Failed: ${err.message}`]));
      }
    }

    function renderTags(allLabels) {
      clear(container);
      for (const label of allLabels) {
        const isActive = activeIds.has(label.id);
        const tagChip = el(
          "button.cp-tag-chip",
          {
            type: "button",
            style: `cursor: pointer; border: 1px solid ${label.colour}; background: ${isActive ? label.colour : "transparent"}; color: ${isActive ? "#fff" : label.colour}; padding: 3px 10px; border-radius: 12px; font-size: 11px; font-weight: 600; transition: all 0.15s ease;`,
            onclick: async () => {
              if (isActive) {
                activeIds.delete(label.id);
              } else {
                activeIds.add(label.id);
              }
              renderTags(allLabels);
              try {
                const updated = await inbox.setFlags(conversationId, { label_ids: [...activeIds] });
                if (data.conversation) data.conversation.labels = updated.labels;
                onSaved?.(data);
              } catch (err) {
                alert(`Tag update failed: ${err.message}`);
              }
            },
          },
          [label.name]
        );
        container.append(tagChip);
      }
    }

    loadTags();

    return el("section.cp-block", {}, [
      el("h3.cp-block__title", {}, ["Customer Tags & Labels"]),
      container,
      el("div.cp-note", {}, ["Click tag to toggle on/off for this customer"]),
    ]);
  }

  function handledBy(data) {
    const agent = data.assigned_agent;
    const rows = [
      row("Our number", `${data.number?.title || "—"} · +${data.number?.phone_number || ""}`),
    ];

    if (agent) {
      rows.push(row("Agent", agent.display_name));
      if (agent.bitrix_user_id) rows.push(row("Bitrix ID", agent.bitrix_user_id));
      // Which of our numbers that agent holds, so whoever is reading knows
      // where to reach them and what else they are carrying. Saying "none"
      // out loud beats an absent row: an owner with no number of their own is
      // usually an admin covering for somebody, which is worth knowing.
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

    const labels = data.conversation?.labels || [];
    if (labels.length) {
      rows.push(
        el("div.cp-row", {}, [
          el("span.cp-row__label", {}, ["Labels"]),
          el(
            "span.cp-row__value",
            {},
            labels.map((l) =>
              el("span.cp-label", { style: l.colour ? `background:${l.colour}` : "" }, [l.name])
            )
          ),
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
          : "Closed — a template is needed to reopen it"
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
    if (!media.length) {
      return section("Files", el("div.cp-note", {}, ["Nothing has been sent either way yet."]));
    }

    const images = media.filter((m) => IMAGE_KINDS.has(m.kind));
    const files = media.filter((m) => !IMAGE_KINDS.has(m.kind));
    const parts = [];

    if (images.length) {
      parts.push(
        el(
          "div.cp-grid",
          {},
          images.map((m, index) =>
            el("button.cp-thumb", {
              type: "button",
              title: m.name || "",
              style: `background-image:url("${m.url}")`,
              onclick: () =>
                openLightbox(
                  images.map((i) => ({ url: i.url, name: i.name, mime: i.mime })),
                  index
                ),
            })
          )
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

    return section(`Files (${media.length})`, parts);
  }

  function elsewhere(data) {
    const others = data.other_conversations || [];
    if (!others.length) return el("div", { hidden: true });

    // The same person writing to two of our numbers is two chats, and an agent
    // who cannot see that answers half a conversation.
    return section(
      "Also talking to us on",
      el("div.cp-note", {}, ["The same customer, on another of our numbers."]),
      others.map((other) =>
        el(
          "button.cp-other",
          { type: "button", onclick: () => { close(); onOpenConversation?.(other.id); } },
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
