/**
 * The WhatsApp tab on a lead, deal, contact, company, or Owner Data item.
 *
 * For each phone on the record it offers two ways in — both via
 * BX24.openApplication into the side panel (same as Omni always did):
 *   Open with Omni     — WABA inbox on that chat / new template
 *   Open with WhatsApp — Linked devices (OpenWA) on that chat / new contact
 *
 * This tab only picks the door. It does not embed a dashboard here.
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

/** Owner Data SPA — same id as backend crmlink / conversation-health. */
const OWNER_DATA_TYPE_ID = 1042;
const OWNER_DATA_PHONE_FIELDS = [
  "ufCrm5_1768317611513",
  "ufCrm5_1769416533028",
  "ufCrm5_1768317656051",
  "ufCrm5_1768314841508",
];

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

/** Collect digit phones from Owner Data UF number/string fields. */
function extractOwnerPhones(item) {
  const out = [];
  const push = (raw) => {
    const value = String(raw ?? "").trim();
    if (!value || value === "0") return;
    const digits = digitsOf(value);
    if (digits.length < 8) return;
    if (!out.includes(digits) && !out.includes(value)) out.push(digits);
  };
  for (const field of OWNER_DATA_PHONE_FIELDS) push(item?.[field]);
  return out;
}

const digitsOf = (text) => String(text || "").replace(/\D/g, "");

