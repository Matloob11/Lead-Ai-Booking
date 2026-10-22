/**
 * The two ends of "I have no number yet".
 *
 * A newly added agent opens the panel and there is nothing in it — no numbers,
 * so no chats, and no way to ask for any. Rather than leave them staring at an
 * empty list, the panel asks them to write which number they need, and admins
 * read those notes next to the screen where numbers are actually assigned.
 */

import { access } from "../api/api.js";
import { el, clear, modal, stamp } from "../core/dom.js";
import { icon } from "../core/icons.js";

/**
 * Fills the whole panel for an agent who has no numbers.
 *
 * @param {{me: object, onAssigned: () => void}} options
 *        onAssigned reloads the panel once the agent has been given a number.
 */
export function renderNoNumbersScreen(host, { me, onAssigned, onLinkedDevices } = {}) {
  const note = el("textarea.field.access__note", {
    rows: 4,
    placeholder: "Example: Please assign 971555484423 to me — I manage the Damac Hills 2 property portfolio.",
  });

  const status = el("div.access__status");
  const send = el("button.btn.btn--primary", { type: "button" }, [icon("send", { size: 15 }), "Send request"]);

  send.addEventListener("click", async () => {
    const message = note.value.trim();
    if (!message) {
      status.className = "access__status access__status--err";
      status.textContent = "Please enter which number you require.";
      return;
    }

    send.disabled = true;
    status.className = "access__status";
    status.textContent = "Sending request…";
    try {
      await access.request(message);
      note.value = "";
      status.className = "access__status access__status--ok";
      status.textContent = "Your request was submitted to the administrator. This page will automatically update once a number is assigned.";
    } catch (error) {
      status.className = "access__status access__status--err";
      status.textContent = error.message;
    } finally {
      send.disabled = false;
    }
  });

  // Lead AI access (Agents & access) needs no number: the agent follows every Lead AI chat on the Lead AI screen
  // (apps/leadai/lane.has_desk_access), so the door to it opens here, before any number is assigned.
  const leadAi = me.can_lead_ai
    ? el("div.access__leadai", {}, [
        el("p.access__lead", {}, ["You have Lead AI access. Open the Lead AI screen to follow its chats; no number is needed for that."]),
        el(
          "button.btn.btn--primary.access__leadai-btn",
          { type: "button", onclick: () => window.a7wa?.openLeadAi?.() },
          [icon("smartphone", { size: 15 }), "Open Lead AI"]
        ),
      ])
    : null;

  // The handover desk (modules/lead-ai/handovers.js): the chats the AI handed to this agent as the lead's Bitrix
  // responsible open here too, with no number of their own; the count comes with the sign-in (handover_desk).
  const deskCount = Math.max(0, Number(me.handover_desk?.count) || 0);
  const handovers = me.handover_desk
    ? el("div.access__leadai.access__handovers", {}, [
        el("p.access__lead", {}, [
          deskCount
            ? `${deskCount} chat${deskCount === 1 ? "" : "s"} the AI handed to you ${deskCount === 1 ? "is" : "are"} waiting for you.`
            : "Chats the AI hands to you (as the lead's responsible) open here; no number is needed for that.",
        ]),
        el(
          "button.btn.btn--primary.access__leadai-btn",
          { type: "button", onclick: () => window.a7wa?.openHandovers?.() },
          [icon("messageSquare", { size: 15 }), deskCount ? `My handovers (${deskCount})` : "My handovers"]
        ),
      ])
    : null;

  clear(host).append(
    el("div.access", {}, [
      el("div.access__card", {}, [
        el("div.access__icon", {}, [icon("hash", { size: 26 })]),
        el("h2.access__title", {}, ["No WhatsApp number assigned yet"]),
        handovers,
        leadAi,
        el("p.access__lead", {}, [
          `${me.display_name || "Agent"} — no conversations will be visible until a number is assigned to your account. ` +
            "Please specify below which number you require so an administrator can assist you.",
        ]),
        note,
        el("div.access__actions", {}, [send]),
        status,
        el("button.btn.btn--ghost.access__recheck", { type: "button", onclick: onAssigned }, [
          icon("refresh", { size: 14 }),
          "Number assigned? Recheck now",
        ]),
        // The QR-linked phones are a separate channel with a separate roster, so
        // an agent can hold one of those and no Business Platform number at all.
        // Without this they were shut out of it entirely: this screen replaces
        // the whole inbox, menu included, so the only door to Linked devices was
        // behind a number they had not been given.
        //
        // Offered whether or not a phone is assigned. What they may actually
        // open is decided on the far side by their OpenWA key, and an empty chat
        // list is the honest answer to "nothing has been assigned to you yet" —
        // better than a missing button, which reads as the feature not existing.
        onLinkedDevices
          ? el("button.btn.btn--ghost.access__linked", { type: "button", onclick: onLinkedDevices }, [
              icon("smartphone", { size: 14 }),
              "Open Linked devices",
            ])
          : null,
      ]),
    ])
  );
}

/**
 * The admin side: every agent still waiting, with what they asked for.
 *
 * @param {{onOpenNumbers: () => void}} options
 */
export function openAccessRequests({ onOpenNumbers } = {}) {
  const body = el("div.modal__body", {}, [el("div.thread__hint", {}, ["Loading requests…"])]);
  const dialog = modal("New agent messages", body, { wide: true });

  load();

  async function load() {
    let requests;
    try {
      requests = await access.list();
    } catch (error) {
      clear(body).append(el("div.alert", {}, [`Could not load: ${error.message}`]));
      return;
    }

    if (!requests.length) {
      clear(body).append(el("div.thread__hint", {}, ["No pending requests — all agents have numbers assigned."]));
      return;
    }

    clear(body).append(
      el("p.modal__note", {}, [
        "These agents have requested a WhatsApp number. Open Numbers Management to assign a number.",
      ]),
      el("div.reqs", {}, requests.map(row))
    );
  }

  function row(request) {
    const done = el("button.btn.btn--ghost.btn--sm", { type: "button" }, ["Mark resolved"]);
    const card = el("div.req", {}, [
      el("div.req__head", {}, [
        el("div.req__who", {}, [request.agent?.display_name || `Agent #${request.agent?.id ?? "?"}`]),
        el("div.req__when", {}, [stamp(request.created_at)]),
      ]),
      el("div.req__msg", {}, [request.message || ""]),
      el("div.req__actions", {}, [
        el("button.btn.btn--primary.btn--sm", { type: "button", onclick: () => { dialog.close(); onOpenNumbers?.(); } }, [
          "Assign number",
        ]),
        done,
      ]),
    ]);

    done.addEventListener("click", async () => {
      done.disabled = true;
      try {
        await access.resolve(request.id);
        card.remove();
      } catch (error) {
        done.disabled = false;
        card.append(el("div.access__status.access__status--err", {}, [error.message]));
      }
    });

    return card;
  }

  return dialog;
}
