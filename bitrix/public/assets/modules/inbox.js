/**
 * The agent inbox: conversation list on the left, thread on the right.
 *
 * Deliberately framework-free — the panel is served as static files from nginx,
 * so staying on plain ES modules keeps "deploy" equal to "copy the folder" with
 * no build step between an edit and the browser.
 *
 * Server rules the UI must mirror (see the API contract):
 *  - an agent sees every chat on their numbers, assigned or not; `assigned_agent`
 *    is ownership for transfers, never a list filter;
 *  - when `is_session_open` is false the composer is locked and only approved
 *    templates can reopen the 24h window;
 *  - transfer is admin-only.
 */

import { access, auth, catalog, inbox, asList } from "../api/api.js";
import { openAccessRequests, renderNoNumbersScreen } from "./access-requests.js";
import { bindFileSources, checkFile, openAttachmentDialog } from "./attach.js";
import { ensureSession } from "../core/bitrix-sso.js";
import { imagesInThread, openLightbox } from "../core/lightbox.js";
import { openNumbersAdmin } from "./numbers-admin.js";
import { openContactPanel, closeContactPanel } from "./contact-panel.js";
import { openTemplateComposer, openTemplateManager } from "./template-composer.js";
import { openSharedLibraryModal } from "./shared-library.js";
import { openLocationModal } from "./location-picker.js";
import { openQuickRepliesModal, bindSlashAutocomplete } from "./quick-replies.js";
import { openStarredMessagesModal } from "./starred-messages.js";
import { openAgentsAdminModal } from "./agents-admin.js";
import { openForwardModal } from "./forward-picker.js";
import { openReportsModal } from "./reports.js";
import { notifyNewMessage, playChime, requestNotificationPermission, isSoundEnabled, setSoundEnabled, isDesktopEnabled, setDesktopEnabled } from "../core/notifications.js";
import { InboxSocket } from "../core/realtime.js";
import { el, clear, dayKey, dayLabel, debounce, formatBytes, minutesUntil, modal, stamp, toast, untilText, initials } from "../core/dom.js";
import { bindEmojiPicker } from "../core/emoji.js";
import { icon, iconForKind } from "../core/icons.js";

const PAGE_SIZE = 40;

const STATUS_TICK = {
  queued: { name: "clock", label: "queued" },
  sent: { name: "check", label: "sent" },
  delivered: { name: "checkDouble", label: "delivered" },
  read: { name: "checkDouble", label: "read", className: "tick--read" },
  failed: { name: "alert", label: "failed", className: "tick--failed" },
};

