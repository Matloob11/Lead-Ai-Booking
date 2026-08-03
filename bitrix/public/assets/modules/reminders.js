/**
 * KAAM B — REMINDERS (reminders.js)
 * Set follow-up reminders, display badge count in topbar, dropdown list,
 * preset + custom datetimepicker, WebAudio sound beep, and real-time toast alert on reminder.due.
 */

import { el, clear, untilText, stamp, modal } from "../core/dom.js";
import { getReminders, createReminder, markReminderDone, deleteReminder } from "../api/api-extras.js";

function getActiveConversationId() {
  return (
    window.a7wa?.activeConversationId ||
    window.a7wa?.getActiveConversationId?.() ||
    document.querySelector(".thread__composer")?.dataset?.conversationId ||
    document.querySelector("#wa-composer-slot")?.dataset?.conversationId ||
    null
  );
}

function toISOWithOffset(date) {
  const tzo = -date.getTimezoneOffset();
  const dif = tzo >= 0 ? "+" : "-";
  const pad = (num) => String(Math.floor(Math.abs(num))).padStart(2, "0");

  return (
    date.getFullYear() +
    "-" +
    pad(date.getMonth() + 1) +
    "-" +
    pad(date.getDate()) +
    "T" +
    pad(date.getHours()) +
    ":" +
    pad(date.getMinutes()) +
    ":" +
    pad(date.getSeconds()) +
    dif +
    pad(tzo / 60) +
    ":" +
    pad(tzo % 60)
  );
}

function playBeep() {
  try {
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    if (!AudioCtx) return;
    const ctx = new AudioCtx();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = "sine";
    osc.frequency.setValueAtTime(587.33, ctx.currentTime); // D5
    gain.gain.setValueAtTime(0.12, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.5);
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start();
    osc.stop(ctx.currentTime + 0.5);
  } catch (_) {}
}

function showToast({ contactName, note, conversationId }) {
  let toastContainer = document.querySelector(".wa-x-toast-container");
  if (!toastContainer) {
    toastContainer = el("div.wa-x-toast-container");
    document.body.appendChild(toastContainer);
  }

  const dismiss = () => {
    toast.classList.add("wa-x-toast--hiding");
    setTimeout(() => toast.remove(), 300);
  };

  const timer = setTimeout(dismiss, 8000);

  const toast = el("div.wa-x-toast", {}, [
    el("div.wa-x-toast-head", {}, [
      el("div.wa-x-toast-title", {}, ["⏰ Reminder Alert"]),
      el("button.wa-x-toast-close", { type: "button", onclick: () => { clearTimeout(timer); dismiss(); } }, ["×"]),
    ]),
    el("div.wa-x-toast-contact", {}, [contactName]),
    el("div.wa-x-toast-note", {}, [note || "Follow-up reminder"]),
    el("div.wa-x-toast-actions", {}, [
      el(
        "button.wa-x-btn.wa-x-btn--sm.wa-x-btn--primary",
        {
          type: "button",
          onclick: () => {
            clearTimeout(timer);
            dismiss();
            if (conversationId && typeof window.a7wa?.openConversation === "function") {
              window.a7wa.openConversation(conversationId);
            }
          },
        },
        ["Open"]
      ),
    ]),
  ]);

  toastContainer.appendChild(toast);
}

export function mountReminders() {
  mountTopbar();
  mountComposerClock();
  listenEvents();
}

let refreshTopbarBadge = () => {};

