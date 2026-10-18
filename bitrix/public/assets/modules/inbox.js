/**
 * The agent inbox: conversation list on the left, thread on the right.
 *
 * Deliberately framework-free — the panel is served as static files from nginx,
 * so staying on plain ES modules keeps "deploy" equal to "copy the folder" with
 * no build step between an edit and the browser.
 *
 * Server rules the UI must mirror (see the API contract):
 *  - an agent sees every chat on their numbers, assigned or not; `assigned_agent`
 *    is ownership for transfers, never a list filter. Transfer shows that one
 *    chat to the receiving agent so they can continue it — it does not grant
 *    the rest of the Official number;
 *  - when `is_session_open` is false the composer is locked and only approved
 *    templates can reopen the 24h window;
 *  - transfer is admin-only.
 */

import { access, auth, catalog, crm, inbox, asList } from "../api/api.js?v=rotate2";
import { openAccessRequests, renderNoNumbersScreen } from "./access-requests.js";
import { bindFileSources, checkFile, openAttachmentDialog } from "./attach.js";
import { ensureSession } from "../core/bitrix-sso.js";
import { imagesInThread, openLightbox } from "../core/lightbox.js";
import { mediaMessageNode } from "../core/message-media.js";
import { buttonReplyTag, templateButtonsRow, templateFooterNode } from "../core/message-bubble-extras.js";
import { specialMessageNode } from "../core/message-special.js";
import { numberNameWithDial } from "../core/number-label.js";
import { createNumberPicker } from "../core/number-picker.js";
import { createQuickFilters, renderTagMenu } from "../core/list-quick-filters.js?v=rotate1";
import { openNumbersAdmin } from "./numbers-admin.js";
import { openLinkedPhonesAdmin } from "./linked-phones-admin.js";
import { openContactPanel, closeContactPanel } from "./contact-panel.js";
import { openTemplateComposer, openTemplateManager } from "./template-composer.js";
import { openSharedLibraryModal } from "./shared-library.js";
import { openLocationModal } from "./location-picker.js";
import { openQuickRepliesModal, bindSlashAutocomplete } from "./quick-replies.js";
import { openStarredMessagesModal } from "./starred-messages.js";
import { openAgentsAdminModal } from "./agents-admin.js";
import { openForwardModal } from "./forward-picker.js";
import { openReportsModal } from "./reports.js";
import { openCampaignModal } from "./campaigns.js";
// Lead AI is its own module (modules/lead-ai/, loaded by index.html) and adds
// its own menu item; the inbox only reaches it through window.a7wa.openLeadAi,
// so a fault there can never stop this inbox from starting.
import { notifyNewMessage, playChime, requestNotificationPermission, isSoundEnabled, setSoundEnabled, isDesktopEnabled, setDesktopEnabled } from "../core/notifications.js";
import { InboxSocket } from "../core/realtime.js";
import { el, clear, dayKey, dayLabel, debounce, formatBytes, minutesUntil, modal, stamp, toast, untilText, initials } from "../core/dom.js";
import { bindEmojiPicker } from "../core/emoji.js";
import { icon, iconForKind } from "../core/icons.js";

const PAGE_SIZE = 40;
const LIST_PAGE_SIZE = 30;

const STATUS_TICK = {
  queued: { name: "clock", label: "queued" },
  sent: { name: "check", label: "sent" },
  delivered: { name: "checkDouble", label: "delivered" },
  read: { name: "checkDouble", label: "read", className: "tick--read" },
  failed: { name: "alert", label: "failed", className: "tick--failed" },
};

/**
 * @param {object} [options.openRequest]  where to land, when something sent
 *   the agent here rather than them opening the panel themselves. The CRM tab
 *   does: an agent clicks the WhatsApp icon beside a lead's number and expects
 *   that conversation, not the list they left three hours ago.
 *
 *   `{ conversationId }`  open this Omni chat
 *   `{ phone }`           no Omni chat yet — start one with this number (template)
 *   `{ linkedPhone }`     open Linked devices on this number (chat or new contact)
 */