export function mountInbox(root, { me }) {
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
  };

  // Composer listeners (attach button, drop zone, paste) are rebound whenever
  // the composer is re-rendered; this releases the previous set.
  let teardownFileSources = null;
  let teardownEmoji = null;

  /* ------------------------------------------------------------ structure */

  const ui = {
    numberSelect: el("select.filter__select", { onchange: onNumberFilterChange }),
    search: el("input.filter__search", {
      type: "search",
      placeholder: "Search by name or number",
      oninput: debounce((event) => {
        state.search = event.target.value.trim();
        loadConversations();
      }),
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

  const menuPanel = el("div.sidebar__menu", { hidden: true }, [
    slots.search,
    el("button.btn.menu__item", { onclick: openProfile, type: "button" }, [
      icon("user", { size: 16 }),
      "My Profile",
    ]),
    el("button.btn.menu__item", { onclick: () => openTemplateManager(), type: "button" }, [
      icon("file", { size: 16 }),
      "Templates Center",
    ]),
    el("button.btn.menu__item", { onclick: () => openSharedLibraryModal(), type: "button" }, [
      icon("folder", { size: 16 }),
      "Shared Library",
    ]),
    el("button.btn.menu__item", { onclick: () => openReportsModal(), type: "button" }, [
      icon("zap", { size: 16 }),
      "Reports",
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
    me.is_wa_admin
      ? el("button.btn.menu__item", { onclick: () => openAgentsAdminModal({ me }), type: "button" }, [
          icon("userCheck", { size: 16 }),
          "Agents & Panel Admins",
        ])
      : null,
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
    me.is_wa_admin
      ? el("button.btn.menu__item", { onclick: openNumbers, type: "button" }, [
          icon("hash", { size: 16 }),
          "Numbers",
        ])
      : null,
    me.is_wa_admin
      ? el("button.btn.menu__item", { onclick: openLinkedDevices, type: "button" }, [
          icon("smartphone", { size: 16 }),
          "Linked devices",
        ])
      : null,
    me.is_wa_admin
      ? el("button.btn.menu__item", { onclick: openRequests, type: "button" }, [
          icon("users", { size: 16 }),
          "New agent messages",
          requestsBadge,
        ])
      : null,
    el("button.btn.menu__item", { onclick: openNewContact, type: "button" }, [
      icon("plus", { size: 16 }),
      "New contact",
    ]),
  ]);

  const menuBtn = el("button.btn.btn--icon.sidebar__menu-btn", { type: "button", title: "Menu" }, [
    icon("menu", { size: 19 }),
  ]);

  const layout = el("div.app", {}, [
    el("aside.sidebar", {}, [
      // The menu button is a direct child of the bar on purpose: companion
      // modules locate their insertion point with
      // `sidebarTop.querySelector(".btn")` and then insertBefore it, which
      // throws if that button is nested inside a wrapper.
      el("div.sidebar__top", {}, [
        el("div.sidebar__title", {}, ["WhatsApp"]),
        menuBtn,
        menuPanel,
      ]),
      el("div.filter", {}, [ui.numberSelect, ui.search]),
      // List and status share one scroll box so the empty-state message sits
      // right under the (possibly empty) list instead of at the sidebar's foot.
      el("div.convs__wrap", {}, [ui.list, ui.listStatus]),
    ]),
    el("section.thread", {}, [ui.connection, ui.threadHeader, ui.messages, ui.composer]),
  ]);

  bindSidebarMenu();
  renderEmptyThread();

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

    // With no number there is nothing to show and no chat to open, so the
    // panel becomes a way to ask for one instead of an empty list.
    if (!state.numbers.length) {
      root.className = "";
      renderNoNumbersScreen(root, { me, onAssigned: () => window.location.reload() });
      return;
    }

    renderNumberFilter();
    await loadConversations();

    root.className = "";
    clear(root).append(layout);
    connectSocket();
    publishApi();
    if (me.is_wa_admin) refreshRequestCount();

    // The frame's height is Bitrix's to decide, and the panel simply fills it.
    // Asking for a taller frame (there is no API for "how much room do I have")
    // meant guessing, and a guess that overshot pushed the portal page into a
    // scrollbar that hid its own header — worse than a shorter panel.
  }

  async function loadConversations({ keepActive = true } = {}) {
    ui.listStatus.textContent = "Loading…";
    try {
      const payload = await inbox.conversations({
        number: state.numberFilter || undefined,
        q: state.search || undefined,
        limit: PAGE_SIZE,
      });
      state.conversations = asList(payload, "conversations");
      renderConversations();
      ui.listStatus.textContent = state.conversations.length ? "" : "No conversations.";

      if (keepActive && state.activeId) {
        const still = state.conversations.some((c) => c.id === state.activeId);
        if (!still) renderEmptyThread();
      }
    } catch (error) {
      ui.listStatus.textContent = `Could not load the list: ${error.message}`;
      console.error("[a7-wa] conversations failed:", error);
    }
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
        if (known?.contact) known.contact.name = contact.name;
        renderConversations();
        renderThreadHeader(known || conversation);
      },
      onOpenConversation: (id) => openConversation(id),
    });
  }

  async function openConversation(id, { highlightMessageId } = {}) {
    if (state.loadingThread) return;
    // The profile describes one customer; carrying it into another chat would
    // show the wrong person beside the right messages.
    if (state.activeId !== id) closeContactPanel();
    // A half-written reply belongs to the chat it was started in.
    if (state.activeId !== id) state.replyTo = null;
    state.activeId = id;
    state.loadingThread = true;
    renderConversations();
    clear(ui.messages).append(el("div.thread__hint", {}, ["Loading…"]));

    try {
      renderThreadHeader(findConversation(id));
      const payload = await inbox.messages(id, { limit: PAGE_SIZE });

      // The endpoint already hands back the newest slice in oldest-first order,
      // which is exactly the reading order — do not re-sort it.
      state.messages = asList(payload, "messages");

      // A search hit can point at a message far above the newest page.
      if (highlightMessageId) await loadUntilMessage(id, highlightMessageId);

      // It also returns the conversation, fresher than the list copy.
      const conversation = payload?.conversation || findConversation(id);
      if (payload?.conversation) upsertConversation(payload.conversation);

      // Captured before mark-read so the "new messages" divider survives.
      state.unreadAtOpen = conversation?.unread_count || 0;

      renderThreadHeader(conversation);
      renderMessages();
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
      if (payload?.conversation) upsertConversation(payload.conversation);
      renderMessages();
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
    }
    return false;
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
    const names = agents.map((a) => a.display_name).filter(Boolean);

    const customLabel = (number?.label || (number?.title !== number?.phone_number ? number?.title : "") || "").trim();
    const isDistinctLabel = customLabel && customLabel !== rawPhone && customLabel !== phone;

    if (names.length) {
      const assignedText = names.join(", ");
      if (isDistinctLabel && !names.includes(customLabel)) {
        return `${phone} (${customLabel}) → ${assignedText}`;
      }
      return `${phone} → ${assignedText}`;
    }

    if (isDistinctLabel) {
      return `${phone} → ${customLabel}`;
    }

    return `${phone} → Not assigned`;
  }

  function renderNumberFilter() {
    clear(ui.numberSelect);
    // With a single number the filter is noise — the agent has no choice to make.
    if (state.numbers.length < 2) {
      ui.numberSelect.hidden = true;
      return;
    }
    ui.numberSelect.hidden = false;
    ui.numberSelect.append(el("option", { value: "" }, ["All numbers"]));
    for (const number of state.numbers) {
      ui.numberSelect.append(el("option", { value: number.id }, [numberOptionLabel(number)]));
    }
  }

  function onNumberFilterChange(event) {
    state.numberFilter = event.target.value;
    loadConversations({ keepActive: false });
  }

  /**
   * `title` is the server's own answer to "what should this number be called"
   * (admin label → gateway name → digits). Everything the agent sees goes
   * through it, so a rename shows up in one place.
   */
  const numberTitle = (number) => number?.title || number?.phone_number || "—";

  function renderConversations() {
    clear(ui.list);
    const conversationsToDraw = state.tagFilter
      ? state.conversations.filter((c) => (c.labels || []).some((l) => l.name === state.tagFilter))
      : state.conversations;

    for (const conversation of conversationsToDraw) {
      const open = conversation.is_session_open;
      const labelsNode = conversation.labels?.length
        ? el("div.conv__labels", { style: "display: flex; flex-wrap: wrap; gap: 4px; margin-top: 4px;" }, [
            ...conversation.labels.map((l) =>
              el("span.conv__label-chip", { style: `background: ${l.colour}; color: #fff; padding: 1px 6px; border-radius: 8px; font-size: 10px; font-weight: 600;` }, [l.name])
            ),
          ])
        : null;

      ui.list.append(
        el(
          "li.conv",
          {
            class: [
              conversation.id === state.activeId ? "conv--active" : "",
              isClosingSoon(conversation) ? "conv--closing" : "",
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
                  conversation.last_message_preview || "",
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
                el("span.conv__number", {}, [numberTitle(numberById(conversation.number_id))]),
              ]),
            ]),
          ]
        )
      );
    }
  }

  const numberById = (id) => state.numbers.find((n) => String(n.id) === String(id));

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
            numberTitle(numberById(conversation.number_id)),
          ]),
        ]),
      ]),
      el("div.thread__tools", {}, [
        el("span.pill", { class: sessionPillClass(conversation) }, [
          open ? (left ? `Window open · ${left}` : "Window open") : "Window closed",
        ]),
        conversation.assigned_agent
          ? el("span.pill", {}, [`@${conversation.assigned_agent.display_name || conversation.assigned_agent}`])
          : null,
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
          : null,
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

  function renderMessages() {
    clear(ui.messages);

    const unreadFrom = firstUnreadIndex();
    let lastDay = null;

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

    followTail = true;
    scrollToBottom();
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
            button.disabled = false;
            button.replaceChildren(icon("refresh", { size: 13 }), " Retry");
            toast(`Retry failed: ${err.message}`, "err");
          }
        },
      },
      [icon("refresh", { size: 13 }), " Retry"]
    );
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

  function messageBubble(message) {
    const outbound = message.direction === "out";
    const tick = outbound ? STATUS_TICK[message.status] : null;
    const failure = [message.error_code, message.error_detail].filter(Boolean).join(" · ");
    const author = outbound && message.sent_by && message.sent_by.id !== state.me.id ? message.sent_by.display_name : null;

    const media = mediaNode(message);
    const location = locationNode(message);

    const forwardedTag = message.is_forwarded
      ? el("div.msg__forwarded-tag", {
          style: "font-size: 11px; font-style: italic; opacity: 0.75; display: flex; align-items: center; gap: 4px; margin-bottom: 4px;",
        }, [
          icon("forward", { size: 12 }),
          "Forwarded",
        ])
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
      el("div.msg__bubble", {}, [
        forwardedTag,
        quotedNode(message.reply_to),
        location,
        media,
        message.body ? el("div.msg__text", {}, [message.body]) : null,
        !media && !location && !message.body ? el("div.msg__unsupported", {}, [unsupportedLabel(message.kind)]) : null,
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
   * Attachments are downloaded from Meta by a background task, so a message can
   * arrive before its file does. The server pushes a message.status event once
   * the download settles, which re-renders this bubble — so the waiting state
   * needs no polling and no retry affordance.
   *
   * The panel is same-origin with the API and the media view is cookie
   * authenticated, so `src` works directly: no fetch, no blob, no header.
   */
  /**
   * "Send again" under a failed outbound message.
   *
   * Only text can be replayed from what the panel holds: a failed attachment's
   * media_id is not in the message payload, so that one has to be re-attached.
   */
  function retryButton(message) {
    if (message.status !== "failed" || message.direction !== "out") return null;
    if (message.kind !== "text" || !message.body) return null;

    return el(
      "button.msg__retry",
      {
        type: "button",
        onclick: async (event) => {
          const button = event.currentTarget;
          button.disabled = true;
          button.textContent = "Sending…";
          const conversation = findConversation(state.activeId);
          if (conversation) await sendText(conversation, message.body);
          button.remove();
        },
      },
      [icon("refresh", { size: 13 }), "Send again"]
    );
  }

  /** Opens the viewer on this image, with the rest of the thread's images loaded. */
  function openImage(message) {
    const images = imagesInThread(state.messages);
    const at = Math.max(0, images.findIndex((i) => String(i.id) === String(message.id)));
    openLightbox(images, at);
  }

  function mediaNode(message) {
    const kind = String(message.kind || "").toLowerCase();
    if (!["image", "audio", "video", "document", "sticker"].includes(kind)) return null;

    if (message.media_failed) {
      return el("div.msg__media-failed", {}, [icon("alert", { size: 15 }), "This attachment is unavailable"]);
    }

    if (!message.media_url) {
      // Outbound attachments are uploaded straight to the gateway and never
      // stored our side, so there is nothing to show back — saying it is still
      // downloading would be plainly wrong. Inbound is the real waiting case.
      if (message.direction === "out") {
        return el("div.msg__sent-media", {}, [
          iconForKind(kind, { size: 15 }) || icon("paperclip", { size: 15 }),
          `${SENT_MEDIA_LABEL[kind] || "File"} sent`,
        ]);
      }
      return el("div.msg__pending", {}, [el("span.spinner.spinner--sm"), "Downloading attachment…"]);
    }

    if (!message.media_ready) {
      return el("div.msg__pending", {}, [el("span.spinner.spinner--sm"), "Downloading attachment…"]);
    }

    if (kind === "image" || kind === "sticker") {
      return el("img.msg__image", {
        src: message.media_url,
        alt: message.media_name || "image",
        loading: "lazy",
        title: "View full size",
        onclick: () => openImage(message),
      });
    }
    // Voice notes arrive as audio/ogg; a plain player is what they need.
    if (kind === "audio") return el("audio.msg__audio", { src: message.media_url, controls: true });

    if (kind === "video") {
      // No poster comes from the API, so preload the metadata — the browser
      // then paints the first frame instead of a black rectangle.
      return el("video.msg__video", { src: message.media_url, controls: true, preload: "metadata" });
    }

    return el("a.msg__doc", { href: message.media_url, target: "_blank", rel: "noopener", download: message.media_name || "" }, [
      el("div.msg__doc-icon", {}, [icon("file", { size: 22 })]),
      el("div.msg__doc-meta", {}, [
        el("div.msg__doc-name", { title: message.media_name || "" }, [message.media_name || "Document"]),
        el("div.msg__doc-sub", {}, [docSubtitle(message)]),
      ]),
      el("div.msg__doc-dl", { title: "Download" }, [icon("download", { size: 17 })]),
    ]);
  }

  const SENT_MEDIA_LABEL = { image: "Photo", sticker: "Sticker", video: "Video", audio: "Audio", document: "Document" };

  const UNSUPPORTED_LABEL = {
    location: "Location sent",
    contacts: "Contact card sent",
    reaction: "Reaction",
    interactive: "Interactive message",
    button: "Button reply",
    system: "System message",
  };

  const unsupportedLabel = (kind) =>
    UNSUPPORTED_LABEL[String(kind || "").toLowerCase()] || `[${kind || "unknown"}]`;

  function docSubtitle(message) {
    const ext = String(message.media_name || "").split(".").pop()?.toUpperCase();
    const size = formatBytes(message.media_size);
    return [ext && ext.length <= 5 ? ext : null, size].filter(Boolean).join(" · ") || "Download";
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
      ui.composer.append(
        el("div.locked", {}, [
          el("div.locked__text", {}, [
            "The 24-hour window is closed, so a free-form message cannot be sent. Sending a template reopens it.",
          ]),
          slots.composer,
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
    try {
      const real = await inbox.send(conversation.id, {
        kind: "text",
        body,
        reply_to_id: replyTo?.id,
      });
      replaceMessage(draft.id, real || { status: "sent" });
    } catch (error) {
      replaceMessage(draft.id, { status: "failed", body: `${body}\n\n⚠ ${error.message}` });
    }
  }

  /* ------------------------------------------------------------- modals */

  async function templatesFor(numberId) {
    if (state.templates.has(numberId)) return state.templates.get(numberId);
    const list = asList(await catalog.templates(numberId), "templates");
    state.templates.set(numberId, list);
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
   * The QR-linked channel, opened inside the panel rather than in a tab.
   *
   * It is a separate service behind /qr/, which nginx will not proxy without a
   * valid admin session — so this is a plain iframe with no token to pass. It
   * is deliberately not part of the inbox: a QR-linked phone is a different
   * kind of channel with different rules, and mixing the two screens would
   * suggest otherwise.
   */
  function openLinkedDevices() {
    const frame = el("iframe.linked-frame", {
      src: "/qr/",
      title: "Linked devices",
      // allow-modals is not decoration: without it a sandboxed frame answers
      // prompt() with null and confirm() with false, immediately and silently.
      // That reads as "the user cancelled", so linking a phone returned before
      // it started and removing one did nothing, with no error either way.
      sandbox: "allow-scripts allow-same-origin allow-forms allow-modals",
    });
    modal("Linked devices", el("div.modal__body.linked-body", {}, [frame]), { wide: true });
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

  function openNewContact() {
    openTemplateComposer({
      mode: "new",
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
              `${agent.display_name || agent.username} ${isCurrent ? "(Current)" : ""}`,
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
        await inbox.assign(conversation.id, { agent_id: selectedId, reason: reason.value.trim() || undefined });
        dialog.close();
        await loadConversations();
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

  function connectSocket() {
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

    socket.connect();
    window.addEventListener("beforeunload", () => socket.close());
  }

  // Events carry whole objects, not ids, so the panel renders them directly
  // instead of refetching the list on every inbound message.
  function handleEvent(event, data) {
    if (event === "ready") return;
    if (event === "message.new") return onMessageNew(data);
    if (event === "message.status") return onMessageStatus(data.message);
    if (event === "conversation.updated" || event === "conversation.assigned") {
      return onConversationChanged(data.conversation);
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

  /** Inserts or replaces a conversation, keeping the list newest-activity-first. */
  function upsertConversation(conversation) {
    if (!conversation) return;
    // A filtered-out number must not silently reappear in the list.
    if (state.numberFilter && String(conversation.number_id) !== String(state.numberFilter)) return;

    const index = state.conversations.findIndex((c) => c.id === conversation.id);
    if (index === -1) state.conversations.unshift(conversation);
    else state.conversations[index] = conversation;

    state.conversations.sort(
      (a, b) => new Date(b.last_message_at || 0) - new Date(a.last_message_at || 0)
    );
    renderConversations();
    ui.listStatus.textContent = state.conversations.length ? "" : "No conversations.";
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

    upsertConversation(conversation);
    if (active) {
      renderThreadHeader(conversation);
      renderComposer(conversation);
    }
  }

  function onMessageStatus(message) {
    if (!message || message.conversation_id !== state.activeId) return;
    replaceMessageById(message);
  }

  function onConversationChanged(conversation) {
    upsertConversation(conversation);
    if (conversation?.id === state.activeId) {
      // Assignment or an expiring window changes what the composer may do.
      renderThreadHeader(conversation);
      renderComposer(conversation);
    }
  }

  return boot();
}
