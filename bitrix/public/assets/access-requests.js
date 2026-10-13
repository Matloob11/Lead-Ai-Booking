/**
 * The two ends of "I have no number yet".
 *
 * A newly added agent opens the panel and there is nothing in it — no numbers,
 * so no chats, and no way to ask for any. Rather than leave them staring at an
 * empty list, the panel asks them to write which number they need, and admins
 * read those notes next to the screen where numbers are actually assigned.
 */

import { access } from "./api.js";
import { el, clear, modal, stamp } from "./dom.js";
import { icon } from "./icons.js";

/**
 * Fills the whole panel for an agent who has no numbers.
 *
 * @param {{me: object, onAssigned: () => void}} options
 *        onAssigned reloads the panel once the agent has been given a number.
 */
export function renderNoNumbersScreen(host, { me, onAssigned }) {
  const note = el("textarea.field.access__note", {
    rows: 4,
    placeholder: "Maslan: mujhe 971555484423 assign kar dein — main Damac Hills 2 par kaam kar raha hoon.",
  });

  const status = el("div.access__status");
  const send = el("button.btn.btn--primary", { type: "button" }, [icon("send", { size: 15 }), "Request bhejein"]);

  send.addEventListener("click", async () => {
    const message = note.value.trim();
    if (!message) {
      status.className = "access__status access__status--err";
      status.textContent = "Pehle likhein ke aap ko kaunsa number chahiye.";
      return;
    }

    send.disabled = true;
    status.className = "access__status";
    status.textContent = "Bhej rahe hain…";
    try {
      await access.request(message);
      note.value = "";
      status.className = "access__status access__status--ok";
      status.textContent = "Aap ki request admin ko chali gayi. Number milte hi ye page khud khul jayega.";
    } catch (error) {
      status.className = "access__status access__status--err";
      status.textContent = error.message;
    } finally {
      send.disabled = false;
    }
  });

  clear(host).append(
    el("div.access", {}, [
      el("div.access__card", {}, [
        el("div.access__icon", {}, [icon("hash", { size: 26 })]),
        el("h2.access__title", {}, ["Aap ko abhi koi WhatsApp number assign nahi hua"]),
        el("p.access__lead", {}, [
          `${me.display_name || "Aap"} — number assign hone tak yahan koi chat nazar nahi aayegi. ` +
            "Neeche likh dein ke aap ko kaunsa number chahiye; admin ko ye foran pahunch jayega.",
        ]),
        note,
        el("div.access__actions", {}, [send]),
        status,
        el("button.btn.btn--ghost.access__recheck", { type: "button", onclick: onAssigned }, [
          icon("refresh", { size: 14 }),
          "Number mil gaya? Dobara check karein",
        ]),
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
  const body = el("div.modal__body", {}, [el("div.thread__hint", {}, ["Load ho raha hai…"])]);
  const dialog = modal("New agent messages", body, { wide: true });

  load();

  async function load() {
    let requests;
    try {
      requests = await access.list();
    } catch (error) {
      clear(body).append(el("div.alert", {}, [`Load nahi hua: ${error.message}`]));
      return;
    }

    if (!requests.length) {
      clear(body).append(el("div.thread__hint", {}, ["Koi request nahi — sab agents ke paas number hai."]));
      return;
    }

    clear(body).append(
      el("p.modal__note", {}, [
        "Ye wo agents hain jinhon ne number maanga hai. Number dene ke liye Numbers screen kholein.",
      ]),
      el("div.reqs", {}, requests.map(row))
    );
  }

  function row(request) {
    const done = el("button.btn.btn--ghost.btn--sm", { type: "button" }, ["Ho gaya"]);
    const card = el("div.req", {}, [
      el("div.req__head", {}, [
        el("div.req__who", {}, [request.agent?.display_name || `Agent #${request.agent?.id ?? "?"}`]),
        el("div.req__when", {}, [stamp(request.created_at)]),
      ]),
      el("div.req__msg", {}, [request.message || ""]),
      el("div.req__actions", {}, [
        el("button.btn.btn--primary.btn--sm", { type: "button", onclick: () => { dialog.close(); onOpenNumbers?.(); } }, [
          "Number assign karein",
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
