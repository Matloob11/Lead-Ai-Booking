import {
  ensureSession,
  ensurePlacement,
  apiFetch,
  callBitrix,
  loadBX24,
  SsoError,
} from "../assets/core/bitrix-sso.js";

/**
 * Safe DOM element creator — guarantees 0% XSS risk by strictly avoiding innerHTML.
 */
function el(tag, attrs = {}, children = []) {
  const element = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "className") {
      element.className = value;
    } else if (key === "textContent") {
      element.textContent = value;
    } else if (key.startsWith("on") && typeof value === "function") {
      element.addEventListener(key.slice(2).toLowerCase(), value);
    } else if (value !== false && value !== null && value !== undefined) {
      element.setAttribute(key, value);
    }
  }
  const childList = Array.isArray(children) ? children : [children];
  for (const child of childList) {
    if (child === null || child === undefined) continue;
    if (typeof child === "string" || typeof child === "number") {
      element.appendChild(document.createTextNode(String(child)));
    } else if (child instanceof Node) {
      element.appendChild(child);
    }
  }
  return element;
}

/**
 * Registers placements in Bitrix if current user is an admin.
 */
async function registerCrmPlacements() {
  const placements = [
    "CRM_LEAD_DETAIL_TAB",
    "CRM_DEAL_DETAIL_TAB",
    "CRM_CONTACT_DETAIL_TAB",
    "CRM_COMPANY_DETAIL_TAB",
  ];
  for (const placement of placements) {
    try {
      const res = await ensurePlacement({ placement, title: "WhatsApp" });
      console.info(`[a7-wa] placement ${placement} status:`, res.status);
    } catch (err) {
      console.warn(`[a7-wa] placement ${placement} bind skipped:`, err);
    }
  }
}

/**
 * Extracts phone values from a Bitrix CRM entity PHONE field array.
 */
function extractPhones(phoneField) {
  if (!Array.isArray(phoneField)) return [];
  const list = [];
  for (const item of phoneField) {
    if (item && item.VALUE) {
      const clean = String(item.VALUE).trim();
      if (clean && !list.includes(clean)) {
        list.push(clean);
      }
    }
  }
  return list;
}

class CrmTabApp {
  constructor(rootEl) {
    this.root = rootEl;
    this.me = null;
    this.entityType = "";
    this.entityId = null;
    this.entityName = "";
    this.phoneNumbers = [];
    this.lookupResults = new Map(); // phone -> lookupData
    this.activeConversation = null;
    this.messages = [];
  }

  async boot() {
    try {
      // 1. Load Bitrix JS SDK
      const BX24 = await loadBX24();

      // Resize window inside Bitrix iframe
      if (typeof BX24.resizeWindow === "function") {
        BX24.resizeWindow(window.innerWidth || 850, 650);
      }

      // 2. Obtain identity / session via SSO
      this.me = await ensureSession();

      // 3. Register placements if admin
      if (typeof BX24.isAdmin === "function" && BX24.isAdmin()) {
        registerCrmPlacements();
      }

      // 4. Retrieve placement information (entity type & ID)
      const placementInfo = typeof BX24.placement.info === "function" ? BX24.placement.info() : {};
      const placementName = placementInfo.placement || "";
      const options = placementInfo.options || {};
      this.entityId = options.ID || null;

      if (!this.entityId) {
        this.renderError("No record ID received from Bitrix placement context.");
        return;
      }

      if (placementName.includes("LEAD")) this.entityType = "LEAD";
      else if (placementName.includes("DEAL")) this.entityType = "DEAL";
      else if (placementName.includes("CONTACT")) this.entityType = "CONTACT";
      else if (placementName.includes("COMPANY")) this.entityType = "COMPANY";
      else this.entityType = "CRM";

      // 5. Fetch entity data and extract phone numbers
      await this.fetchEntityPhones();

      if (!this.phoneNumbers.length) {
        if (this.entityType === "DEAL") {
          this.renderNoPhoneState("No contact or phone number is attached to this deal.");
        } else {
          this.renderNoPhoneState(`No phone number found on this ${this.entityType.toLowerCase()}.`);
        }
        return;
      }

      // 6. Perform chat lookup for each phone number
      await this.performPhoneLookups();

      // 7. Render overview UI
      this.renderOverview();
    } catch (err) {
      console.error("[a7-wa] CRM tab boot failed:", err);
      this.renderError(err.message || "Failed to load CRM Tab");
    }
  }

