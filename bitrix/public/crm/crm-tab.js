/**
 * The WhatsApp tab on a lead, deal, contact or company.
 *
 * It answers one question and then gets out of the way: for each phone number
 * on this record, is there already a WhatsApp chat, and take me to it.
 *
 * Deliberately not a chat. This tab once carried a thread, message bubbles and
 * a composer, which meant an agent could half-work a conversation inside a
 * CRM record — with no template picker, no attachments, no reply-to, and no
 * sight of anything else the customer had said. Everything that actually
 * answers a customer lives in the panel, so the icon opens the panel, on the
 * right chat, and the agent works there.
 *
 * The panel opens *inside Bitrix*, through BX24.openApplication. A new browser
 * tab would leave the portal — and the panel reads where to land from the
 * placement options, which a plain URL cannot carry.
 *
 * Nothing here goes through innerHTML: a contact's name, a lead's title and a
 * phone number are all typed by people outside this company.
 */

import {
  ensureSession,
  ensurePlacement,
  apiFetch,
  callBitrix,
  loadBX24,
} from "../assets/core/bitrix-sso.js";

/** Nodes, never markup. */
function el(spec, props = {}, children = []) {
  const [tag, ...classes] = spec.split(".");
  const node = document.createElement(tag || "div");
  if (classes.length) node.className = classes.join(" ");

  for (const [key, value] of Object.entries(props)) {
    if (value === undefined || value === null || value === false) continue;
    if (key.startsWith("on") && typeof value === "function") {
      node.addEventListener(key.slice(2).toLowerCase(), value);
    } else if (key in node) node[key] = value;
    else node.setAttribute(key, value);
  }

  for (const child of [children].flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

/** WhatsApp's glyph, drawn — the portal's CSP has no room for an icon font. */
function whatsappIcon(size = 18) {
  const SVG = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(SVG, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("width", String(size));
  svg.setAttribute("height", String(size));
  svg.setAttribute("fill", "currentColor");
  svg.setAttribute("aria-hidden", "true");
  const path = document.createElementNS(SVG, "path");
  path.setAttribute(
    "d",
    "M12.04 2C6.58 2 2.13 6.45 2.13 11.91c0 1.75.46 3.45 1.32 4.95L2 22l5.25-1.38a9.9 9.9 0 004.79 1.22h.01c5.46 0 9.9-4.45 9.9-9.91C21.95 6.45 17.5 2 12.04 2zm5.8 14.1c-.24.68-1.42 1.31-1.96 1.36-.5.05-.98.23-3.3-.69-2.78-1.1-4.55-3.93-4.69-4.11-.14-.18-1.12-1.49-1.12-2.84s.71-2.02.96-2.29c.25-.28.55-.35.73-.35.18 0 .37 0 .53.01.17.01.4-.07.62.47.24.57.8 1.97.87 2.11.07.14.12.31.02.49-.09.18-.14.29-.28.45-.14.16-.29.36-.42.48-.14.14-.28.29-.12.57.16.28.72 1.19 1.55 1.93 1.07.95 1.97 1.25 2.25 1.39.28.14.44.12.6-.07.17-.19.69-.8.87-1.08.18-.28.36-.23.61-.14.25.09 1.6.75 1.87.89.28.14.46.21.53.32.07.12.07.66-.17 1.34z"
  );
  svg.append(path);
  return svg;
}

/** The phone values on a Bitrix CRM entity, de-duplicated, in order. */
function extractPhones(phoneField) {
  if (!Array.isArray(phoneField)) return [];
  const out = [];
  for (const item of phoneField) {
    const value = String(item?.VALUE || "").trim();
    if (value && !out.includes(value)) out.push(value);
  }
  return out;
}

const digitsOf = (text) => String(text || "").replace(/\D/g, "");

/**
 * Whoever the customer is, by whichever name the server knows them under — and
 * "" when the only name it has is the number itself.
 *
 * serialize_contact falls back to the wa_id when a contact has no WhatsApp
 * profile name, which is most of them. Printed as-is that makes every row read
 * "971555484423 · 971555484423 · on Farhat Shahid": the number, said twice,
 * with the useful half pushed off the end.
 */
function contactName(conversation, phone) {
  const c = conversation?.contact || {};
  const name = c.display_name || c.profile_name || c.name || "";
  if (!name) return "";
  return digitsOf(name) && digitsOf(name) === digitsOf(phone) ? "" : name;
}

/** "2 days ago", and the units either side of it. */
function ago(iso) {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";

  const seconds = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (seconds < 90) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} minutes ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return hours === 1 ? "an hour ago" : `${hours} hours ago`;
  const days = Math.round(hours / 24);
  if (days < 30) return days === 1 ? "yesterday" : `${days} days ago`;
  const months = Math.round(days / 30);
  return months === 1 ? "a month ago" : `${months} months ago`;
}

/**
 * Which of several chats the icon should open.
 *
 * One number can have more than one chat, because a conversation is per (our
 * number, customer) — the same person messaged from three of our numbers is
 * three threads on purpose. Lead 70045 has exactly that.
 *
 * The agent's own chat wins. Anything else would hand them somebody else's
 * thread with the same person, which is the one outcome that wastes two
 * agents' time instead of one.
 */
function pickConversation(conversations, meId) {
  const mine = conversations.filter((c) => Number(c.assigned_agent?.id) === Number(meId));
  const pool = mine.length ? mine : conversations;
  return [...pool].sort(
    (a, b) => new Date(b.last_message_at || 0) - new Date(a.last_message_at || 0)
  )[0];
}

/* --------------------------------------------------------------- the tab */

class CrmTab {
  constructor(root) {
    this.root = root;
    this.me = null;
    this.bx = null;
    this.entityType = "";
    this.entityId = null;
    this.entityName = "";
    this.rows = []; // {phone, conversations}
  }

  async boot() {
    try {
      this.bx = await loadBX24();
      this.me = await ensureSession();

      if (typeof this.bx.isAdmin === "function" && this.bx.isAdmin()) {
        // Self-healing, the same way index.html does it: an app registered by
        // hand never gets Bitrix's install call, so the tab would stay unbound.
        this.registerPlacements();
      }

      const info = typeof this.bx.placement?.info === "function" ? this.bx.placement.info() : {};
      const options = info?.options || {};
      this.entityId = options.ID || options.ENTITY_ID || null;
      this.entityType = String(info?.placement || "").includes("LEAD")
        ? "LEAD"
        : String(info?.placement || "").includes("DEAL")
          ? "DEAL"
          : String(info?.placement || "").includes("CONTACT")
            ? "CONTACT"
            : String(info?.placement || "").includes("COMPANY")
              ? "COMPANY"
              : "";

      if (!this.entityId || !this.entityType) {
        return this.showNote(
          "This tab has to be opened from a CRM record",
          "Bitrix did not say which record this is. Open it from a lead, deal, contact or company."
        );
      }

      const phones = await this.fetchPhones();
      if (!phones.length) {
        return this.showNote(
          "No phone number on this record",
          this.entityType === "DEAL"
            ? "This deal has no contact or company attached, so there is no number to look up. Attach one and reopen this tab."
            : "Add a phone number to this record and reopen this tab."
        );
      }

      this.rows = [];
      for (const phone of phones) {
        // One at a time. Four numbers is four requests either way, and doing
        // them together only makes the failures harder to attribute.
        this.rows.push({ phone, conversations: await this.lookup(phone) });
      }

      this.render();
    } catch (error) {
      console.error("[a7-wa] CRM tab failed:", error);
      this.showNote(
        "The WhatsApp tab could not load",
        error?.message || "Unknown error",
        // `crm` is what reads the record's numbers; without it every lookup
        // comes back empty and the tab looks broken rather than unauthorised.
        "If this keeps happening, check that the app's scope includes `crm`."
      );
    }
  }

  async registerPlacements() {
    for (const placement of [
      "CRM_LEAD_DETAIL_TAB",
      "CRM_DEAL_DETAIL_TAB",
      "CRM_CONTACT_DETAIL_TAB",
      "CRM_COMPANY_DETAIL_TAB",
    ]) {
      // Handler left to default: it resolves to this page's own directory,
      // which is exactly where these four belong.
      await ensurePlacement({ placement, title: "WhatsApp" }).catch(() => {});
    }
  }

  async fetchPhones() {
    const id = this.entityId;

    if (this.entityType === "LEAD") {
      const lead = await callBitrix("crm.lead.get", { id });
      this.entityName = lead.TITLE || `Lead #${id}`;
      return extractPhones(lead.PHONE);
    }
    if (this.entityType === "CONTACT") {
      const contact = await callBitrix("crm.contact.get", { id });
      this.entityName = `${contact.NAME || ""} ${contact.LAST_NAME || ""}`.trim() || `Contact #${id}`;
      return extractPhones(contact.PHONE);
    }
    if (this.entityType === "COMPANY") {
      const company = await callBitrix("crm.company.get", { id });
      this.entityName = company.TITLE || `Company #${id}`;
      return extractPhones(company.PHONE);
    }

    // A deal has no number of its own; it borrows the one from whoever it is
    // attached to. Both are read, because a deal can carry a company and a
    // contact and the person answering is on the contact.
    const deal = await callBitrix("crm.deal.get", { id });
    this.entityName = deal.TITLE || `Deal #${id}`;

    const phones = [];
    if (deal.CONTACT_ID) {
      const contact = await callBitrix("crm.contact.get", { id: deal.CONTACT_ID }).catch(() => null);
      phones.push(...extractPhones(contact?.PHONE));
    }
    if (deal.COMPANY_ID) {
      const company = await callBitrix("crm.company.get", { id: deal.COMPANY_ID }).catch(() => null);
      for (const p of extractPhones(company?.PHONE)) if (!phones.includes(p)) phones.push(p);
    }
    return phones;
  }

  async lookup(phone) {
    try {
      const data = await apiFetch(`/api/inbox/lookup/?phone=${encodeURIComponent(phone)}`);
      // Shown exactly as the server scoped it. This tab does no filtering of
      // its own: /api/inbox/lookup/ already answers per agent, and a second
      // opinion here could only ever be the wrong one.
      return Array.isArray(data?.conversations) ? data.conversations : [];
    } catch (error) {
      console.warn(`[a7-wa] lookup failed for ${phone}:`, error);
      return [];
    }
  }

  /**
   * Opens the panel inside Bitrix, on the chat this row is about.
   *
   * openApplication, never a URL. The panel reads where to land from the
   * placement options — a link could not carry them, and would take the agent
   * out of the portal on the way.
   */
  open(target) {
    if (typeof this.bx.openApplication !== "function") {
      return this.showNote(
        "This portal cannot open the panel from here",
        "BX24.openApplication is unavailable. Open WhatsApp from the left menu instead."
      );
    }
    this.bx.openApplication(target);
  }

  render() {
    const list = el("div.wa-list");

    for (const { phone, conversations } of this.rows) {
      const chosen = conversations.length ? pickConversation(conversations, this.me?.id) : null;

      const status = chosen
        ? [
            contactName(chosen, phone),
            // The label, never number_id. That id printed as "Channel #16" is
            // a database row number shown to an agent as though it named
            // something.
            chosen.number_label ? `on ${chosen.number_label}` : "",
            ago(chosen.last_message_at),
          ]
            .filter(Boolean)
            .join(" · ") || "Chat open"
        : "No chat yet";

      const button = el("button.wa-row__go", {
        type: "button",
        title: chosen ? "Open this chat in WhatsApp" : "Start a WhatsApp chat with this number",
        // The chat when there is one, the bare number when there is not — the
        // panel opens the template composer for the second, because a customer
        // who has never written cannot be sent anything else.
        onclick: () =>
          this.open(chosen ? { conversation_id: chosen.id } : { phone: digitsOf(phone) }),
      }, [whatsappIcon(18)]);

      list.append(
        el("div.wa-row", {}, [
          el("div.wa-row__main", {}, [
            el("div.wa-row__phone", {}, [phone]),
            el("div.wa-row__status", { class: chosen ? "" : "wa-row__status--none" }, [status]),
          ]),
          // Said only when it changes what the icon does: several chats exist
          // and this opens one of them.
          conversations.length > 1
            ? el("span.wa-row__count", { title: "This number has more than one chat" }, [
                `${conversations.length} chats`,
              ])
            : null,
          button,
        ])
      );
    }

    this.root.replaceChildren(list);
    this.fit();
  }

  showNote(title, ...lines) {
    this.root.replaceChildren(
      el("div.wa-note", {}, [
        el("div.wa-note__title", {}, [title]),
        ...lines.filter(Boolean).map((line) => el("div.wa-note__line", {}, [line])),
      ])
    );
    this.fit();
  }

  /**
   * Asks Bitrix for the height this actually needs.
   *
   * The tab used to reserve room for a thread and a composer, so a lead with
   * two numbers left most of the panel empty. Measured rather than guessed —
   * the number of rows is not known until they are drawn.
   */
  fit() {
    if (typeof this.bx?.resizeWindow !== "function") return;
    const height = Math.min(560, Math.max(140, this.root.scrollHeight + 24));
    this.bx.resizeWindow(window.innerWidth || 800, height);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const root = document.getElementById("root");
  if (root) new CrmTab(root).boot();
});