function mountTopbar() {
  const slot = document.querySelector("#wa-topbar-slot");
  if (!slot) {
    console.warn("[reminders.js] #wa-topbar-slot anchor missing — topbar bell skipped");
    return;
  }

  clear(slot);

  const bellIcon = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  bellIcon.setAttribute("viewBox", "0 0 24 24");
  bellIcon.setAttribute("width", "18");
  bellIcon.setAttribute("height", "18");
  bellIcon.setAttribute("fill", "none");
  bellIcon.setAttribute("stroke", "currentColor");
  bellIcon.setAttribute("stroke-width", "2");
  bellIcon.setAttribute("stroke-linecap", "round");
  bellIcon.setAttribute("stroke-linejoin", "round");
  const bellPath = document.createElementNS("http://www.w3.org/2000/svg", "path");
  bellPath.setAttribute("d", "M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9M13.73 21a2 2 0 01-3.46 0");
  bellIcon.appendChild(bellPath);

  const badge = el("span.wa-x-badge", { hidden: true }, ["0"]);
  const dropdown = el("div.wa-x-reminders-dropdown", { hidden: true });

  const bellBtn = el("button.wa-x-btn-icon", { type: "button", title: "Reminders" }, [bellIcon, badge]);

  const container = el("div.wa-x-topbar-container", {}, [bellBtn, dropdown]);
  slot.append(container);

  const loadAndRenderList = async () => {
    dropdown.replaceChildren(el("div.wa-x-reminders-status", {}, ["Loading…"]));
    try {
      const items = await getReminders({ open: 1 });
      const reminders = Array.isArray(items) ? items : [];

      // Update badge
      if (reminders.length > 0) {
        badge.textContent = String(reminders.length);
        badge.hidden = false;
      } else {
        badge.hidden = true;
      }

      clear(dropdown);

      if (!reminders.length) {
        dropdown.append(el("div.wa-x-reminders-empty", {}, ["No open reminders."]));
        return;
      }

      // Sort by due_at ascending
      reminders.sort((a, b) => new Date(a.due_at) - new Date(b.due_at));

      const head = el("div.wa-x-reminders-head", {}, ["Open Reminders"]);
      const list = el("div.wa-x-reminders-list");

      reminders.forEach((r) => {
        const contactName = r.conversation?.contact?.name || r.conversation?.contact?.wa_id || "Unknown chat";
        const relTime = untilText(r.due_at);
        const timeText = relTime ? `in ${relTime}` : `Overdue (${stamp(r.due_at)})`;

        const checkBtn = el(
          "button.wa-x-action-btn",
          {
            type: "button",
            title: "Mark Done",
            onclick: async (e) => {
              e.stopPropagation();
              checkBtn.disabled = true;
              try {
                await markReminderDone(r.id);
                await loadAndRenderList();
              } catch (err) {
                alert(`Error: ${err.message}`);
              }
            },
          },
          ["✓"]
        );

        const deleteBtn = el(
          "button.wa-x-action-btn.wa-x-action-btn--del",
          {
            type: "button",
            title: "Delete",
            onclick: async (e) => {
              e.stopPropagation();
              deleteBtn.disabled = true;
              try {
                await deleteReminder(r.id);
                await loadAndRenderList();
              } catch (err) {
                alert(`Error: ${err.message}`);
              }
            },
          },
          ["🗑"]
        );

        const row = el(
          "div.wa-x-reminder-row",
          {
            onclick: () => {
              if (r.conversation?.id && typeof window.a7wa?.openConversation === "function") {
                window.a7wa.openConversation(r.conversation.id);
              }
              dropdown.hidden = true;
            },
          },
          [
            el("div.wa-x-reminder-body", {}, [
              el("div.wa-x-reminder-contact", {}, [contactName]),
              el("div.wa-x-reminder-note", {}, [r.note || "No note"]),
              el("div.wa-x-reminder-time", {}, [timeText]),
            ]),
            el("div.wa-x-reminder-actions", {}, [checkBtn, deleteBtn]),
          ]
        );

        list.append(row);
      });

      dropdown.append(head, list);
    } catch (err) {
      clear(dropdown).append(
        el("div.wa-x-reminders-status.wa-x-reminders-status--err", {}, [`Error: ${err.message}`])
      );
    }
  };

  refreshTopbarBadge = loadAndRenderList;

  bellBtn.addEventListener("click", () => {
    dropdown.hidden = !dropdown.hidden;
    if (!dropdown.hidden) {
      loadAndRenderList();
    }
  });

  document.addEventListener("click", (e) => {
    if (!container.contains(e.target)) {
      dropdown.hidden = true;
    }
  });

  // Initial fetch for badge count
  loadAndRenderList();
}