  async fetchEntityPhones() {
    const id = this.entityId;

    if (this.entityType === "LEAD") {
      const data = await callBitrix("crm.lead.get", { id });
      this.entityName = data.TITLE || `Lead #${id}`;
      this.phoneNumbers = extractPhones(data.PHONE);
    } else if (this.entityType === "CONTACT") {
      const data = await callBitrix("crm.contact.get", { id });
      this.entityName = `${data.NAME || ""} ${data.LAST_NAME || ""}`.trim() || `Contact #${id}`;
      this.phoneNumbers = extractPhones(data.PHONE);
    } else if (this.entityType === "COMPANY") {
      const data = await callBitrix("crm.company.get", { id });
      this.entityName = data.TITLE || `Company #${id}`;
      this.phoneNumbers = extractPhones(data.PHONE);
    } else if (this.entityType === "DEAL") {
      const deal = await callBitrix("crm.deal.get", { id });
      this.entityName = deal.TITLE || `Deal #${id}`;

      if (deal.CONTACT_ID) {
        const contact = await callBitrix("crm.contact.get", { id: deal.CONTACT_ID });
        this.phoneNumbers = extractPhones(contact.PHONE);
      } else if (deal.COMPANY_ID) {
        const company = await callBitrix("crm.company.get", { id: deal.COMPANY_ID });
        this.phoneNumbers = extractPhones(company.PHONE);
      }
    }
  }

  async performPhoneLookups() {
    this.lookupResults.clear();
    for (const phone of this.phoneNumbers) {
      try {
        const data = await apiFetch(`/api/inbox/lookup/?phone=${encodeURIComponent(phone)}`);
        this.lookupResults.set(phone, data);
      } catch (err) {
        console.warn(`[a7-wa] lookup failed for ${phone}:`, err);
        this.lookupResults.set(phone, { phone, conversations: [], numbers: [] });
      }
    }
  }

  renderError(message) {
    this.root.replaceChildren(
      el("div", { className: "alert-card" }, [
        el("strong", { textContent: "Unable to display WhatsApp Tab" }),
        el("div", { textContent: message, style: "margin-top: 4px;" }),
      ])
    );
  }

  renderNoPhoneState(message) {
    this.root.replaceChildren(
      this.renderHeader(),
      el("div", { className: "empty-state" }, [
        el("div", { className: "empty-state__title", textContent: "No Phone Number Available" }),
        el("div", { textContent: message }),
      ])
    );
  }

  renderHeader() {
    return el("header", { className: "crm-header" }, [
      el("div", { className: "crm-header__title" }, [
        el("div", { className: "brand__mark", textContent: "A7" }),
        el("span", { textContent: this.entityName || `${this.entityType} #${this.entityId}` }),
        el("span", { className: "crm-header__badge", textContent: this.entityType }),
      ]),
      el("div", { className: "crm-header__actions" }, [
        el("button", {
          className: "btn btn--secondary btn--sm",
          textContent: "↻ Refresh",
          onClick: () => this.boot(),
        }),
        el("a", {
          className: "btn btn--primary btn--sm",
          href: `${window.location.origin}/app/`,
          target: "_blank",
          textContent: "↗ Open Full Panel",
        }),
      ]),
    ]);
  }