export function mountInbox(root, { me, openRequest = null }) {
  const state = {
    me,
    numbers: [],
    numberFilter: "",
    search: "",
    conversations: [],
    activeId: null,
    messages: [],
    unreadAtOpen: 0,
    templates: new Map(), // numberId -> template[]
    // The message the composer is currently answering, or null. Cleared on
    // send and whenever the thread changes — a quote belongs to one chat.
    replyTo: null,
    loadingThread: false,
    connection: "connecting",
    listOffset: 0,
    listExhausted: false,
    /** Label name to keep in the conversation list, or null for all. */
    tagFilter: null,
    /** all | unread | pinned | transferred */
    listFilter: "all",
    messagesExhausted: false,
    loadingOlderMessages: false,
  };

  // Composer listeners (attach button, drop zone, paste) are rebound whenever
  // the composer is re-rendered; this releases the previous set.
  let teardownFileSources = null;
  let teardownEmoji = null;

  /* ------------------------------------------------------------ structure */

  const ui = {
    search: el("input.filter__search", {
      type: "search",
      placeholder: "Search by name or number",
      oninput: debounce((event) => {
        state.search = event.target.value.trim();
        loadConversations();
      }, 200),
    }),
    list: el("ul.convs"),
    listStatus: el("div.convs__status"),
    threadHeader: el("header.thread__header"),
    messages: el("div.thread__messages"),
    composer: el("footer.thread__composer"),
    connection: el("div.connbar", { hidden: true }),
  };

  // Mount points for the companion modules (search, reminders, reply buttons).
  // They own what goes inside; this file only guarantees the slots exist, keep
  // their id, and take no space while empty.
  const slots = {
    search: el("div.slot", { id: "wa-search-slot" }),
    topbar: el("div.slot", { id: "wa-topbar-slot" }),
    composer: el("div.slot", { id: "wa-composer-slot" }),
    theme: el("div.slot", { id: "wa-theme-slot" }),
  };

  /**
   * Everything that is not the app's name lives behind one button.
   *
   * Four controls side by side left no room for the title — it rendered as
   * "W…" — and companion modules append their own into this bar too, so it
   * only gets tighter. A name and a menu is all the bar holds now.
   */
  // Count of agents waiting for a number; the badge is the only nudge an admin
  // gets, so it is filled in as soon as the list is known.
  const requestsBadge = el("span.badge.menu__badge", { hidden: true });

  const menuTagsSlot = el("div.menu__tags-slot", { id: "wa-tag-filter-menu" });

  const menuPanel = el("div.sidebar__menu", { hidden: true }, [
    slots.search,
    el("div.menu__section", {}, ["You"]),
    el("button.btn.menu__item", { onclick: openProfile, type: "button" }, [
      icon("user", { size: 16 }),
      "My Profile",
    ]),
    el("button.btn.menu__item", { onclick: openNewContact, type: "button" }, [
      icon("plus", { size: 16 }),
      "New contact",
    ]),
    el("button.btn.menu__item", {
      onclick: async () => {
        const soundOn = isSoundEnabled();
        setSoundEnabled(!soundOn);
        if (!soundOn) playChime();
        await requestNotificationPermission();
        toast(`Sound ${!soundOn ? "on" : "off"} for new messages`);
      },
      type: "button",
    }, [
      icon("bell", { size: 16 }),
      "Sound & Notifications",
    ]),
    el("div.menu__section", {}, ["Inbox tools"]),
    el("div.menu__section", {}, ["Tags"]),
    menuTagsSlot,
    el("button.btn.menu__item", { onclick: () => openTemplateManager({ isAdmin: me.is_wa_admin }), type: "button" }, [
      icon("file", { size: 16 }),
      "Templates Center",
    ]),
    el("button.btn.menu__item", { onclick: () => openSharedLibraryModal(), type: "button" }, [
      icon("folder", { size: 16 }),
      "Shared Library",
    ]),
    el("button.btn.menu__item", {
      onclick: () => openQuickRepliesModal({ isWaAdmin: me.is_wa_admin }),
      type: "button",
    }, [
      icon("zap", { size: 16 }),
      "Quick Replies",
    ]),
    el("button.btn.menu__item", {
      onclick: () =>
        openStarredMessagesModal({
          conversationId: null,
          onNavigateToMessage: (convId, msgId) => openConversation(convId, { highlightMessageId: msgId }),
        }),
      type: "button",
    }, [
      icon("star", { size: 16 }),
      "Starred Messages",
    ]),
    el("button.btn.menu__item", { onclick: () => openReportsModal(), type: "button" }, [
      icon("zap", { size: 16 }),
      "Reports",
    ]),
    el("button.btn.menu__item", { onclick: () => openCampaignModal(), type: "button" }, [
      icon("send", { size: 16 }),
      "Campaign",
    ]),
    me.is_wa_admin && me.can_linked_devices !== false
      ? el("button.btn.menu__item", { onclick: openLinkedPhones, type: "button" }, [
          icon("users", { size: 16 }),
          "Linked phone agents",
        ])
      : null,
    me.is_wa_admin ? el("div.menu__section", {}, ["Admin"]) : null,
    me.is_wa_admin
      ? el("button.btn.menu__item", { onclick: openNumbers, type: "button" }, [
          icon("hash", { size: 16 }),
          "Numbers",
        ])
      : null,
    me.is_wa_admin
      ? el("button.btn.menu__item", { onclick: () => openAgentsAdminModal({ me }), type: "button" }, [
          icon("userCheck", { size: 16 }),
          "Agents & access",
        ])
      : null,
    me.is_wa_admin
      ? el("button.btn.menu__item", { onclick: openRequests, type: "button" }, [
          icon("users", { size: 16 }),
          "New agent messages",
          requestsBadge,
        ])
      : null,
    el("div.menu__section", {}, ["Design"]),
    slots.theme,
  ]);

  const menuBtn = el("button.btn.btn--icon.sidebar__menu-btn", { type: "button", title: "Menu" }, [
    icon("menu", { size: 19 }),
  ]);

  const newContactFab = el(
    "button.sidebar__fab",
    {
      type: "button",
      title: "New contact",
      "aria-label": "New contact",
      onclick: () => openNewContact(),
    },
    [icon("plus", { size: 18 }), el("span.sidebar__fab-label", {}, ["New"])]
  );

  const quickFilters = createQuickFilters({
    getActive: () => state.listFilter,
      onChange: (id) => {
        state.listFilter = id;
        quickFilters.render();
        loadConversations({ keepActive: false });
      },
  });

  const numberPicker = createNumberPicker({
    getNumbers: () => state.numbers,
    getValue: () => state.numberFilter || "",
    setValue: (id) => {
      state.numberFilter = id;
    },
    onChange: () => loadConversations({ keepActive: false }),
    labelFor: (number) => (number ? numberOptionLabel(number) : "All numbers"),
    matchFilter: numberMatchesFilter,
  });

  const layout = el("div.app", {}, [
    el("aside.sidebar", {}, [
      // Chrome stays out of the scroll pane so filters never paint under chats.
      el("div.sidebar__chrome", {}, [
        // The menu button is a direct child of the bar on purpose: companion
        // modules locate their insertion point with
        // `sidebarTop.querySelector(".btn")` and then insertBefore it, which
        // throws if that button is nested inside a wrapper.
        el("div.sidebar__top", {}, [
          el("div.sidebar__title", {}, ["Official API"]),
          menuBtn,
          menuPanel,
        ]),
        el("div.filter", {}, [numberPicker.root, ui.search, quickFilters.root]),
      ]),
      // List and status share one scroll box so the empty-state message sits
      // right under the (possibly empty) list instead of at the sidebar's foot.
      el("div.convs__wrap", {}, [ui.list, ui.listStatus]),
      // Float over the list — no footer bar; chats stay visible behind.
      newContactFab,
    ]),
    el("section.thread", {}, [ui.connection, ui.threadHeader, ui.messages, ui.composer]),
  ]);

  bindSidebarMenu();
  renderEmptyThread();
  quickFilters.render();

  /**
   * Opens and closes the sidebar menu, and adopts anything a companion module
   * drops into the bar.
   *
   * The companions append their controls to `.sidebar__top` directly — that is
   * the surface they were written against — so rather than ask them to change,
   * the bar hands anything unexpected to the menu. Without it, the crowding
   * this menu exists to fix would come straight back.
   */
  function bindSidebarMenu() {
    const closeMenu = () => {
      menuPanel.hidden = true;
      document.removeEventListener("click", onOutside, true);
    };

    const onOutside = (event) => {
      if (!menuPanel.contains(event.target) && !menuBtn.contains(event.target)) closeMenu();
    };

    menuBtn.addEventListener("click", (event) => {
      event.preventDefault();
      if (!menuPanel.hidden) return closeMenu();
      menuPanel.hidden = false;
      document.addEventListener("click", onOutside, true);
    });

    // Choosing anything in the menu is the end of that interaction.
    menuPanel.addEventListener("click", (event) => {
      if (event.target.closest(".menu__item")) closeMenu();
    });

    const bar = layout.querySelector(".sidebar__top");
    const mine = new Set([bar.firstElementChild, menuBtn, menuPanel]);
    new MutationObserver(() => {
      for (const node of [...bar.children]) {
        if (!mine.has(node)) menuPanel.append(node);
      }
    }).observe(bar, { childList: true });
  }

  /* ------------------------------------------------------------- loading */

  /**
   * Builds the inbox off-screen and only swaps it in once the first fetches
   * succeed — if they don't, the caller's boot screen is still mounted and can
   * show the error instead of an empty panel.
   */
  async function boot() {
    // /api/auth/me/ already carries the visible numbers, so the panel opens on
    // one round trip; the catalog call is only the fallback.
    state.numbers = asList(me.numbers, "numbers");
    if (!state.numbers.length) state.numbers = asList(await catalog.numbers(), "numbers");

    await loadConversations();

    // No Official number, and no chat transferred to them either — ask for a number.
    if (!state.numbers.length && !state.conversations.length) {
      root.className = "";
      renderNoNumbersScreen(root, {
        me,
        onAssigned: () => window.location.reload(),
        onLinkedDevices: openLinkedDevices,
      });
      return;
    }

    renderNumberFilter();
    quickFilters.render();
    root.className = "";
    clear(root).append(layout);
    connectSocket();
    publishApi();
    if (me.is_wa_admin) refreshRequestCount();

    // Pin the panel to this iframe's visible box so the composer cannot be
    // pushed under Bitrix chrome on short sliders / laptop viewports.
    pinFrameHeight(root);

    // Last, because it needs the list and the layout to exist first.
    if (openRequest) await honourOpenRequest(openRequest);
  }

  /**
   * Keep html/body/#root exactly as tall as the frame's visual viewport.
   * Bitrix LEFT_MENU / openApplication iframes vary by screen; without this,
   * percentage heights sometimes resolve against a taller box and the bottom
   * composer is clipped by overflow:hidden on .app.
   */
  function pinFrameHeight(mount) {
    const apply = () => {
      const h = Math.floor(
        window.visualViewport?.height || window.innerHeight || document.documentElement.clientHeight || 0
      );
      if (h < 200) return;
      const px = `${h}px`;
      document.documentElement.style.height = px;
      document.documentElement.style.maxHeight = px;
      document.body.style.height = px;
      document.body.style.maxHeight = px;
      if (mount) {
        mount.style.height = px;
        mount.style.maxHeight = px;
      }
    };

    apply();
    window.addEventListener("resize", apply);
    window.visualViewport?.addEventListener("resize", apply);
    window.visualViewport?.addEventListener("scroll", apply);

    // A one-shot after Bitrix finishes opening the slider — first paint is
    // often shorter than the final frame.
    window.setTimeout(apply, 120);
    window.setTimeout(apply, 600);
  }

  /**
   * Lands the agent where whoever sent them here meant them to land.
   *
   * Deliberately after the panel has drawn rather than instead of it: if the
   * chat cannot be found, or the number turns out not to be reachable, what
   * they get is the ordinary inbox rather than an error page — they came here
   * to talk to somebody and the panel is still the way to do that.
   */
  async function honourOpenRequest({ conversationId, phone, linkedPhone }) {
    if (linkedPhone) {
      const digits = String(linkedPhone).replace(/\D/g, "");
      if (digits) openLinkedDevices(digits);
      return;
    }

    if (conversationId) {
      try {
        await openConversation(Number(conversationId));
        return;
      } catch (error) {
        console.warn("[a7-wa] could not open the requested chat:", error);
      }
    }

    if (!phone) return;

    // No conversation for this number. The window has never been open, so a
    // free-form message is not a thing that can be sent — the only way to
    // reach somebody cold is a template, which is what this opens on.
    const digits = String(phone).replace(/\D/g, "");
    if (digits) openNewContact({ to: digits });
  }

  async function loadConversations({ keepActive = true, append = false } = {}) {
    if (!append) {
      state.listOffset = 0;
      state.listExhausted = false;
      ui.listStatus.textContent = "Loading…";
    } else {
      clear(ui.listStatus).append("Loading more…");
    }
    try {
      const offset = append ? state.listOffset || 0 : 0;
      const payload = await inbox.conversations({
        number: state.numberFilter || undefined,
        q: state.search || undefined,
        limit: LIST_PAGE_SIZE,
        offset,
        rotate: state.listFilter === "rotate",
      });
      const page = asList(payload, "conversations");
      state.conversations = append
        ? mergeConversations(state.conversations, page)
        : page;
      state.listOffset = (append ? offset : 0) + page.length;
      state.listExhausted = page.length < LIST_PAGE_SIZE;
      renderConversations();
      renderListStatus();

      if (keepActive && state.activeId) {
        const still = state.conversations.some((c) => c.id === state.activeId);
        if (!still) renderEmptyThread();
      }
    } catch (error) {
      clear(ui.listStatus).append(`Could not load the list: ${error.message}`);
      console.error("[a7-wa] conversations failed:", error);
    }
  }

  function mergeConversations(existing, incoming) {
    const byId = new Map(existing.map((c) => [String(c.id), c]));
    for (const row of incoming) byId.set(String(row.id), row);
    return [...byId.values()];
  }

  function renderListStatus() {
    clear(ui.listStatus);
    if (!state.conversations.length) {
      ui.listStatus.append(
        state.listFilter === "rotate"
          ? "No rotate campaign chats."
          : "No conversations."
      );
      return;
    }
    if (state.listExhausted) return;
    ui.listStatus.append(
      el(
        "button.btn.btn--ghost.btn--sm.convs__more",
        {
          type: "button",
          onclick: () => loadConversations({ keepActive: true, append: true }),
        },
        ["Load more"]
      )
    );
  }

  function openProfile() {
    const currentMe = state.me || me;
    const initialName = currentMe.display_name || currentMe.username || "Agent";

    const nameInput = el("input.wa-x-field", {
      type: "text",
      value: initialName,
      placeholder: "Your display name",
    });

    const statusEl = el("div.wa-x-alert", { hidden: true });
    const saveBtn = el("button.wa-x-btn.wa-x-btn--primary", { type: "button" }, [
      icon("check", { size: 14 }),
      "Save Profile",
    ]);

    const assignedNumbers = currentMe.numbers || state.numbers || [];

    const formatPhone = (numStr) => {
      if (!numStr) return "";
      const cleaned = String(numStr).replace(/\D/g, "");
      if (cleaned.length === 12 && cleaned.startsWith("971")) {
        return `+971 ${cleaned.slice(3, 5)} ${cleaned.slice(5, 8)} ${cleaned.slice(8)}`;
      }
      return cleaned.startsWith("+") ? cleaned : `+${cleaned}`;
    };

    const numberPills = assignedNumbers.map((n) => {
      const phoneDigits = n.phone_number || (typeof n === "string" ? n : "");
      const phoneFormatted = formatPhone(phoneDigits);
      const titleLabel = n.title && n.title !== phoneDigits ? ` (${n.title})` : "";
      return el("div.na-chip.wa-x-profile-num-chip", { style: "margin: 3px 4px 3px 0;" }, [
        icon("phone", { size: 14 }),
        el("span.na-chip__name", {}, [`${phoneFormatted || n.title || "Unknown"}${titleLabel}`]),
      ]);
    });

    // Calculate WhatsApp System statistics
    const totalConversations = state.conversations?.length || 0;
    const totalUnread = (state.conversations || []).reduce((acc, c) => acc + (c.unread_count || 0), 0);
    const openWindowsCount = (state.conversations || []).filter((c) => c.is_session_open).length;

    const statsGrid = el("div.wa-x-profile-stats-grid", {}, [
      el("div.wa-x-profile-stat-card", {}, [
        el("div.wa-x-stat-icon", {}, [icon("phone", { size: 16 })]),
        el("div.wa-x-stat-val", {}, [String(assignedNumbers.length)]),
        el("div.wa-x-stat-lbl", {}, ["Assigned Numbers"]),
      ]),
      el("div.wa-x-profile-stat-card", {}, [
        el("div.wa-x-stat-icon", {}, [icon("messageSquare", { size: 16 })]),
        el("div.wa-x-stat-val", {}, [String(totalConversations)]),
        el("div.wa-x-stat-lbl", {}, ["Active Chats"]),
      ]),
      el("div.wa-x-profile-stat-card", {}, [
        el("div.wa-x-stat-icon", {}, [icon("bell", { size: 16 })]),
        el("div.wa-x-stat-val", {}, [String(totalUnread)]),
        el("div.wa-x-stat-lbl", {}, ["Unread Messages"]),
      ]),
      el("div.wa-x-profile-stat-card", {}, [
        el("div.wa-x-stat-icon", {}, [icon("clock", { size: 16 })]),
        el("div.wa-x-stat-val", {}, [String(openWindowsCount)]),
        el("div.wa-x-stat-lbl", {}, ["Open 24h Windows"]),
      ]),
    ]);

    const systemFeatures = el("div.wa-x-profile-features", {}, [
      el("div.wa-x-feature-tag", {}, [icon("check", { size: 12 }), "WhatsApp Business API"]),
      el("div.wa-x-feature-tag", {}, [icon("check", { size: 12 }), "Interactive Reply Buttons"]),
      el("div.wa-x-feature-tag", {}, [icon("check", { size: 12 }), "Bitrix CRM Realtime Sync"]),
      el("div.wa-x-feature-tag", {}, [icon("check", { size: 12 }), "Media & Document Messaging"]),
    ]);

    const bodyNode = el("div.wa-x-modal-body.wa-x-profile-modal", {}, [
      el("div.wa-x-profile-header", {}, [
        el("div.conv__avatar.wa-x-profile-avatar", {}, [initials(initialName)]),
        el("div.wa-x-profile-titles", {}, [
          el("div.wa-x-profile-name-row", {}, [
            el("span.wa-x-profile-name", {}, [initialName]),
            el("span.wa-x-online-badge", {}, [icon("check", { size: 12 }), "Online"]),
          ]),
          el("div.wa-x-profile-role", {}, [
            icon("shield", { size: 12 }),
            currentMe.role || (currentMe.is_wa_admin ? "Administrator" : "Agent"),
          ]),
        ]),
      ]),
      el("div.wa-x-profile-section", {}, [
        el("div.wa-x-label-head", {}, ["Assigned WhatsApp Numbers"]),
        el("div.wa-x-profile-numbers-list", {}, [
          numberPills.length ? el("div.na-chips", {}, numberPills) : el("span.na-empty", {}, ["No numbers assigned yet"]),
        ]),
      ]),
      el("div.wa-x-profile-section", { style: "margin-top: 14px;" }, [
        el("div.wa-x-label-head", {}, ["System Statistics"]),
        statsGrid,
      ]),
      el("div.wa-x-profile-section", { style: "margin-top: 14px;" }, [
        el("div.wa-x-label-head", {}, ["System Capabilities"]),
        systemFeatures,
      ]),
      el("div.wa-x-profile-section", { style: "margin-top: 14px;" }, [
        el("div.wa-x-label-head", {}, ["Bitrix Account Info"]),
        el("div.wa-x-field-static", {}, [
          icon("user", { size: 14 }),
          ` Bitrix #${currentMe.bitrix_user_id || currentMe.id} — ${currentMe.bitrix_portal || "Bitrix24 Portal"}`,
        ]),
      ]),
      el("label.wa-x-field-row", { style: "margin-top: 14px;" }, [
        el("div.wa-x-label-head", {}, ["Display Name"]),
        nameInput,
      ]),
      statusEl,
      el("div.wa-x-modal-actions", {}, [saveBtn]),
    ]);

    const profileModal = modal("My Profile", bodyNode);

    saveBtn.addEventListener("click", async () => {
      const newName = nameInput.value.trim();
      if (!newName) {
        statusEl.textContent = "Please enter a valid display name.";
        statusEl.className = "wa-x-alert";
        statusEl.hidden = false;
        return;
      }

      saveBtn.disabled = true;
      saveBtn.textContent = "Saving…";
      statusEl.hidden = true;

      try {
        const updated = await auth.updateProfile({ display_name: newName });
        state.me = updated;
        saveBtn.disabled = false;
        saveBtn.replaceChildren(icon("check", { size: 14 }), "Save Profile");
        statusEl.textContent = "Profile updated successfully!";
        statusEl.className = "wa-x-alert wa-x-alert--ok";
        statusEl.hidden = false;
        setTimeout(() => profileModal.close(), 1200);
      } catch (err) {
        saveBtn.disabled = false;
        saveBtn.replaceChildren(icon("check", { size: 14 }), "Save Profile");
        statusEl.textContent = err.message || "Failed to update profile.";
        statusEl.className = "wa-x-alert";
        statusEl.hidden = false;
      }
    });
  }

  /** The person behind the open chat. Renaming there renames them here too. */
  function openContact(conversation) {
    openContactPanel(conversation.id, {
      onSaved: (contact) => {
        const known = findConversation(conversation.id);
        if (!known) {
          renderConversations();
          return;
        }
        if (known.contact && contact?.name != null) known.contact.name = contact.name;
        if (known.contact && contact?.display_name != null) {
          known.contact.name = contact.display_name || known.contact.name;
        }
        // Pin / archive flags come back on contact.conversation from the panel.
        const flags = contact?.conversation;
        if (flags) {
          if ("is_pinned" in flags) known.is_pinned = !!flags.is_pinned;
          if ("is_archived" in flags) known.is_archived = !!flags.is_archived;
        }
        renderConversations();
        renderThreadHeader(known);
      },
      onOpenConversation: (id) => openConversation(id),
    });
  }

  async function openConversation(id, { highlightMessageId } = {}) {
    if (state.loadingThread) return;

    // A link to a chat that is not in this list (search, reminder, CRM tab,
    // campaign history) may point at a Lead AI chat, which opens in the Lead AI
    // screen instead. Ask first, so the chat open here, and a reply half
    // written in it, are left as they are.
    let prefetched = null;
    if (!findConversation(id)) {
      state.loadingThread = true;
      try {
        prefetched = await inbox.messages(id, { limit: PAGE_SIZE });
      } catch {
        prefetched = null;
      } finally {
        state.loadingThread = false;
      }
      if (prefetched?.conversation?.lead_ai) {
        sendToLeadAi(id, highlightMessageId);
        return;
      }
    }

    // The profile describes one customer; carrying it into another chat would
    // show the wrong person beside the right messages.
    if (state.activeId !== id) closeContactPanel();
    // A half-written reply belongs to the chat it was started in.
    if (state.activeId !== id) state.replyTo = null;
    state.activeId = id;
    state.loadingThread = true;
    state.messagesExhausted = false;
    state.loadingOlderMessages = false;
    renderConversations({ scrollActive: true });
    clear(ui.messages).append(el("div.thread__hint", {}, ["Loading…"]));

    try {
      renderThreadHeader(findConversation(id));
      const payload = prefetched || (await inbox.messages(id, { limit: PAGE_SIZE }));

      // A listed chat that a Lead AI campaign moved a moment ago opens there.
      if (payload?.conversation?.lead_ai) {
        dropLeadAiChat(id, { quiet: true });
        sendToLeadAi(id, highlightMessageId);
        return;
      }

      // The endpoint already hands back the newest slice in oldest-first order,
      // which is exactly the reading order — do not re-sort it.
      state.messages = asList(payload, "messages");
      state.messagesExhausted = state.messages.length < PAGE_SIZE;

      // A search hit can point at a message far above the newest page.
      if (highlightMessageId) await loadUntilMessage(id, highlightMessageId);

      // It also returns the conversation, fresher than the list copy.
      const conversation = payload?.conversation || findConversation(id);
      if (payload?.conversation) upsertConversation(payload.conversation);

      // Captured before mark-read so the "new messages" divider survives.
      state.unreadAtOpen = conversation?.unread_count || 0;

      renderThreadHeader(conversation);
      renderMessages({ scroll: "bottom" });
      renderComposer(conversation);

      if (highlightMessageId) highlightMessage(highlightMessageId);

      markRead(conversation);
    } catch (error) {
      clear(ui.messages).append(el("div.thread__hint.thread__hint--error", {}, [`Could not load the thread: ${error.message}`]));
      console.error("[a7-wa] messages failed:", error);
    } finally {
      state.loadingThread = false;
    }
  }

  /**
   * Refetches the open thread and redraws it, without reopening the chat.
   *
   * What star, retry and send-location all want after the server has changed
   * something: the bubbles again, not a fresh conversation. Going through
   * openConversation would re-run mark-read, reset the unread divider and, when
   * a thread is already loading, return without doing anything at all — three
   * call sites were asking for this function and none of them existed.
   */
  async function loadMessages(id) {
    if (!id) return;
    try {
      const payload = await inbox.messages(id, { limit: PAGE_SIZE });
      state.messages = asList(payload, "messages");
      state.messagesExhausted = state.messages.length < PAGE_SIZE;
      if (payload?.conversation) upsertConversation(payload.conversation);
      renderMessages({ scroll: "bottom" });
    } catch (error) {
      console.error("[a7-wa] could not refresh the thread:", error);
    }
  }

  const findConversation = (id) => state.conversations.find((c) => c.id === id) || null;

  /**
   * Clears the unread badge for a chat, but only if this tab is actually on
   * screen.
   *
   * The panel is commonly left open in a second tab. Without the visibility
   * check that tab still holds an `activeId`, so every arriving message looked
   * "read" to it: it cleared the badge the agent was meant to see in the tab
   * they were really using, and sent the customer a blue tick for a message
   * nobody had looked at. A hidden tab reads nothing.
   */
  function markRead(conversation) {
    if (!conversation?.unread_count) return;
    if (document.visibilityState !== "visible") return;

    inbox.markRead(conversation.id).then(() => {
      conversation.unread_count = 0;
      renderConversations();
    }, () => {});
  }

  // Coming back to the tab is the moment the open chat is genuinely read.
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState !== "visible" || !state.activeId) return;
    markRead(findConversation(state.activeId));
  });

  /** How far back a deep link may pull before giving up. */
  const HIGHLIGHT_MAX_PAGES = 5;

  /**
   * Pages backwards until the wanted message is loaded, so a deep link into an
   * old message lands on it instead of on an empty scroll position. Bounded:
   * a wrong id must not walk the whole history.
   */
  async function loadUntilMessage(conversationId, messageId) {
    const wanted = String(messageId);
    for (let page = 0; page < HIGHLIGHT_MAX_PAGES; page++) {
      if (state.messages.some((m) => String(m.id) === wanted)) return true;

      const oldest = state.messages[0]?.id;
      if (!oldest) return false;

      const older = asList(await inbox.messages(conversationId, { before: oldest, limit: PAGE_SIZE }), "messages");
      if (!older.length) return false;
      state.messages = [...older, ...state.messages];
      state.messagesExhausted = older.length < PAGE_SIZE;
      renderMessages({ scroll: "preserve" });
    }
    return false;
  }

  /** Pull the next page of history when the agent scrolls to the top. */
  async function loadOlderMessages() {
    if (!state.activeId || state.loadingOlderMessages || state.messagesExhausted) return;
    const oldest = state.messages[0]?.id;
    if (!oldest) return;
    state.loadingOlderMessages = true;
    try {
      const older = asList(
        await inbox.messages(state.activeId, { before: oldest, limit: PAGE_SIZE }),
        "messages"
      );
      if (!older.length) {
        state.messagesExhausted = true;
        return;
      }
      state.messages = [...older, ...state.messages];
      if (older.length < PAGE_SIZE) state.messagesExhausted = true;
      renderMessages({ scroll: "preserve" });
    } catch (error) {
      console.error("[a7-wa] could not load older messages:", error);
    } finally {
      state.loadingOlderMessages = false;
    }
  }

  /** Scrolls a message into view and flashes it, the way a search result should. */
  function highlightMessage(messageId) {
    const node = ui.messages.querySelector(`[data-id="${CSS.escape(String(messageId))}"]`);
    if (!node) return;
    node.scrollIntoView({ block: "center" });
    node.classList.add("msg--highlight");
    setTimeout(() => node.classList.remove("msg--highlight"), 2000);
  }

  /* ------------------------------------------------------------ rendering */

  function formatPhoneDigits(numStr) {
    if (!numStr) return "";
    const cleaned = String(numStr).replace(/\D/g, "");
    if (cleaned.length === 12 && cleaned.startsWith("971")) {
      return `+971 ${cleaned.slice(3, 5)} ${cleaned.slice(5, 8)} ${cleaned.slice(8)}`;
    }
    return cleaned.startsWith("+") ? cleaned : `+${cleaned}`;
  }

  function numberOptionLabel(number) {
    const rawPhone = number?.phone_number || number?.id || "";
    const phone = formatPhoneDigits(rawPhone) || rawPhone || "Number";

    const agents = Array.isArray(number?.agents) ? number.agents : [];
    const names = agents.map((a) => {
      const name = a.display_name;
      if (!name) return "";
      const community = String(a.community || "").trim();
      return community ? `${name} · ${community}` : name;
    }).filter(Boolean);

    const customLabel = (number?.label || (number?.title !== number?.phone_number ? number?.title : "") || "").trim();
    const isDistinctLabel = customLabel && customLabel !== rawPhone && customLabel !== phone;
    const community = String(number?.community || "").trim();
    const withCommunity = (text) =>
      community && !String(text).includes(community) ? `${text} · ${community}` : text;

    if (names.length) {
      const assignedText = names.join(", ");
      if (isDistinctLabel && !names.includes(customLabel)) {
        return withCommunity(`${phone} (${customLabel}) → ${assignedText}`);
      }
      return withCommunity(`${phone} → ${assignedText}`);
    }

    if (isDistinctLabel) {
      return withCommunity(`${phone} → ${customLabel}`);
    }

    return withCommunity(community ? `${phone} → ${community}` : `${phone} → Not assigned`);
  }

  function numberMatchesFilter(number, query) {
    const q = String(query || "").trim().toLowerCase();
    if (!q) return true;
    const phone = String(number?.phone_number || "");
    const label = numberOptionLabel(number).toLowerCase();
    const digits = q.replace(/\D/g, "");
    if (label.includes(q)) return true;
    if (phone.toLowerCase().includes(q)) return true;
    if (digits && phone.replace(/\D/g, "").includes(digits)) return true;
    const title = String(number?.title || number?.label || "").toLowerCase();
    if (title.includes(q)) return true;
    const account = String(number?.account_username || "").toLowerCase();
    if (account && account.includes(q)) return true;
    const waba = String(number?.waba_business_id || "");
    if (waba && (waba.toLowerCase().includes(q) || (digits && waba.includes(digits)))) return true;
    const agents = Array.isArray(number?.agents) ? number.agents : [];
    for (const agent of agents) {
      const name = String(agent?.display_name || "").toLowerCase();
      if (name && name.includes(q)) return true;
    }
    return false;
  }

  function renderNumberFilter() {
    numberPicker.setVisible(state.numbers.length >= 2);
    numberPicker.refresh();
  }

  /**
   * `title` is the server's own answer to "what should this number be called"
   * (admin label → gateway name → digits). Everything the agent sees goes
   * through it, so a rename shows up in one place.
   */
  const numberTitle = (number) => numberNameWithDial(number);

  function collectTagNames() {
    const names = new Map();
    for (const c of state.conversations) {
      for (const l of c.labels || []) {
        if (l?.name) names.set(l.name, l.colour || "#25D366");
      }
    }
    return names;
  }

  function renderTagFilterMenu() {
    renderTagMenu({
      container: menuTagsSlot,
      getTags: collectTagNames,
      getActive: () => state.tagFilter,
      onChange: (name) => {
        state.tagFilter = name;
        renderTagFilterMenu();
        renderConversations();
      },
    });
  }

  function applyListFilter(conversations) {
    let rows = conversations.slice();
    if (state.listFilter === "rotate") {
      rows = rows.filter((c) => c.staff_only);
    } else if (state.listFilter === "unread") {
      rows = rows.filter((c) => !c.staff_only && Number(c.unread_count || 0) > 0);
    } else if (state.listFilter === "pinned") {
      rows = rows.filter((c) => !c.staff_only && c.is_pinned);
    } else if (state.listFilter === "transferred") {
      rows = rows.filter((c) => !c.staff_only && isTransferredIn(c));
    } else {
      rows = rows.filter((c) => !c.staff_only);
    }
    if (state.tagFilter) {
      rows = rows.filter((c) => (c.labels || []).some((l) => l.name === state.tagFilter));
    }
    return rows;
  }

  function renderConversations({ scrollActive = false } = {}) {
    clear(ui.list);
    renderTagFilterMenu();
    const conversationsToDraw = applyListFilter(state.conversations).sort((a, b) => {
      const pa = a.is_pinned ? 1 : 0;
      const pb = b.is_pinned ? 1 : 0;
      if (pa !== pb) return pb - pa;
      const ta = Date.parse(a.last_message_at || "") || 0;
      const tb = Date.parse(b.last_message_at || "") || 0;
      return tb - ta;
    });

    for (const conversation of conversationsToDraw) {
      const open = conversation.is_session_open;
      // "Transferred" already shows on the meta line — keep chips for real tags only.
      const chipLabels = (conversation.labels || []).filter(
        (l) => String(l.name || "").trim().toLowerCase() !== "transferred"
      );
      const labelsNode = chipLabels.length
        ? el(
            "div.conv__labels",
            {},
            chipLabels.map((l) =>
              el("span.conv__label-chip", { style: `background:${l.colour};color:#fff` }, [l.name])
            )
          )
        : null;

      ui.list.append(
        el(
          "li.conv",
          {
            class: [
              conversation.id === state.activeId ? "conv--active" : "",
              isClosingSoon(conversation) ? "conv--closing" : "",
              isTransferredIn(conversation) ? "conv--transferred" : "",
            ]
              .filter(Boolean)
              .join(" "),
            onclick: () => openConversation(conversation.id),
          },
          [
            el("div.conv__avatar", {}, [initials(conversation.contact?.name || conversation.contact?.wa_id)]),
            el("div.conv__body", {}, [
              el("div.conv__line", {}, [
                el("span.conv__name", {}, [conversation.contact?.name || conversation.contact?.wa_id || "—"]),
                el("span.conv__time", {}, [stamp(conversation.last_message_at)]),
              ]),
              el("div.conv__line", {}, [
                el("span.conv__preview", {}, [
                  kindIcon(conversation.last_message_kind),
                  el("span.conv__preview-text", {}, [conversation.last_message_preview || ""]),
                ]),
                conversation.unread_count
                  ? el("span.badge", {}, [String(conversation.unread_count)])
                  : null,
              ]),
              labelsNode,
              el("div.conv__meta", {}, [
                el("span.dot", {
                  class: !open ? "dot--closed" : isClosingSoon(conversation) ? "dot--closing" : "dot--open",
                  title: !open
                    ? "Window closed"
                    : isClosingSoon(conversation)
                      ? `Window closing — ${untilText(conversation.session_expires_at) || "1 hour"} left`
                      : "Window open",
                }),
                el(
                  "span.conv__number",
                  {},
                  [
                    isTransferredIn(conversation) ? "Transferred · " : "",
                    numberTitle(numberById(conversation.number_id) || conversation.number),
                  ]
                ),
                leadbotChip(conversation),
              ]),
            ]),
          ]
        )
      );
    }

    if (scrollActive && state.activeId) {
      requestAnimationFrame(() => {
        ui.list.querySelector(".conv--active")?.scrollIntoView({ block: "nearest" });
      });
    }
  }

  const numberById = (id) => state.numbers.find((n) => String(n.id) === String(id));

  function leadbotChip(conversation) {
    const badge = conversation?.leadbot;
    if (!badge || !badge.label) return null;
    const kind = badge.kind || "pending";
    return el("span.conv__ai", { class: "conv__ai--" + kind, title: badge.label }, [badge.label]);
  }

  function isTransferredIn(conversation) {
    if (conversation?.is_transferred) return true;
    if ((conversation?.labels || []).some((l) => String(l.name) === "Transferred")) return true;
    const mine =
      String(conversation?.assigned_agent?.id || conversation?.assigned_agent) === String(state.me?.id);
    if (!mine) return false;
    return !state.numbers.some((n) => String(n.id) === String(conversation.number_id));
  }

  /** Marks a media preview in the list; plain text and templates get no icon. */
  const kindIcon = (kind) => iconForKind(kind, { size: 13, className: "conv__kind" });

  /**
   * The slot anchors must be in the document from mount, not only while a chat
   * is open: the companion modules look them up once on wa:ready. Every render
   * path that clears the header or composer puts them back.
   */
  function renderEmptyThread() {
    clear(ui.threadHeader).append(slots.topbar);
    clear(ui.composer).append(slots.composer);
    clear(ui.messages).append(el("div.thread__hint", {}, ["Select a chat from the left."]));
  }

  /**
   * The way back to the CRM record this customer belongs to.
   *
   * Put beside the window chip because that is where somebody stands when they
   * want to know whether any of this reached the lead — and until now the only
   * way to find out was to leave the panel, open the CRM, and search for the
   * number by hand.
   *
   * Asked of our own backend rather than of Bitrix directly. The answer takes
   * several REST calls now — the duplicate search for leads, another for
   * contacts, a read of each candidate to reject the record carrying thirteen
   * thousand phone numbers, and two filtered queries against Owner Data — and
   * the server already has to get all of that right for the timeline mirror.
   * Repeating it in the browser would be a second copy to keep in step.
   *
   * At click time rather than on every repaint: it is a handful of calls per
   * chat, and drawing the conversation list would have made hundreds of them.
   */
  /**
   * A wa_id as a person writes it. `971552666614` is a string to a computer and
   * a phone number to everybody else.
   *
   * This existed only as a name: two places called `withPlus` and nothing ever
   * defined it. The older of them sits in the "this number is on several
   * records" modal, which needs two or more hits to open and so had never run —
   * a ReferenceError waiting for the first customer who was in the CRM twice.
   */
  function withPlus(waId) {
    const digits = String(waId || "").replace(/\D/g, "");
    if (!digits) return "";
    if (digits.length === 12 && digits.startsWith("971")) {
      return `+971 ${digits.slice(3, 5)} ${digits.slice(5, 8)} ${digits.slice(8)}`;
    }
    return `+${digits}`;
  }

  /**
   * The number is in neither Leads nor Owner Data, so offer to put it in one.
   *
   * Two places, asked rather than guessed: a buyer enquiring belongs in Leads,
   * and somebody an agent is dealing with about a property they own belongs in
   * Owner Data. Only the agent on the conversation knows which, and picking one
   * silently would scatter owners through the lead pipeline.
   *
   * Whichever is chosen, the whole conversation is copied into the new record's
   * timeline in the order it happened — the point of making the record here
   * rather than by hand in another tab is that the history comes with it.
   */
  function offerToCreate(conversation, waId, button, restore) {
    // The destination is passed to `run()` at click time, not carried on the
    // button, so this only needs the label.
    const pick = (label) =>
      el("button.btn.btn--ghost.crm-hits__row", { type: "button" }, [
        el("span.crm-hits__kind", {}, [label]),
      ]);

    const asLead = pick("Create a Lead");
    const asOwner = pick("Create in Owner Data");
    const note = el("p.modal__note", {}, [
      `${withPlus(waId)} is not in the CRM. Creating a record here also copies this ` +
        `conversation into its timeline, oldest message first.`,
    ]);

    const dialog = modal(
      "Not in the CRM yet",
      el("div.modal__body", {}, [note, el("div.crm-hits", {}, [asLead, asOwner])])
    );

    const run = async (where, source) => {
      asLead.disabled = asOwner.disabled = true;
      clear(note).append("Creating the record and copying the conversation…");
      try {
        const made = await crm.createRecord(conversation.id, where);
        clear(note).append(
          `${made.label} #${made.id} created. ${made.messages_copied} message` +
            `${made.messages_copied === 1 ? "" : "s"} copied` +
            `${made.messages_failed ? `, ${made.messages_failed} could not be` : ""}.`
        );
        // Straight to it. The agent asked for a record; showing them the record
        // is the answer, not a dialog reporting that one exists.
        window.BX24?.openPath?.(made.path);
        dialog?.close?.();
        clear(button).append(icon("user", { size: 15 }), " CRM");
      } catch (error) {
        // Left on screen. A failed create that clears itself leaves the agent
        // believing the lead is there.
        clear(note).append(error?.message || "Bitrix refused to create the record.");
        asLead.disabled = asOwner.disabled = false;
        void source;
      }
    };

    asLead.addEventListener("click", () => run("lead", asLead));
    asOwner.addEventListener("click", () => run("owner_data", asOwner));

    clear(button).append(icon("user", { size: 15 }), " Create in CRM");
    restore();
  }

  function openLeadButton(conversation) {
    const waId = conversation.contact?.wa_id || "";
    if (!waId) return null;

    const button = el("button.btn.btn--ghost.btn--sm", {
      type: "button",
      title: "Open this customer's record in the CRM — lead, contact or Owner Data",
    }, [icon("user", { size: 15 }), " CRM"]);

    const restore = () =>
      setTimeout(() => clear(button).append(icon("user", { size: 15 }), " CRM"), 2600);

    button.addEventListener("click", async () => {
      button.disabled = true;
      try {
        const records = asList(await crm.whereis(waId), "records");

        if (!records.length) {
          // Not in the CRM is not news, it is a job. The button used to say so
          // and change back a moment later, which left the agent to go and make
          // the lead by hand in another tab and paste the number in.
          offerToCreate(conversation, waId, button, restore);
          return;
        }

        // One record: straight there. Several — a lead and the Owner Data
        // entries for the same person's properties — is a real answer rather
        // than an ambiguity to resolve by guessing, so it gets a list.
        if (records.length === 1) {
          window.BX24?.openPath?.(records[0].path);
          return;
        }

        modal(
          "Where this number appears",
          el("div.modal__body", {}, [
            el("p.modal__note", {}, [
              `${withPlus(waId)} is on ${records.length} records. WhatsApp messages are added to all of them.`,
            ]),
            el(
              "div.crm-hits",
              {},
              records.map((record) =>
                el("button.btn.btn--ghost.crm-hits__row", {
                  type: "button",
                  onclick: () => window.BX24?.openPath?.(record.path),
                }, [
                  el("span.crm-hits__kind", {}, [record.label]),
                  el("span.crm-hits__id", {}, [`#${record.id}`]),
                ])
              )
            ),
          ])
        );
      } catch (error) {
        console.warn("[a7-wa] CRM lookup failed:", error);
        clear(button).append(icon("alert", { size: 15 }), " CRM search failed");
        restore();
      } finally {
        button.disabled = false;
      }
    });

    return button;
  }

  /* The browser-side duplicate search that used to live here has gone to the
     server — /api/crm/whereis/. It searched leads, contacts and companies and
     took the first hit, which since then has turned out to be three wrong
     answers: it missed Owner Data entirely, where an agent often works the
     owner side of a property and never opens a lead; it accepted the contact
     carrying 13,501 phone numbers, because Bitrix returns that one for every
     number on it; and it stopped at the first match when a person genuinely
     has several records. The server has to get all of that right for the
     timeline mirror, so asking it is one answer rather than two to keep in
     step. */

  function renderThreadHeader(conversation) {
    clear(ui.threadHeader);
    if (!conversation) {
      ui.threadHeader.append(slots.topbar);
      return;
    }

    const open = conversation.is_session_open;
    const left = untilText(conversation.session_expires_at);

    ui.threadHeader.append(
      el("div.thread__who", { onclick: () => openContact(conversation), title: "Contact details" }, [
        el("div.conv__avatar", {}, [initials(conversation.contact?.name || conversation.contact?.wa_id)]),
        el("div", {}, [
          el("div.thread__name", {}, [conversation.contact?.name || conversation.contact?.wa_id || "—"]),
          el("div.thread__sub", {}, [
            conversation.contact?.wa_id || "",
            " · ",
            numberTitle(numberById(conversation.number_id) || conversation.number),
          ]),
        ]),
      ]),
      el("div.thread__tools", {}, [
        el("span.pill", { class: sessionPillClass(conversation) }, [
          open ? (left ? `Window open · ${left}` : "Window open") : "Window closed",
        ]),
        conversation.assigned_agent
          ? el("span.pill", {}, [
              `@${conversation.assigned_agent.display_name || conversation.assigned_agent}${
                conversation.assigned_agent.community ? ` · ${conversation.assigned_agent.community}` : ""
              }`,
            ])
          : null,
        conversation.is_transferred
          ? el("span.pill", { title: "Panel copy on both Official numbers. New WhatsApp messages use each agent's own number." }, [
              "Transferred",
            ])
          : null,
        leadbotChip(conversation),
        openLeadButton(conversation),
        el("button.btn.btn--ghost.btn--sm", {
          type: "button",
          title: "Export chat record",
          onclick: () => {
            const expDialog = modal(
              "Export Chat Record",
              el("div.modal__body", {}, [
                el("p.modal__note", {}, ["Download complete chat history as Text (.txt) or Spreadsheet (.csv):"]),
                el("div.modal__actions", { style: "gap: 12px; justify-content: center; margin-top: 16px;" }, [
                  el("button.btn.btn--primary", {
                    type: "button",
                    onclick: () => {
                      expDialog.close();
                      window.open(inbox.exportUrl(conversation.id, "txt"), "_blank");
                    },
                  }, [icon("fileText", { size: 15 }), " Download TXT"]),
                  el("button.btn.btn--primary", {
                    type: "button",
                    onclick: () => {
                      expDialog.close();
                      window.open(inbox.exportUrl(conversation.id, "csv"), "_blank");
                    },
                  }, [icon("file", { size: 15 }), " Download CSV"]),
                ]),
              ])
            );
          },
        }, [
          icon("download", { size: 15 }),
          "Export",
        ]),
        state.me.is_wa_admin
          ? el("button.btn.btn--ghost.btn--sm", { type: "button", onclick: () => openTransfer(conversation) }, [
              icon("users", { size: 15 }),
              "Transfer",
            ])
          : el(
              "button.btn.btn--ghost.btn--sm",
              {
                type: "button",
                title: "Only panel admins can transfer chats",
                onclick: () =>
                  toast("Ask a panel admin to transfer this chat — agents cannot reassign ownership.", "err"),
              },
              [icon("users", { size: 15 }), "Ask admin"]
            ),
      ])
    );
  }

  /** Within this many pixels of the end counts as "watching the live edge". */
  const STICK_THRESHOLD = 80;

  const isAtBottom = () =>
    ui.messages.scrollHeight - ui.messages.scrollTop - ui.messages.clientHeight <= STICK_THRESHOLD;

  const scrollToBottom = () => {
    ui.messages.scrollTop = ui.messages.scrollHeight;
  };

  // Images and videos have no height until they load, so the scroll that runs
  // right after render lands short and the newest bubble hides behind the
  // composer. Re-pin whenever a media element settles, unless the agent has
  // meanwhile scrolled up to read something.
  let followTail = true;
  ui.messages.addEventListener("scroll", () => {
    followTail = isAtBottom();
  });
  ui.messages.addEventListener(
    "load",
    () => {
      if (followTail) scrollToBottom();
    },
    true // capture: load does not bubble
  );

  /**
   * Follows new messages only when the agent is already at the bottom. Yanking
   * the view down while they are reading older history is worse than missing a
   * bubble they can scroll to.
   */
  function appendMessageNode(node, { wasAtBottom = isAtBottom() } = {}) {
    ui.messages.append(node);
    if (wasAtBottom) scrollToBottom();
  }

  /** The server warns at this mark; the panel derives the same state itself. */
  const CLOSING_SOON_MINUTES = 60;

  /**
   * Whether this chat's free window is about to lapse.
   *
   * Derived from session_expires_at rather than remembered from the
   * session.closing event: the task behind that event runs every 15 minutes and
   * re-sends for the same chat, and a computed answer is inherently
   * de-duplicated — it is also right for chats loaded after the event fired.
   */
  function isClosingSoon(conversation) {
    if (!conversation?.is_session_open) return false;
    const left = minutesUntil(conversation.session_expires_at);
    return left !== null && left >= 0 && left <= CLOSING_SOON_MINUTES;
  }

  /**
   * The window closing is the deadline that costs money — once it lapses only
   * a paid template reopens the chat — so the pill warns before it happens
   * rather than only reporting that it already did.
   */
  function sessionPillClass(conversation) {
    if (!conversation.is_session_open) return "pill--closed";
    const left = minutesUntil(conversation.session_expires_at);
    if (left !== null && left <= 30) return "pill--urgent";
    if (left !== null && left <= 120) return "pill--soon";
    return "pill--open";
  }

  function renderMessages({ scroll = "bottom" } = {}) {
    const prevScrollTop = ui.messages.scrollTop;
    const prevHeight = ui.messages.scrollHeight;
    clear(ui.messages);

    const unreadFrom = firstUnreadIndex();
    let lastDay = null;

    if (state.loadingOlderMessages) {
      ui.messages.append(el("div.thread__hint", {}, ["Loading older messages…"]));
    } else if (!state.messagesExhausted && state.messages.length >= PAGE_SIZE) {
      ui.messages.append(
        el(
          "button.btn.btn--ghost.btn--sm.thread__older",
          { type: "button", onclick: () => void loadOlderMessages() },
          ["Load older messages"]
        )
      );
    }

    state.messages.forEach((message, index) => {
      const day = dayKey(message.created_at);
      if (day && day !== lastDay) {
        ui.messages.append(el("div.daysep", {}, [el("span", {}, [dayLabel(message.created_at)])]));
        lastDay = day;
      }
      if (index === unreadFrom) {
        ui.messages.append(el("div.unreadsep", {}, [el("span", {}, ["New messages"])]));
      }
      ui.messages.append(messageBubble(message));
    });

    if (scroll === "preserve") {
      followTail = false;
      ui.messages.scrollTop = ui.messages.scrollHeight - prevHeight + prevScrollTop;
    } else {
      followTail = true;
      scrollToBottom();
    }
  }

  /**
   * Index of the first message in the unread run, or -1.
   *
   * The count is taken when the thread is opened, before it is marked read —
   * otherwise the divider would vanish the instant the agent looked at it. It
   * counts inbound messages from the end, which is what the server counts too.
   */
  function firstUnreadIndex() {
    const unread = state.unreadAtOpen;
    if (!unread) return -1;

    let seen = 0;
    for (let i = state.messages.length - 1; i >= 0; i--) {
      if (state.messages[i].direction !== "in") continue;
      seen += 1;
      if (seen === unread) return i;
    }
    return -1;
  }

  function locationNode(message) {
    if (message.kind !== "location" && !message.location) return null;
    const loc = message.location || {};
    const lat = loc.latitude;
    const lng = loc.longitude;
    const mapsUrl = `https://www.google.com/maps?q=${lat},${lng}`;

    return el("div.msg__location-card", {
      style: "padding: 10px; background: rgba(0,0,0,0.18); border-radius: 8px; margin-bottom: 6px; border: 1px solid rgba(255,255,255,0.08);",
    }, [
      el("div", { style: "display: flex; align-items: center; gap: 6px; font-weight: 600; font-size: 13px;" }, [
        icon("mapPin", { size: 16 }),
        loc.name || "Shared Location Pin",
      ]),
      loc.address ? el("div", { style: "font-size: 12px; opacity: 0.8; margin-top: 2px;" }, [loc.address]) : null,
      el("a.msg__doc", {
        href: mapsUrl,
        target: "_blank",
        rel: "noopener",
        style: "margin-top: 6px; display: inline-flex; align-items: center; gap: 4px; font-size: 12px; color: #25D366; text-decoration: none; font-weight: 600;",
      }, [
        icon("globe", { size: 14 }),
        " Open in Google Maps",
      ]),
    ]);
  }

  /**
   * The quoted line above a reply — in a bubble, and again in the composer
   * while the reply is being written.
   *
   * One node for both so the agent sees exactly what the customer will. The
   * server sends only a trimmed copy of the original (id, who wrote it, kind
   * and the first 120 characters), which is all a quote ever shows.
   */
  function quotedNode(reply, { onCancel = null, clickable = true } = {}) {
    if (!reply) return null;

    const preview =
      reply.body?.trim() || (reply.kind === "text" ? "" : unsupportedLabel(reply.kind));

    return el(
      "div.quoted",
      {
        class: reply.direction === "out" ? "quoted--mine" : "",
        // Jumping to the original is what makes a quote worth reading in a long
        // thread; in the composer there is nothing to jump to yet.
        onclick: clickable && reply.id ? () => highlightMessage(reply.id) : null,
        title: clickable && reply.id ? "Go to the original message" : "",
      },
      [
        el("div.quoted__body", {}, [
          el("div.quoted__who", {}, [reply.sender || (reply.direction === "out" ? "You" : "Customer")]),
          el("div.quoted__text", {}, [
            reply.kind && reply.kind !== "text" ? kindIcon(reply.kind) : null,
            preview,
          ]),
        ]),
        onCancel
          ? el("button.quoted__x", { type: "button", title: "Cancel reply", onclick: onCancel }, [
              icon("close", { size: 15 }),
            ])
          : null,
      ]
    );
  }

  /** Starts a reply to `message`, and puts the cursor where it is needed. */
  function startReply(message) {
    state.replyTo = {
      id: message.id,
      direction: message.direction,
      kind: message.kind,
      body: message.body || "",
      sender:
        message.direction === "in"
          ? findConversation(state.activeId)?.contact?.name || "Customer"
          : message.sent_by?.display_name || "You",
    };
    renderComposer(findConversation(state.activeId));
    ui.composer.querySelector(".composer__input")?.focus();
  }

  /** Human-readable send failure for the bubble (Meta codes + our guards). */
  function formatSendFailure(message) {
    const code = String(message.error_code || "").trim();
    const detail = String(message.error_detail || "").trim();
    if (code === "RECIPIENT_MISMATCH") return detail || "Recipient number mismatch";
    if (code === "131026") {
      return (
        "131026 · Message undeliverable — this phone may not be on WhatsApp, " +
        "or the country code is wrong. Confirm the number and resend the template."
      );
    }
    return [code, detail].filter(Boolean).join(" · ");
  }

  function messageBubble(message) {
    if (message.kind === "system") {
      return el("div.msg.msg--system", { "data-id": message.id ?? "" }, [message.body || ""]);
    }

    const outbound = message.direction === "out";
    const tick = outbound ? STATUS_TICK[message.status] : null;
    const failure = formatSendFailure(message);
    const author = outbound && message.sent_by && message.sent_by.id !== state.me.id ? message.sent_by.display_name : null;

    const media = mediaNode(message);
    const location = locationNode(message);
    const special = specialMessageNode(message);
    const kind = String(message.kind || "").toLowerCase();
    const bodyText = String(message.body || "").trim();
    const isButtonReply = kind === "button" || kind === "interactive";
    const templateLine =
      !bodyText && message.template_name
        ? el("div.msg__template-line", {}, [
            el("span.msg__template-badge", {}, ["Template"]),
            message.template_name,
          ])
        : null;
    const mainText = bodyText && !special
      ? el("div.msg__text", {}, [
          isButtonReply ? buttonReplyTag(kind) : null,
          message.body,
        ])
      : null;
    const templateFooter = kind === "template" ? templateFooterNode(message) : null;
    const templateBtns = kind === "template" ? templateButtonsRow(message) : null;
    const emptyHint =
      !media && !location && !special && !mainText && !templateLine && !templateFooter
        ? el("div.msg__empty-hint", {}, [messageFallbackLabel(message)])
        : null;

    const forwardedTag = message.is_forwarded
      ? el("div.msg__forwarded-tag", {
          style: "font-size: 11px; font-style: italic; opacity: 0.75; display: flex; align-items: center; gap: 4px; margin-bottom: 4px;",
        }, [
          icon("forward", { size: 12 }),
          "Forwarded",
        ])
      : message.is_panel_copy
        ? el("div.msg__forwarded-tag", {
            style: "font-size: 11px; font-style: italic; opacity: 0.75; margin-bottom: 4px;",
          }, ["Panel copy"])
        : null;

    const starBadge = message.is_starred
      ? el("span.msg__star-badge", {
          title: "Starred message",
          style: "color: #eab308; display: inline-flex; align-items: center; margin-left: 4px;",
        }, [
          icon("starFill", { size: 13 }),
        ])
      : null;

    /**
     * Reply / star / forward for one message.
     *
     * Kept out of the bubble and revealed on hover: three buttons under every
     * message tripled the visual weight of the thread and pushed the text
     * apart, while the actions themselves are occasional. They stay reachable
     * without a mouse — focus inside the row reveals it the same way.
     */
    const actionToolbar = el("div.msg__acts", {}, [
      el("button.msg__act", {
        type: "button",
        title: "Reply to this message",
        onclick: () => startReply(message),
      }, [icon("reply", { size: 14 })]),

      el("button.msg__act", {
        type: "button",
        class: message.is_starred ? "msg__act--on" : "",
        title: message.is_starred ? "Unstar message" : "Star message",
        onclick: async (event) => {
          const button = event.currentTarget;
          const next = !message.is_starred;
          button.disabled = true;
          try {
            await inbox.star(message.id, next);
            message.is_starred = next;
            // Repaint this bubble only. Reloading the thread for a star threw
            // away the scroll position and every other bubble's state.
            replaceMessageById(message);
          } catch (err) {
            button.disabled = false;
            toast(`Could not star the message: ${err.message}`, "err");
          }
        },
      }, [icon(message.is_starred ? "starFill" : "star", { size: 14 })]),

      el("button.msg__act", {
        type: "button",
        title: "Forward message",
        onclick: () => {
          openForwardModal({
            message,
            conversations: state.conversations,
            onForward: (conv) => {
              toast(`Forwarded to ${conv.contact?.name || conv.contact?.wa_id || "the chat"}`);
            },
          });
        },
      }, [icon("forward", { size: 14 })]),
    ]);

    return el("div.msg", { class: outbound ? "msg--out" : "msg--in", "data-id": message.id ?? "" }, [
      el("div.msg__stack", {}, [
        el("div.msg__bubble", {}, [
          forwardedTag,
          quotedNode(message.reply_to),
          location,
          special,
          media,
          templateLine,
          mainText,
          templateFooter,
          emptyHint,
          failure ? el("div.msg__error", {}, [failure]) : null,
          retryButton(message),
          el("div.msg__foot", {}, [
            author ? el("span.msg__author", {}, [author]) : null,
            el("span", {}, [stamp(message.created_at)]),
            starBadge,
            tick
              ? el("span.tick", { class: tick.className || "", title: failure || tick.label }, [
                  icon(tick.name, { size: 15 }),
                ])
              : null,
          ]),
        ]),
        templateBtns,
      ]),
      actionToolbar,
      reactionsNode(message),
    ]);
  }

  /**
   * Reactions hang under their own bubble, WhatsApp-style — they are not
   * messages of their own. The payload maps sender wa_id → emoji, so the same
   * emoji from several people collapses into one chip with a count.
   *
   * There is no way to send one from here: the gateway rejects the `reaction`
   * type outright.
   */
  function reactionsNode(message) {
    const emojis = Object.values(message.reactions || {}).filter(Boolean);
    if (!emojis.length) return null;

    const counts = new Map();
    for (const emoji of emojis) counts.set(emoji, (counts.get(emoji) || 0) + 1);

    return el(
      "div.reactions",
      { title: `${emojis.length} reaction${emojis.length > 1 ? "s" : ""}` },
      [...counts].map(([emoji, count]) =>
        el("span.reaction", {}, [emoji, count > 1 ? el("span.reaction__n", {}, [String(count)]) : null])
      )
    );
  }

  /**
   * Retry a failed outbound via the server (templates/media/text). Text-only
   * "Send again" remains as a fallback when the gateway retry is refused.
   */
  function retryButton(message) {
    if (message.status !== "failed" || message.direction !== "out") return null;

    return el(
      "button.msg__retry",
      {
        type: "button",
        style: "margin-top: 6px;",
        onclick: async (event) => {
          const button = event.currentTarget;
          button.disabled = true;
          button.textContent = "Retrying…";
          try {
            await inbox.retry(message.id);
            if (state.activeId) await loadMessages(state.activeId);
          } catch (err) {
            if (message.kind === "text" && message.body) {
              button.textContent = "Sending…";
              try {
                const conversation = findConversation(state.activeId);
                if (conversation) await sendText(conversation, message.body);
                button.remove();
                return;
              } catch (sendErr) {
                toast(`Retry failed: ${sendErr.message || err.message}`, "err");
              }
            } else {
              toast(`Retry failed: ${err.message}`, "err");
            }
            button.disabled = false;
            button.replaceChildren(icon("refresh", { size: 13 }), " Retry");
          }
        },
      },
      [icon("refresh", { size: 13 }), " Retry"]
    );
  }

  /** Opens the viewer on this image, with the rest of the thread's images loaded. */
  function openImage(message) {
    const images = imagesInThread(state.messages);
    const at = Math.max(0, images.findIndex((i) => String(i.id) === String(message.id)));
    openLightbox(images, at);
  }

  function mediaNode(message) {
    return mediaMessageNode(message, {
      onImageClick: openImage,
      formatBytes,
    });
  }

  const UNSUPPORTED_LABEL = {
    location: "Location sent",
    contacts: "Contact card sent",
    reaction: "Reaction",
    interactive: "Interactive message",
    button: "Button reply",
    system: "System message",
    // Meta's own `unsupported` type, stored here as `unknown`: the customer sent
    // something the Cloud API will not carry to a business number — a poll, a
    // view-once message, whatever WhatsApp has added lately. It arrives as error
    // 131051 with the content absent, and Meta does not even say what it was
    // (`raw_type` is itself "unknown"). Nothing can be shown because nothing was
    // sent to us, and nothing can be re-imported later. Spelled out because
    // "[unknown]" reads to an agent as a fault in this panel, and the next thing
    // they do is report a bug instead of asking the customer to resend.
    album: "Photo album",
    pinned_message: "Pinned message",
    unknown: "WhatsApp could not deliver this message. Ask the customer to send it again as text, a photo or a file.",
    unsupported: "WhatsApp could not deliver this message. Ask the customer to send it again as text, a photo or a file.",
  };

  const unsupportedLabel = (kind) =>
    UNSUPPORTED_LABEL[String(kind || "").toLowerCase()] || `[${kind || "unknown"}]`;

  function messageFallbackLabel(message) {
    const kind = String(message.kind || "").toLowerCase();
    if (message.media_failed) {
      if (kind === "audio") return "Voice message — file not saved on server";
      if (kind === "image" || kind === "sticker") return "Photo — file not saved on server";
      if (kind === "video") return "Video — file not saved on server";
      return "Attachment — file not saved on server";
    }
    if (message.status === "failed" || message.status === "exhausted") {
      return formatSendFailure(message) || "Message failed to send";
    }
    if (kind === "template") return message.template_name ? `Template: ${message.template_name}` : "Template message";
    return unsupportedLabel(kind);
  }

  /* ------------------------------------------------------------- composer */

  function renderComposer(conversation) {
    teardownFileSources?.();
    teardownFileSources = null;
    teardownEmoji?.destroy();
    teardownEmoji = null;
    clear(ui.composer);
    if (!conversation) {
      ui.composer.append(slots.composer);
      return;
    }

    if (!conversation.is_session_open) {
      // Do not mount #wa-composer-slot here — reply-buttons / reminders would
      // stay clickable while free-form is closed and look like a broken send.
      ui.composer.append(
        el("div.locked", {}, [
          el("div.locked__main", {}, [
            el("div.locked__text", {}, [
              // Not "sending a template reopens it". A template does not reopen
              // the window — only a message *from* the customer does. Telling an
              // agent otherwise is what sends them to write a free-form reply
              // straight after a template and collect Meta's error 131049.
              "The 24-hour window is closed, so only a template can be sent. " +
                "A template does not reopen free-form chat — after you send it, wait for the customer to reply, then type normally. " +
                "Replying in free text before they answer usually fails with Meta error 131049.",
            ]),
            el("p.locked__note", {}, [
              "This Official API channel also cannot show outbound blue ticks, typing indicators, or send reactions — Meta gateway limits, not a panel bug.",
            ]),
          ]),
          el("button.btn.btn--primary", { type: "button", onclick: () => openTemplates(conversation) }, [
            "Choose a template",
          ]),
        ])
      );
      return;
    }

    const textarea = el("textarea.composer__input", {
      rows: 1,
      placeholder: "Write a message…",
      onkeydown: (event) => {
        if (event.key === "Enter" && !event.shiftKey) {
          event.preventDefault();
          submit();
        }
      },
      oninput: () => autoGrow(textarea),
    });

    async function submit() {
      const body = textarea.value.trim();
      if (!body) return;
      textarea.value = "";
      autoGrow(textarea);
      await sendText(conversation, body);
    }

    // Last cheap chance to reply: after the window lapses every message costs a
    // template, and Meta's marketing cap can refuse it outright.
    if (isClosingSoon(conversation)) {
      const left = untilText(conversation.session_expires_at);
      ui.composer.append(
        el("div.closingbar", {}, [
          icon("clock", { size: 15 }),
          el("span", {}, [
            `The window closes ${left ? `in ${left}` : "in under an hour"} — reply now, or a template will be needed.`,
          ]),
        ])
      );
    }

    const attachBtn = el("button.btn.btn--icon", { type: "button", title: "Attach File" }, [icon("paperclip", { size: 19 })]);
    const openLibrary = () => {
        openSharedLibraryModal({
          isPicker: true,
          onSelectAsset: async (asset) => {
            if (!asset.url) return;
            try {
              // The file is behind the session, and fetch resolves happily on a
              // 404 — without this check the agent would "send" the error page
              // as if it were the brochure.
              const res = await fetch(asset.url, { credentials: "include" });
              if (!res.ok) throw new Error(`the library returned HTTP ${res.status}`);

              const blob = await res.blob();
              const file = new File([blob], asset.file_name || asset.title, {
                type: asset.mime_type || blob.type,
              });
              attachFile(conversation, file);
            } catch (err) {
              toast(`Could not send that file: ${err.message}`, "err");
            }
          },
        });
    };

    const openLocation = () => {
        openLocationModal({
          onSendLocation: async (locData) => {
            await inbox.sendLocation(conversation.id, locData);
            if (state.activeId) await loadMessages(state.activeId);
          },
        });
    };

    const openQuickReplies = () => {
        openQuickRepliesModal({
          isWaAdmin: state.me.is_wa_admin,
          onSelectReply: (reply) => {
            textarea.value += reply.body;
            textarea.focus();
            autoGrow(textarea);
          },
        });
    };

    const emojiBtn = el("button.btn.btn--icon", { type: "button", title: "Emoji" }, [icon("smile", { size: 19 })]);

    // The quote sits above the composer, not inside it, so a long quoted line
    // wraps across the full width instead of squeezing the input.
    if (state.replyTo) {
      ui.composer.append(
        quotedNode(state.replyTo, {
          clickable: false,
          onCancel: () => {
            state.replyTo = null;
            renderComposer(conversation);
          },
        })
      );
    }

    ui.composer.append(
      el("div.composer", {}, [
        el("div.composer__attach", {}, [attachBtn]),
        el("div.composer__attach", {}, [emojiBtn]),
        slots.composer,
        textarea,
        el("button.btn.btn--primary.btn--send", { type: "button", onclick: submit, title: "Send" }, [
          icon("send", { size: 17 }),
          el("span.btn__text", {}, ["Send"]),
        ]),
      ])
    );

    bindSlashAutocomplete({
      textarea,
      isWaAdmin: state.me.is_wa_admin,
      onApply: () => autoGrow(textarea),
    });

    teardownEmoji?.destroy();
    teardownEmoji = bindEmojiPicker({ button: emojiBtn, textarea });

    // Files can arrive from the button, a drop anywhere on the thread, or a
    // paste — a screenshot straight from the clipboard is the fastest of the
    // three and the one agents reach for most.
    teardownFileSources = bindFileSources({
      button: attachBtn,
      dropZone: ui.messages,
      pasteTarget: textarea,
      onFile: (file) => attachFile(conversation, file),
      // Everything else that puts content into a message lives in the same
      // menu, so the composer shows one "add" button rather than four.
      extraItems: [
        { icon: "folder", label: "Shared library", onSelect: openLibrary },
        { icon: "mapPin", label: "Location pin", onSelect: openLocation },
        { icon: "zap", label: "Quick reply", onSelect: openQuickReplies },
      ],
    });

    textarea.focus();
  }

  /** Grows the composer with the text, up to the CSS max-height. */
  function autoGrow(textarea) {
    textarea.style.height = "auto";
    textarea.style.height = `${textarea.scrollHeight}px`;
  }

  function attachFile(conversation, file) {
    const problem = checkFile(file);
    if (problem) {
      // Still open the dialog: it shows the reason next to the file, which is
      // clearer than a toast that disappears.
      openAttachmentDialog(file, { conversationId: conversation.id, onSent: () => {} });
      return;
    }
    openAttachmentDialog(file, {
      conversationId: conversation.id,
      onSent: (message) => {
        if (message?.id && !state.messages.some((m) => String(m.id) === String(message.id))) {
          state.messages.push(message);
          appendMessageNode(messageBubble(message), { wasAtBottom: true });
        }
        bumpConversationActivity(conversation, message || { kind: "document", created_at: new Date().toISOString() });
      },
    });
  }

  /**
   * Optimistic append: the agent sees the bubble instantly, and the real message
   * (with its id and status) replaces it when the API answers. A failure turns
   * the same bubble red instead of losing what they typed.
   */
  function appendOptimistic(patch) {
    const draft = {
      id: `tmp-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      direction: "out",
      status: "queued",
      created_at: new Date().toISOString(),
      ...patch,
    };
    state.messages.push(draft);
    // The agent just hit send, so following their own message is always right.
    appendMessageNode(messageBubble(draft), { wasAtBottom: true });
    return draft;
  }

  /**
   * WhatsApp list rule: only a new message (send or receive) moves a chat.
   * Opening / marking read must not change last_message_at.
   */
  function bumpConversationActivity(conversation, messageLike) {
    if (!conversation) return;
    const at = messageLike?.created_at || new Date().toISOString();
    const prevAt = Date.parse(conversation.last_message_at || "") || 0;
    const nextAt = Date.parse(at) || Date.now();
    if (nextAt < prevAt) {
      upsertConversation(conversation);
      return;
    }
    conversation.last_message_at = at;
    if (messageLike?.kind) conversation.last_message_kind = messageLike.kind;
    const preview =
      (messageLike?.body && String(messageLike.body).trim()) ||
      (messageLike?.kind && messageLike.kind !== "text" ? `[${messageLike.kind}]` : "");
    if (preview) conversation.last_message_preview = String(preview).slice(0, 255);
    upsertConversation(conversation);
  }

  function replaceMessage(draftId, real) {
    const index = state.messages.findIndex((m) => m.id === draftId);
    if (index === -1) return;
    const node = ui.messages.querySelector(`[data-id="${CSS.escape(String(draftId))}"]`);

    // The WebSocket echo of our own send can land before the HTTP response.
    // If it already painted the real message, drop the draft instead of
    // producing a second copy of it.
    const alreadyLive =
      real?.id !== undefined && state.messages.some((m, i) => i !== index && String(m.id) === String(real.id));
    if (alreadyLive) {
      state.messages.splice(index, 1);
      node?.remove();
      return;
    }

    state.messages[index] = { ...state.messages[index], ...real };
    node?.replaceWith(messageBubble(state.messages[index]));
  }

  async function sendText(conversation, body) {
    // Taken before the await: the agent can cancel the quote, or start another
    // reply, while this send is still in the air.
    const replyTo = state.replyTo;
    if (replyTo) {
      state.replyTo = null;
      renderComposer(conversation);
    }

    const draft = appendOptimistic({ kind: "text", body, reply_to: replyTo });
    bumpConversationActivity(conversation, draft);
    try {
      const real = await inbox.send(conversation.id, {
        kind: "text",
        body,
        reply_to_id: replyTo?.id,
      });
      replaceMessage(draft.id, real || { status: "sent" });
      if (real?.created_at) bumpConversationActivity(conversation, real);
    } catch (error) {
      replaceMessage(draft.id, { status: "failed", body: `${body}\n\n⚠ ${error.message}` });
    }
  }

  /* ------------------------------------------------------------- modals */

  async function templatesFor(numberId, conversation) {
    const id = String(numberId || conversation?.number_id || "");
    if (id && state.templates.has(id)) return state.templates.get(id);

    const ownsNumber = Boolean(id) && state.numbers.some((n) => String(n.id) === id);
    const thread =
      conversation?.id
        ? conversation
        : state.conversations.find(
            (c) =>
              String(c.number_id) === id &&
              String(c.assigned_agent?.id || c.assigned_agent) === String(state.me.id)
          );

    let list;
    if (ownsNumber) {
      list = asList(await catalog.templates(id), "templates");
    } else if (thread?.id) {
      // Transfer grants the thread, not the number roster. Catalog 404s
      // on a number the agent does not hold — the chat endpoint does not.
      list = asList(await inbox.conversationTemplates(thread.id), "templates");
    } else {
      throw new Error("This chat's WhatsApp number is not available.");
    }
    if (id) state.templates.set(id, list);
    return list;
  }


  /**
   * Sending a template is its own screen: the fields it needs depend on the
   * template, and the only way to be sure they were filled in right is to see
   * the message being built. See template-composer.js.
   */
  function openTemplates(conversation) {
    openTemplateComposer({
      mode: "reply",
      conversation,
      templatesFor,
      onSent: () => openConversation(conversation.id),
    });
  }

  /**
   * Where the QR-linked channel lives.
   *
   * This was `/qr/` — the wa-qr service — and is now OpenWA. **wa-qr has not been
   * removed**: it is still running, still holds both linked phones and all of its
   * history, and putting this line back is the whole of going back to it.
   *
   * An absolute URL on a different port rather than a path, because OpenWA is a
   * single-page app that asks for `/assets/…` and `/api/…` absolutely, and `/api/`
   * on this host already belongs to Django. nginx publishes it on 2786 with the
   * certificate this name already has, behind the same session gate that stands
   * in front of `/qr/`.
   *
   * None of this touches the Business Platform side. The WABA numbers, their
   * templates and the inbox around them are served by `backend/` through
   * alots.io and know nothing about either of these services.
   */
  const LINKED_DEVICES_URL = "https://wa.srv1802669.hstgr.cloud:2786/";

  /**
   * The QR channel, filling the panel rather than floating over it.
   *
   * Deliberately not modal(): that sizes itself in vh, and the panel is
   * already inside Bitrix's own iframe, where vh measures the outer window and
   * not the room actually available — so the dialog ran off the bottom with
   * the composer below the fold. This covers the panel's own surface instead,
   * which is a size the browser can be sure of.
   *
   * It is a whole screen of its own, not a dialog: a QR-linked phone is a
   * different channel with different rules, and it has a chat list, threads
   * and a composer of its own.
   */
  /**
   * @param {string} [phoneDigits]  when set (CRM "Open with WhatsApp"), land on
   *   that chat in OpenWA, or the new-contact form if there is no chat yet.
   */
  function openLinkedDevices(phoneDigits) {
    if (me.can_linked_devices === false) {
      toast("Linked phones access is not enabled for your account", "err");
      return;
    }
    const digits = String(phoneDigits || "").replace(/\D/g, "");
    const base = LINKED_DEVICES_URL.replace(/\/+$/, "");
    const src = digits.length >= 8
      ? `${base}/chats?phone=${encodeURIComponent(digits)}&embedded=1`
      : `${base}/?embedded=1`;

    const frame = el("iframe.linked__frame", {
      src,
      title: "Linked phones",
      // Voice notes: getUserMedia is refused in a nested iframe unless this
      // frame (and Bitrix's outer iframe) delegate the microphone.
      allow: "microphone; autoplay",
      // Every flag here was added because something inside was silently doing
      // nothing without it. A sandboxed frame does not refuse loudly.
      //
      //   allow-modals    — prompt() answered null and confirm() answered false
      //                     without asking anybody, which reads as "cancelled".
      //                     Linking a phone returned before it started.
      //   allow-popups    — target="_blank" was dropped on the floor, so View
      //                     on a document and the lightbox's window.open did
      //                     nothing at all, with no error either way.
      //   allow-downloads — the download attribute was ignored the same way,
      //                     so Download did nothing on a 13 MB PDF.
      //   …-to-escape-sandbox — a tab opened from here inherits the sandbox
      //                     otherwise, and Chrome's PDF viewer will not run
      //                     inside one. The document opened to a blank tab.
      sandbox:
        "allow-scripts allow-same-origin allow-forms allow-modals " +
        "allow-popups allow-popups-to-escape-sandbox allow-downloads",
    });

    // Signing the agent in, so they never meet a login screen.
    //
    // OpenWA's only credential is an API key. Asking an agent to hold one would
    // be asking them to keep a password that opens every conversation on the
    // number — so the panel fetches theirs and hands it over, and they see the
    // chats instead of a box they have no way to fill.
    //
    // The frame speaks first: it posts `openwa_ready` once its listener is
    // attached. Posting before that raced the iframe's own boot and the message
    // landed on nothing. The key is fetched in parallel, so whichever arrives
    // second does the send.
    //
    // Addressed to the frame's exact origin, never "*" — a wildcard would offer
    // the key to whatever happened to be in that frame.
    const openwaOrigin = new URL(LINKED_DEVICES_URL).origin;
    let credentials = null;
    let frameReady = false;

    const handOver = () => {
      if (!frameReady || !credentials?.apiKey) return;
      frame.contentWindow?.postMessage(
        { type: "openwa_auth", key: credentials.apiKey },
        openwaOrigin
      );
      if (digits.length >= 8) {
        frame.contentWindow?.postMessage(
          { type: "openwa_open_phone", phone: digits },
          openwaOrigin
        );
      }
    };

    const onFrameMessage = (event) => {
      if (event.origin !== openwaOrigin) return;
      if (event.data?.type !== "openwa_ready") return;
      frameReady = true;
      handOver();
    };
    window.addEventListener("message", onFrameMessage);

    fetch("/api/auth/openwa-credentials/", { credentials: "include" })
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        credentials = data;
        handOver();
      })
      .catch(() => {
        // Left deliberately quiet. The frame falls back to its own login box,
        // which is a worse experience but not a broken one, and an alert over
        // the panel would say nothing an agent could act on.
      });

    const close = () => {
      document.removeEventListener("keydown", onKey, true);
      window.removeEventListener("message", onFrameMessage);
      screen.remove();
    };
    const onKey = (event) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      close();
    };

    // Same liquid-glass shell as the Omni / API WhatsApp screen (pic-1), so the
    // QR-linked inbox does not look like a different product sitting next to it.
    const screen = el("section.linked", {}, [
      el("div.linked__glass-bg", { "aria-hidden": "true" }, [
        el("div.linked__blob.linked__b1"),
        el("div.linked__blob.linked__b2"),
        el("div.linked__blob.linked__b3"),
        el("div.linked__blob.linked__b4"),
      ]),
      el("header.linked__bar", {}, [
        icon("smartphone", { size: 17 }),
        el("span.linked__title", {}, ["Linked phones"]),
        el("button.btn.btn--icon.linked__close", { type: "button", title: "Back to the inbox", onclick: close }, [
          icon("close", { size: 18 }),
        ]),
      ]),
      frame,
    ]);

    document.addEventListener("keydown", onKey, true);
    root.append(screen);
  }

  function openNumbers() {
    openNumbersAdmin({
      onSaved: (numbers) => {
        // A rename has to reach the list, the thread header and the filter,
        // all of which read from state.numbers.
        state.numbers = asList(numbers, "numbers");
        renderNumberFilter();
        renderConversations();
        const active = findConversation(state.activeId);
        if (active) renderThreadHeader(active);
      },
    });
  }

  // Nothing to refresh afterwards: the roster changes what an *agent* can reach
  // on their next open, and nothing on this admin's own screen depends on it.
  function openLinkedPhones() {
    openLinkedPhonesAdmin();
  }

  function openRequests() {
    openAccessRequests({ onOpenNumbers: openNumbers });
    // Reading them is the acknowledgement; the count refreshes from the server
    // rather than being cleared optimistically.
    setTimeout(refreshRequestCount, 500);
  }

  /** Keeps the menu badge honest. Silent on failure — it is only a hint. */
  async function refreshRequestCount() {
    try {
      const pending = asList(await access.list(), "requests").filter((r) => r.status !== "resolved");
      requestsBadge.textContent = String(pending.length);
      requestsBadge.hidden = pending.length === 0;
    } catch {
      requestsBadge.hidden = true;
    }
  }

  function openNewContact({ to = "" } = {}) {
    openTemplateComposer({
      mode: "new",
      to,
      numbers: state.numbers.map((n) => ({ ...n, title: numberTitle(n) })),
      templatesFor,
      findExisting: findConversationByWaId,
      onOpenExisting: (id) => openConversation(id),
      onSent: async (created) => {
        await loadConversations({ keepActive: false });
        if (created?.id) await openConversation(created.id);
      },
    });
  }

  /**
   * Any existing thread with this customer, on any of our numbers.
   *
   * The server keeps one conversation per (our number, customer) and reuses it,
   * so sending from the same number can never duplicate anything. What it does
   * not stop is an agent picking a different one of our numbers, which opens a
   * second thread with the same person — that is what the composer warns about.
   */
  async function findConversationByWaId(waId) {
    const match = (c) => String(c.contact?.wa_id || "").endsWith(waId) || waId.endsWith(String(c.contact?.wa_id || ""));

    let found = state.conversations.find(match);
    if (!found) {
      // The list only holds the first page, so ask the server before deciding
      // there is no existing chat.
      const payload = await inbox.conversations({ q: waId, limit: 10 });
      found = asList(payload, "conversations").find(match);
    }
    if (!found && window.a7wa?.findLeadAiChat) {
      // This list leaves Lead AI chats out; their own screen still knows them.
      const leadAi = await window.a7wa.findLeadAiChat(waId).catch(() => null);
      if (leadAi) {
        return {
          id: leadAi.id,
          number_id: leadAi.number_id,
          number_title: `${numberTitle(numberById(leadAi.number_id))} (in Lead AI)`,
        };
      }
    }
    if (!found) return null;

    return {
      id: found.id,
      number_id: found.number_id,
      number_title: numberTitle(numberById(found.number_id)),
    };
  }

  async function openTransfer(conversation) {
    const agentSelect = el("select.field", {}, [el("option", { value: "" }, ["Loading agents…"])]);
    const reason = el("input.field", { type: "text", placeholder: "Reason (optional)" });
    const error = el("div.alert", { hidden: true });
    const send = el("button.btn.btn--primary", { type: "button", disabled: true }, ["Transfer"]);

    const dialog = modal(
      "Chat transfer",
      el("div.modal__body", {}, [
        el("p.modal__note", {}, ["The full history moves with the chat. Nothing is deleted."]),
        el("label.field__row", {}, [el("span", {}, ["Select Agent"]), agentSelect]),
        el("label.field__row", {}, [el("span", {}, ["Reason"]), reason]),
        error,
        el("div.modal__actions", {}, [send]),
      ])
    );

    try {
      const agentsList = await catalog.agents();
      clear(agentSelect);
      const activeAgents = (agentsList || []).filter((a) => a.is_active !== false);

      if (!activeAgents.length) {
        agentSelect.append(el("option", { value: "" }, ["No active agents found"]));
      } else {
        agentSelect.append(el("option", { value: "" }, ["-- Select Agent --"]));
        const currentAgentId = conversation?.assigned_agent?.id || conversation?.assigned_agent;
        for (const agent of activeAgents) {
          const isCurrent = String(agent.id) === String(currentAgentId);
          agentSelect.append(
            el("option", { value: agent.id }, [
              `${agent.display_name || agent.username}${
                agent.community ? ` · ${agent.community}` : ""
              } ${isCurrent ? "(Current)" : ""}`,
            ])
          );
        }
        send.disabled = false;
      }
    } catch (err) {
      clear(agentSelect).append(el("option", { value: "" }, ["Could not load agents"]));
      error.hidden = false;
      error.textContent = `Error loading agents: ${err.message}`;
    }

    send.addEventListener("click", async () => {
      const selectedId = agentSelect.value;
      if (!selectedId) {
        error.hidden = false;
        error.textContent = "Please select an agent to transfer the chat.";
        return;
      }
      send.disabled = true;
      send.textContent = "Transferring…";
      try {
        const updated = await inbox.assign(conversation.id, {
          agent_id: selectedId,
          reason: reason.value.trim() || undefined,
        });
        dialog.close();
        await focusTransferredChat(updated || conversation);
        const picked = activeAgents.find((a) => String(a.id) === String(selectedId));
        toast(
          `Copied onto ${picked?.display_name || picked?.username || "the agent"}'s Official number. They send the next WhatsApp message from that number (template if the window is closed).`
        );
      } catch (err) {
        send.disabled = false;
        send.textContent = "Transfer";
        error.hidden = false;
        error.textContent = err.message;
      }
    });
  }

  /* ------------------------------------------------- API for companions */

  /**
   * The seam the companion modules (search, reminders, reply buttons) build
   * against. They render into the #wa-*-slot anchors and drive the thread
   * through here, so they never reach into this file's internals.
   *
   * `wa:ready` fires last, once the panel is on screen and the API is callable.
   */
  function publishApi() {
    window.a7wa = window.a7wa || {};

    window.a7wa.openConversation = (id, options = {}) => openConversation(id, options);

    // Read-only views of what the panel is showing, so a companion does not
    // have to refetch what is already here.
    window.a7wa.getActiveConversationId = () => state.activeId;
    window.a7wa.getMe = () => state.me;

    window.dispatchEvent(new CustomEvent("wa:ready", { detail: { me: state.me } }));
  }

  /* ------------------------------------------------------------ realtime */

  let liveSocket = null;
  let socketUnloadBound = false;

  function connectSocket() {
    liveSocket?.close();
    const socket = new InboxSocket({
      onEvent: handleEvent,

      onStatus: ({ state: connState, resync }) => {
        state.connection = connState;
        ui.connection.hidden = connState === "open";
        ui.connection.textContent =
          connState === "open" ? "" : "Live connection lost — reconnecting…";
        // A gap in the socket means missed events; REST is the source of truth.
        if (connState === "open" && resync) {
          loadConversations();
          if (state.activeId) openConversation(state.activeId);
        }
      },

      // The socket was rejected as unauthenticated: the Django session lapsed.
      // Re-run the Bitrix handshake once, then reconnect — the agent never sees
      // a login prompt, which is the whole point of the SSO.
      onAuthLost: async () => {
        ui.connection.hidden = false;
        ui.connection.textContent = "Re-establishing your session…";
        try {
          await ensureSession();
          socket.connect();
          loadConversations();
        } catch (error) {
          ui.connection.textContent = `Your session could not be restored — reload the page. (${error.message})`;
          console.error("[a7-wa] re-auth failed:", error);
        }
      },
    });

    liveSocket = socket;
    socket.connect();
    if (!socketUnloadBound) {
      socketUnloadBound = true;
      window.addEventListener("beforeunload", () => liveSocket?.close());
    }
  }

  // Events carry whole objects, not ids, so the panel renders them directly
  // instead of refetching the list on every inbound message.
  function handleEvent(event, data) {
    if (event === "ready") return;
    // Lead AI chats are heard by the Lead AI module (modules/lead-ai/). One
    // that is still listed here just moved there, so it leaves this list.
    if (String(event).startsWith("leadai.")) {
      return dropLeadAiChat(data?.conversation?.id ?? data?.message?.conversation_id);
    }
    // A plain notice about a Lead AI chat (a transfer, a reminder's chat) must
    // not pull it into this list or reset the filters for it.
    if (data?.conversation?.lead_ai) return dropLeadAiChat(data.conversation.id);
    if (event === "message.new") return onMessageNew(data);
    if (event === "message.status") return onMessageStatus(data.message);
    if (event === "conversation.updated" || event === "conversation.assigned") {
      const mine = String(data.conversation?.assigned_agent?.id || "") === String(state.me?.id);
      if (event === "conversation.assigned" && mine) {
        toast("A chat was transferred to you.");
        focusTransferredChat(data.conversation);
        return;
      }
      return onConversationChanged(data.conversation, { force: mine });
    }
    // The closing warning carries the conversation, and the panel derives the
    // warning state from it — so re-sends of the same warning are harmless.
    if (event === "session.closing") return onConversationChanged(data.conversation);

    // A new agent asked for a number. Only admins can act on it.
    if (event === "access.requested") {
      if (state.me.is_wa_admin) refreshRequestCount();
      return;
    }
    console.debug("[a7-wa] unhandled ws event:", event, data);
  }

  /**
   * Transfer landed this thread on the agent looking at the panel. Drop the
   * number / search / tag filters so it is not hidden, then open it — list
   * row and thread together.
   */
  async function focusTransferredChat(conversation) {
    if (!conversation) return;
    state.search = "";
    ui.search.value = "";
    state.tagFilter = null;
    state.numberFilter = "";
    numberPicker.refresh({ resetSearch: true });
    quickFilters.render();
    await loadConversations({ keepActive: true });
    upsertConversation(conversation, { force: true });
    await openConversation(conversation.id);
  }

  /**
   * Takes a chat that now lives in the Lead AI screen out of this inbox: off
   * the list, and out of the thread pane if it was the open one.
   */
  function dropLeadAiChat(id, { quiet = false } = {}) {
    if (id === undefined || id === null || id === "") return;
    const before = state.conversations.length;
    state.conversations = state.conversations.filter((c) => String(c.id) !== String(id));
    if (String(state.activeId) === String(id)) {
      closeContactPanel();
      state.activeId = null;
      state.messages = [];
      state.replyTo = null;
      renderEmptyThread();
      // Said out loud: the open chat just went somewhere else.
      if (!quiet) toast("This chat moved to Lead AI.");
    }
    if (state.conversations.length !== before) {
      // The server's list shifted up by one; keep "Load more" from skipping a chat.
      state.listOffset = Math.max(0, (state.listOffset || 0) - 1);
      renderConversations();
      renderListStatus();
    }
  }

  function sendToLeadAi(id, highlightMessageId) {
    if (window.a7wa?.openLeadAi) window.a7wa.openLeadAi(id, { highlightMessageId });
    else toast("This chat is in Lead AI.", "err");
  }

  /** Inserts or replaces a conversation, keeping the list newest-activity-first. */
  function upsertConversation(conversation, { force = false } = {}) {
    if (!conversation) return;
    // Never list a Lead AI chat here, whatever path brought it (a closing
    // warning, a transfer, an open from a link). See dropLeadAiChat.
    if (conversation.lead_ai) return dropLeadAiChat(conversation.id);
    // A filtered-out number must not silently reappear in the list — unless
    // this chat was just transferred to the agent sitting here.
    if (
      !force &&
      !isTransferredIn(conversation) &&
      state.numberFilter &&
      String(conversation.number_id) !== String(state.numberFilter)
    ) {
      return;
    }

    const index = state.conversations.findIndex((c) => c.id === conversation.id);
    if (index === -1) {
      state.conversations.unshift(conversation);
    } else {
      const prev = state.conversations[index];
      if (prev.staff_only) conversation = { ...conversation, staff_only: true };
      const prevAt = Date.parse(prev.last_message_at || "") || 0;
      const nextAt = Date.parse(conversation.last_message_at || "") || 0;
      // Opening a chat (or a stale WS payload) must not bury a thread we just
      // bumped for a send — keep the fresher activity fields.
      if (nextAt < prevAt) {
        conversation = {
          ...conversation,
          last_message_at: prev.last_message_at,
          last_message_preview: prev.last_message_preview,
          last_message_kind: prev.last_message_kind,
        };
      }
      state.conversations[index] = conversation;
    }

    renderConversations();
    renderListStatus();
  }

  /**
   * Replaces a message already in the thread, in place.
   *
   * The server re-pushes the *same* message when something about it changes —
   * a reaction arriving or being taken back is the common case. Appending that
   * would show the message twice.
   *
   * @returns {boolean} false when the message is not in the open thread.
   */
  function replaceMessageById(message) {
    const index = state.messages.findIndex((m) => String(m.id) === String(message.id));
    if (index === -1) return false;

    state.messages[index] = message;
    const node = ui.messages.querySelector(`[data-id="${CSS.escape(String(message.id))}"]`);
    node?.replaceWith(messageBubble(message));
    return true;
  }

  function onMessageNew({ message, conversation }) {
    const active = conversation?.id === state.activeId;

    if (message?.direction === "in") {
      notifyNewMessage({
        contactName: conversation?.contact?.name || conversation?.contact?.wa_id || "Customer",
        messageText: message.body || "New message received",
        conversationId: conversation?.id,
        onClick: () => {
          if (conversation?.id) openConversation(conversation.id);
        },
      });
    }

    if (active) {
      // An id we already hold means this is a re-push (a reaction changed, or
      // the echo of a send we painted optimistically) — update, never append.
      if (!replaceMessageById(message)) {
        state.messages.push(message);
        appendMessageNode(messageBubble(message));
      }
      // The open thread is only actually being read if this tab is on screen.
      if (message.direction === "in") markRead(conversation);
    }

    // New message activity — same rule as WhatsApp: this chat jumps to the top.
    bumpConversationActivity(conversation, message);
    if (active) {
      renderThreadHeader(conversation);
      renderComposer(conversation);
    }
  }

  function onMessageStatus(message) {
    if (!message || message.conversation_id !== state.activeId) return;
    replaceMessageById(message);
  }

  function onConversationChanged(conversation, { force = false } = {}) {
    upsertConversation(conversation, { force });
    if (conversation?.id === state.activeId) {
      // Assignment or an expiring window changes what the composer may do.
      renderThreadHeader(conversation);
      renderComposer(conversation);
    }
  }

  return boot();
}