function mountComposerClock() {
  const slot = document.querySelector("#wa-composer-slot");
  if (!slot) {
    console.warn("[reminders.js] #wa-composer-slot anchor missing — clock icon skipped");
    return;
  }

  const clockIcon = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  clockIcon.setAttribute("viewBox", "0 0 24 24");
  clockIcon.setAttribute("width", "18");
  clockIcon.setAttribute("height", "18");
  clockIcon.setAttribute("fill", "none");
  clockIcon.setAttribute("stroke", "currentColor");
  clockIcon.setAttribute("stroke-width", "2");
  clockIcon.setAttribute("stroke-linecap", "round");
  clockIcon.setAttribute("stroke-linejoin", "round");
  const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
  circle.setAttribute("cx", "12");
  circle.setAttribute("cy", "12");
  circle.setAttribute("r", "10");
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("d", "M12 6v6l4 2");
  clockIcon.appendChild(circle);
  clockIcon.appendChild(path);

  const menu = el("div.wa-x-preset-menu", { hidden: true });

  const clockBtn = el("button.wa-x-btn-icon", { type: "button", title: "Set Reminder" }, [clockIcon]);

  const container = el("div.wa-x-composer-clock-wrapper", {}, [clockBtn, menu]);
  slot.append(container);

  const openReminderDialog = (initialDate = new Date()) => {
    const convId = getActiveConversationId();
    if (!convId) {
      alert("Select a conversation first.");
      return;
    }

    // Format initial date for datetime-local input YYYY-MM-DDTHH:mm
    const localIsoStr = new Date(initialDate.getTime() - initialDate.getTimezoneOffset() * 60000)
      .toISOString()
      .slice(0, 16);

    const dtInput = el("input.wa-x-field", { type: "datetime-local", value: localIsoStr });
    const noteInput = el("input.wa-x-field", { type: "text", placeholder: "Note (e.g. Call back re Damac)" });
    const errorEl = el("div.wa-x-alert", { hidden: true });
    const submitBtn = el("button.wa-x-btn.wa-x-btn--primary", { type: "button" }, ["Set reminder"]);

    const content = el("div.wa-x-modal-body", {}, [
      el("label.wa-x-field-row", {}, [el("span", {}, ["Due at"]), dtInput]),
      el("label.wa-x-field-row", {}, [el("span", {}, ["Note"]), noteInput]),
      errorEl,
      el("div.wa-x-modal-actions", {}, [submitBtn]),
    ]);

    const dlg = modal("Set Reminder", content);

    submitBtn.addEventListener("click", async () => {
      errorEl.hidden = true;
      const dtValue = dtInput.value;
      if (!dtValue) {
        errorEl.textContent = "Choose a time.";
        errorEl.hidden = false;
        return;
      }

      const selectedDate = new Date(dtValue);
      if (Number.isNaN(selectedDate.getTime())) {
        errorEl.textContent = "That time is not valid.";
        errorEl.hidden = false;
        return;
      }

      if (selectedDate <= new Date()) {
        errorEl.textContent = "Choose a time in the future.";
        errorEl.hidden = false;
        return;
      }

      submitBtn.disabled = true;
      submitBtn.textContent = "Saving…";

      try {
        const isoString = toISOWithOffset(selectedDate);
        await createReminder(convId, {
          due_at: isoString,
          note: noteInput.value.trim() || "Follow-up",
        });

        dlg.close();
        refreshTopbarBadge();
      } catch (err) {
        submitBtn.disabled = false;
        submitBtn.textContent = "Set reminder";
        errorEl.textContent = err.message || "The reminder could not be created.";
        errorEl.hidden = false;
      }
    });
  };

  const getTomorrow9AM = () => {
    const d = new Date();
    d.setDate(d.getDate() + 1);
    d.setHours(9, 0, 0, 0);
    return d;
  };

  const options = [
    { label: "30 minutes", getDate: () => new Date(Date.now() + 30 * 60000) },
    { label: "1 hour", getDate: () => new Date(Date.now() + 60 * 60000) },
    { label: "3 hours", getDate: () => new Date(Date.now() + 180 * 60000) },
    { label: "Tomorrow 9 am", getDate: getTomorrow9AM },
    { label: "Custom…", getDate: null },
  ];

  clear(menu);
  options.forEach((opt) => {
    menu.append(
      el(
        "button.wa-x-preset-item",
        {
          type: "button",
          onclick: () => {
            menu.hidden = true;
            if (opt.getDate) {
              openReminderDialog(opt.getDate());
            } else {
              openReminderDialog(new Date());
            }
          },
        },
        [opt.label]
      )
    );
  });

  clockBtn.addEventListener("click", () => {
    menu.hidden = !menu.hidden;
  });

  document.addEventListener("click", (e) => {
    if (!container.contains(e.target)) {
      menu.hidden = true;
    }
  });
}

function listenEvents() {
  window.addEventListener("wa:event", (e) => {
    const detail = e?.detail;
    if (detail && detail.event === "reminder.due") {
      const data = detail.data || {};
      playBeep();
      showToast({
        contactName: data.conversation?.contact?.name || data.conversation?.contact?.wa_id || "Contact",
        note: data.note,
        conversationId: data.conversation?.id,
      });
      refreshTopbarBadge();
    }
  });
}