  renderOverview() {
    const sections = [];

    for (const phone of this.phoneNumbers) {
      const lookup = this.lookupResults.get(phone) || { conversations: [] };
      const conversations = lookup.conversations || [];

      const cardList = [];
      if (!conversations.length) {
        cardList.push(
          el("div", { className: "empty-state", style: "padding: 14px;" }, [
            el("div", { textContent: "No previous WhatsApp conversations found for this number." }),
          ])
        );
      } else {
        for (const conv of conversations) {
          const channelName =
            conv.number_display_name ||
            (conv.number ? conv.number.title : `Channel #${conv.number_id}`);

          const isSessionOpen = Boolean(conv.is_session_open);
          const lastMsgText = conv.last_message ? conv.last_message.body : "No messages yet";

          const card = el(
            "div",
            {
              className: "conversation-card",
              onClick: () => this.openConversation(conv),
            },
            [
              el("div", { className: "conversation-card__info" }, [
                el("div", { className: "conversation-card__channel" }, [
                  el("span", { textContent: "💬 " + channelName }),
                ]),
                el("div", { className: "conversation-card__last-msg", textContent: lastMsgText }),
              ]),
              el("div", { className: "conversation-card__meta" }, [
                el("span", {
                  className: `badge ${isSessionOpen ? "badge--open" : "badge--closed"}`,
                  textContent: isSessionOpen ? "Session Open" : "Session Closed",
                }),
                conv.unread_count > 0
                  ? el("span", {
                      className: "badge badge--unread",
                      textContent: String(conv.unread_count),
                    })
                  : null,
                el("button", { className: "btn btn--primary btn--sm", textContent: "Open Chat" }),
              ]),
            ]
          );

          cardList.push(card);
        }
      }

      const section = el("div", { className: "phone-section" }, [
        el("div", { className: "phone-section__header" }, [
          el("div", { className: "phone-number-title" }, [
            el("span", { className: "phone-number-title__icon", textContent: "📞" }),
            el("span", { textContent: phone }),
          ]),
          el("span", {
            className: "text-muted",
            style: "font-size: 12px;",
            textContent: `${conversations.length} chat(s)`,
          }),
        ]),
        el("div", { className: "conversations-grid" }, cardList),
      ]);

      sections.push(section);
    }

    this.root.replaceChildren(this.renderHeader(), ...sections);
  }

  async openConversation(conv) {
    this.activeConversation = conv;
    this.renderThreadLoading();

    try {
      const messagesData = await apiFetch(
        `/api/inbox/conversations/${conv.id}/messages/`
      );
      this.messages = Array.isArray(messagesData) ? messagesData : messagesData.results || [];
      this.renderThreadView();
    } catch (err) {
      console.error("[a7-wa] failed to load thread messages:", err);
      this.renderError("Failed to load chat history for this conversation.");
    }
  }

  renderThreadLoading() {
    this.root.replaceChildren(
      this.renderHeader(),
      el("div", { className: "boot-card" }, [
        el("div", { className: "loading-state" }, [
          el("span", { className: "spinner" }),
          el("span", { textContent: "Loading conversation messages…" }),
        ]),
      ])
    );
  }