/**
 * Whoever the customer is, by whichever name the server knows them under — and
 * "" when the only name it has is the number itself.
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
 * Which of several chats the Omni icon should open.
 * The agent's own chat wins.
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
    this.entityTypeId = null;
    this.entityId = null;
    this.entityName = "";
    this.rows = []; // {phone, conversations}
  }

  async boot() {
    try {
      this.bx = await loadBX24();
      this.me = await ensureSession();

      if (typeof this.bx.isAdmin === "function" && this.bx.isAdmin()) {
        this.registerPlacements();
      }

      const info = typeof this.bx.placement?.info === "function" ? this.bx.placement.info() : {};
      const options = info?.options || {};
      this.entityId = options.ID || options.ENTITY_ID || null;
      const placement = String(info?.placement || "");
      const dyn = placement.match(/CRM_DYNAMIC_(\d+)_DETAIL_TAB/i);

      if (dyn) {
        this.entityTypeId = Number(dyn[1]);
        this.entityType = `DYNAMIC_${this.entityTypeId}`;
      } else if (placement.includes("LEAD")) {
        this.entityType = "LEAD";
      } else if (placement.includes("DEAL")) {
        this.entityType = "DEAL";
      } else if (placement.includes("CONTACT")) {
        this.entityType = "CONTACT";
      } else if (placement.includes("COMPANY")) {
        this.entityType = "COMPANY";
      } else {
        this.entityType = "";
      }

      if (!this.entityId || !this.entityType) {
        return this.showNote(
          "This tab has to be opened from a CRM record",
          "Bitrix did not say which record this is. Open it from a lead, deal, contact, company or Owner Data."
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
        this.rows.push({ phone, conversations: await this.lookup(phone) });
      }

      this.render();
    } catch (error) {
      console.error("[a7-wa] CRM tab failed:", error);
      this.showNote(
        "The WhatsApp tab could not load",
        error?.message || "Unknown error",
        "If this keeps happening, check that the app's scope includes `crm`."
      );
    }
  }

  async registerPlacements() {
    const handler = new URL(".", window.location.href).href;
    for (const placement of [
      "CRM_LEAD_DETAIL_TAB",
      "CRM_DEAL_DETAIL_TAB",
      "CRM_CONTACT_DETAIL_TAB",
      "CRM_COMPANY_DETAIL_TAB",
      `CRM_DYNAMIC_${OWNER_DATA_TYPE_ID}_DETAIL_TAB`,
    ]) {
      await ensurePlacement({ placement, title: "WhatsApp", handler }).catch(() => {});
    }
  }

  async fetchPhones() {
    const id = this.entityId;

    if (this.entityType.startsWith("DYNAMIC_")) {
      const typeId = this.entityTypeId || Number(this.entityType.replace("DYNAMIC_", ""));
      const res = await callBitrix("crm.item.get", { entityTypeId: typeId, id });
      const item = res?.item || res || {};
      this.entityName = item.title || item.TITLE || `Owner Data #${id}`;
      return extractOwnerPhones(item);
    }

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
      return Array.isArray(data?.conversations) ? data.conversations : [];
    } catch (error) {
      console.warn(`[a7-wa] lookup failed for ${phone}:`, error);
      return [];
    }
  }

  /**
   * Opens the WhatsApp side panel (same BX24.openApplication path Omni uses).
   * Options: conversation_id / phone (Omni) or linked_phone (Linked devices).
   */
  openPanel(target) {
    if (typeof this.bx.openApplication !== "function") {
      return this.showNote(
        "This portal cannot open the panel from here",
        "BX24.openApplication is unavailable. Open WhatsApp from the left menu instead."
      );
    }
    this.bx.openApplication(target);
  }

  /** Let the agent pick which Omni thread when one phone has several chats. */
  chooseOmniChat(phone, conversations) {
    if (!conversations.length) {
      this.openPanel({ phone: digitsOf(phone) });
      return;
    }
    if (conversations.length === 1) {
      this.openPanel({ conversation_id: conversations[0].id });
      return;
    }

    const backdrop = el("div.wa-pick", {
      role: "dialog",
      "aria-label": "Choose Omni chat",
    });
    const close = () => backdrop.remove();
    const list = el("div.wa-pick__list");
    for (const c of conversations) {
      const label = [
        contactName(c, phone) || phone,
        c.number_label ? `on ${c.number_label}` : "",
        c.assigned_agent?.display_name || c.assigned_agent?.username
          ? `@${c.assigned_agent.display_name || c.assigned_agent.username}`
          : "",
        ago(c.last_message_at),
      ]
        .filter(Boolean)
        .join(" · ");
      list.append(
        el(
          "button.wa-pick__item",
          {
            type: "button",
            onclick: () => {
              close();
              this.openPanel({ conversation_id: c.id });
            },
          },
          [label]
        )
      );
    }
    backdrop.append(
      el("div.wa-pick__card", {}, [
        el("div.wa-pick__title", {}, [`${conversations.length} Official API chats for ${phone}`]),
        el("p.wa-pick__help", {}, [
          "Same customer on more than one company WhatsApp number. Pick the Official API thread to open.",
        ]),
        list,
        el("button.wa-pick__cancel", { type: "button", onclick: close }, ["Cancel"]),
      ])
    );
    backdrop.addEventListener("click", (e) => {
      if (e.target === backdrop) close();
    });
    this.root.append(backdrop);
    this.fit();
  }

  render() {
    const list = el("div.wa-list");
    list.append(
      el("p.wa-legend", {}, [
        el("strong", {}, ["Official API"]),
        " = Meta Business (templates, 24h window). ",
        el("strong", {}, ["Linked phone"]),
        " = QR-linked handset chats (OpenWA).",
      ])
    );

    for (const { phone, conversations } of this.rows) {
      const chosen = conversations.length ? pickConversation(conversations, this.me?.id) : null;

      const status = chosen
        ? [
            contactName(chosen, phone),
            chosen.number_label ? `on ${chosen.number_label}` : "",
            ago(chosen.last_message_at),
          ]
            .filter(Boolean)
            .join(" · ") || "Chat open"
        : "No Official API chat yet";

      const omniBtn = el(
        "button.wa-row__btn.wa-row__btn--omni",
        {
          type: "button",
          title: chosen
            ? "Open Official API (Meta Business) chat"
            : "Start Official API chat — template if the 24h window is closed",
          onclick: () => this.chooseOmniChat(phone, conversations),
        },
        [whatsappIcon(16), el("span", {}, ["Official API"])]
      );

      const linkedBtn = el(
        "button.wa-row__btn.wa-row__btn--linked",
        {
          type: "button",
          title: "Open Linked phone (QR / OpenWA) for this number",
          onclick: () => this.openPanel({ linked_phone: digitsOf(phone) }),
        },
        [whatsappIcon(16), el("span", {}, ["Linked phone"])]
      );

      list.append(
        el("div.wa-row", {}, [
          el("div.wa-row__main", {}, [
            el("div.wa-row__phone", {}, [phone]),
            el("div.wa-row__status", { class: chosen ? "" : "wa-row__status--none" }, [status]),
          ]),
          conversations.length > 1
            ? el(
                "button.wa-row__count",
                {
                  type: "button",
                  title: "Choose which Official API chat to open",
                  onclick: () => this.chooseOmniChat(phone, conversations),
                },
                [`${conversations.length} chats — pick`]
              )
            : null,
          el("div.wa-row__actions", {}, [omniBtn, linkedBtn]),
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

  fit() {
    if (typeof this.bx?.resizeWindow !== "function") return;
    const height = Math.min(560, Math.max(160, this.root.scrollHeight + 24));
    this.bx.resizeWindow(window.innerWidth || 800, height);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const root = document.getElementById("root");
  if (root) new CrmTab(root).boot();
});