  renderThreadView() {
    const conv = this.activeConversation;
    const isSessionOpen = Boolean(conv.is_session_open);
    const channelName =
      conv.number_display_name || (conv.number ? conv.number.title : `Channel #${conv.number_id}`);

    // Thread Header
    const threadHeader = el("div", { className: "thread-header" }, [
      el("div", { style: "display: flex; align-items: center; gap: 10px;" }, [
        el("button", {
          className: "btn btn--secondary btn--sm",
          textContent: "← Back",
          onClick: () => this.renderOverview(),
        }),
        el("div", { className: "thread-header__title", textContent: `${conv.wa_id} (${channelName})` }),
      ]),
      el("div", { style: "display: flex; align-items: center; gap: 8px;" }, [
        el("span", {
          className: `badge ${isSessionOpen ? "badge--open" : "badge--closed"}`,
          textContent: isSessionOpen ? "24h Session Open" : "Session Closed",
        }),
        el("a", {
          className: "btn btn--primary btn--sm",
          href: `${window.location.origin}/app/#/chat/${conv.id}`,
          target: "_blank",
          textContent: "↗ Open in Panel",
        }),
      ]),
    ]);

    // Messages List
    const messageBubbles = [];
    for (const msg of this.messages) {
      const isInbound = msg.direction === "inbound" || msg.direction === "in";
      const timeStr = msg.created_at
        ? new Date(msg.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
        : "";

      const bubble = el(
        "div",
        {
          className: `message-bubble ${isInbound ? "message-bubble--inbound" : "message-bubble--outbound"}`,
        },
        [
          el("div", { textContent: msg.body || (msg.media ? `<${msg.kind}>` : "") }),
          el("div", { className: "message-time", textContent: timeStr }),
        ]
      );

      messageBubbles.push(bubble);
    }

    const messagesContainer = el("div", { className: "thread-messages" }, messageBubbles);

    // Thread Composer
    let composerContainer;
    if (isSessionOpen) {
      const inputEl = el("textarea", {
        className: "thread-composer__input",
        placeholder: "Type a message...",
      });

      // Said next to the box rather than in an alert(): this page is a Bitrix
      // placement iframe, where the browser refuses the modal dialogs outright
      // — prompt() answers null and confirm() answers false without asking
      // anybody, which reads as "the user cancelled".
      const problem = el("div", { className: "thread-composer__error", hidden: true });

      const sendBtn = el("button", {
        className: "btn btn--primary",
        textContent: "Send",
        onClick: async () => {
          const text = inputEl.value.trim();
          if (!text) return;
          sendBtn.disabled = true;
          problem.hidden = true;
          try {
            // /send/, not /messages/. The latter is the GET that lists a
            // thread and refuses every other method, so this button answered
            // 405 for every message anybody tried to send from the CRM.
            const sentMsg = await apiFetch(`/api/inbox/conversations/${conv.id}/send/`, {
              method: "POST",
              body: { body: text },
            });
            inputEl.value = "";
            this.messages.push(sentMsg);
            this.renderThreadView();
          } catch (err) {
            problem.hidden = false;
            problem.textContent = err.message;
          } finally {
            sendBtn.disabled = false;
          }
        },
      });

      composerContainer = el("div", { className: "thread-composer" }, [inputEl, sendBtn, problem]);
    } else {
      composerContainer = el("div", { className: "thread-composer", style: "align-items: center; justify-content: space-between;" }, [
        el("span", {
          className: "text-secondary",
          style: "font-size: 12px;",
          // Not "to reopen". A template does not reopen the window — only a
          // message *from* the customer does that. Saying otherwise is the
          // misunderstanding that hands an agent Meta's error 131049 after the
          // send has already failed, which is why CLAUDE.md spells it out.
          textContent:
            "The 24-hour window has closed, so only a template can be sent. " +
            "The window reopens when the customer writes back.",
        }),
        el("a", {
          className: "btn btn--primary btn--sm",
          href: `${window.location.origin}/app/#/chat/${conv.id}`,
          target: "_blank",
          textContent: "Send Template in Panel",
        }),
      ]);
    }

    const threadView = el("div", { className: "thread-view" }, [
      threadHeader,
      messagesContainer,
      composerContainer,
    ]);

    this.root.replaceChildren(this.renderHeader(), threadView);

    // Auto-scroll messages container to bottom
    setTimeout(() => {
      messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }, 50);
  }
}

// Instantiate and boot on DOM ready
document.addEventListener("DOMContentLoaded", () => {
  const rootEl = document.getElementById("root");
  if (rootEl) {
    const app = new CrmTabApp(rootEl);
    app.boot();
  }
});
