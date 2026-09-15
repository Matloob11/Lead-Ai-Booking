import { useState, useEffect, useCallback, useRef, useMemo, useLayoutEffect } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useLocation } from 'react-router-dom';
import { Trans, useTranslation } from 'react-i18next';
import { nextReconnectState } from '../utils/reconnectState';
import { applyIncomingToChatList } from '../utils/chatList';
import { filterChats, filterChannels, groupStatusesByContact, chatMatchesPhone, digitsOnly } from '../utils/chatFilters';
import { ArrowLeft, Loader2, Megaphone, CircleDashed, AlertCircle, MessageSquare, ExternalLink } from 'lucide-react';
import { useProfilePicture } from '../hooks/useProfilePicture';
import { useProfilePictures } from '../hooks/useProfilePictures';
import { useResolvedPhone } from '../hooks/useResolvedPhone';
import { formatPhoneForDisplay } from '../utils/formatPhone';
import {
  sessionApi,
  messageApi,
  conversationHealthApi,
  chatProfileApi,
  asMessageType,
  ALL_CHATS_SESSION_ID,
  // A7: the sidebar search box now looks inside messages too, not just chat names.
  searchApi,
  type Session,
  type Chat,
  type ChatKind,
  type Channel,
  type SearchHit,
  type ContactStatusGroup,
} from '../services/api';
import {
  applyMessageEdit,
  mergeDeliveryStatus,
  findRevokedIndex,
  getMediaSrc,
  type ChatMessageView,
  type MessageMedia,
} from '../utils/chatMessages';
import { useWebSocket } from '../hooks/useWebSocket';
import { useDocumentTitle } from '../hooks/useDocumentTitle';
import { useToast } from '../hooks/useToast';
import { PageHeader } from '../components/PageHeader';
import { ConversationHealthPanel } from '../components/ConversationHealthPanel';
import { useAppMenu } from '../hooks/useAppMenu';
// A7: shared with what used to be the corner search box — it turns a typed query
// into the API's params, and returns null for one too short to be worth sending.
import { buildSearchParams } from '../utils/search-highlight';
import { useChatMessages, useChatMessagesActions, messagesQueryKey } from '../hooks/useChatMessages';
import { useChannelMessages } from '../hooks/useChannelMessages';
import { useContactStatuses } from '../hooks/useContactStatuses';
import { useChatScrollPosition } from '../hooks/useChatScrollPosition';
import { useCurrentEngineQuery } from '../hooks/queries';
import { useRole } from '../hooks/useRole';
import { createTrailingCoalescer } from '../utils/trailingCoalescer';
import MessageBody from '../components/chats/MessageBody';
import MediaLightbox, { type LightboxItem } from '../components/chats/MediaLightbox';
import KindIcon from '../components/chats/KindIcon';
import ChatSidebar from '../components/chats/ChatSidebar';
import ChatThread from '../components/chats/ChatThread';
import ChatComposer, { type StagedAttachment } from '../components/chats/ChatComposer';
import StatusMedia from '../components/chats/StatusMedia';
import StatusComposeModal from '../components/chats/StatusComposeModal';
// A7: the agent's two sidebar actions — reaching a new number, and their own figures.
import NewContactModal from '../components/chats/NewContactModal';
import AgentProfileModal from '../components/chats/AgentProfileModal';
import ContactProfilePanel from '../components/chats/ContactProfilePanel';
import './Chats.css';

// Quiet window for coalescing mark-as-read RPCs (see markReadCoalescer below).
const MARK_READ_DEBOUNCE_MS = 750;

// mergeDeliveryStatus (forward-only delivery-tick merge) is shared with mergeOrAppend in utils/chatMessages
// so the WS append path and the ack path apply the exact same rule.

interface IncomingWsMessage {
  id: string;
  chatId: string;
  from: string;
  to: string;
  body: string;
  type: string;
  timestamp: number;
  fromMe?: boolean;
  media?: MessageMedia;
  quotedMessage?: { id: string; body: string };
  // The backend emits `call` as a top-level field on the live `message.received` event (it's only
  // folded into `metadata` on the persisted/history path), so declare it here to carry it through.
  call?: { video: boolean; missed: boolean };
  metadata?: ChatMessageView['metadata'];
  kind?: ChatKind;
  /** Group poster: `from` is the group JID, so `contact`/`author` identify who actually sent it. */
  contact?: { id?: string; name?: string; pushName?: string };
  author?: string;
}

// WhatsApp's text-status font slots — the current wire enum is {0,1,2,6,7,8,9,10} (6 is the bold
// system face); 3–5 are legacy slots older clients still emit. Approximated with generic
// families/weights since the actual faces are proprietary; slot 0 and unknown slots keep the UI
// default.
const STATUS_FONT: Record<number, { family?: string; weight?: number }> = {
  1: { family: 'serif' },
  2: { family: 'cursive' },
  3: { family: 'fantasy' }, // legacy
  4: { family: 'serif' }, // legacy
  5: { family: 'ui-rounded, system-ui, sans-serif' }, // legacy
  6: { weight: 700 },
  7: { family: 'cursive' },
  8: { family: 'serif' },
  9: { family: 'sans-serif', weight: 800 },
  10: { family: 'monospace', weight: 700 },
};

/** Inline style for a status item's font slot; {} when unstyled/unknown. */
const statusFontStyle = (font?: number): { fontFamily?: string; fontWeight?: number } => {
  if (font === undefined) return {};
  const slot = STATUS_FONT[font];
  if (!slot) return {};
  return {
    ...(slot.family ? { fontFamily: slot.family } : {}),
    ...(slot.weight ? { fontWeight: slot.weight } : {}),
  };
};

export function Chats() {
  const { t } = useTranslation();
  useDocumentTitle(t('nav.chats'));
  const location = useLocation();
  const { error: showErrorToast, warning: showWarningToast } = useToast();
  const { isAdmin } = useRole();

  // Sessions list & active session
  const [sessions, setSessions] = useState<Session[]>([]);
  const [selectedSessionId, setSelectedSessionId] = useState<string>('');
  const [loadingSessions, setLoadingSessions] = useState<boolean>(true);
  // A7: the sessions held back from the list above because their history is still importing. Kept
  // apart from `sessions` rather than mixed in: a half-imported chat list is worse than none, but
  // "connect a session first" is the wrong thing to tell somebody whose phone is plainly connected.
  const [importingSessions, setImportingSessions] = useState<Session[]>([]);

  // Chats list
  const [chats, setChats] = useState<Chat[]>([]);
  const [loadingChats, setLoadingChats] = useState<boolean>(false);
  const [searchQuery, setSearchQuery] = useState<string>('');
  // A7: what the same box found inside the messages. Chat names match locally and
  // instantly; these arrive from the server a moment later and render beneath.
  const [messageHits, setMessageHits] = useState<SearchHit[]>([]);
  const [messageHitsLoading, setMessageHitsLoading] = useState<boolean>(false);

  // Selected chat & message history
  const [activeChat, setActiveChat] = useState<Chat | null>(null);
  const [activeChannel, setActiveChannel] = useState<Channel | null>(null);
  // Only the contact id is state — the open group is derived from groupedStatuses at render, so a
  // refetch (window focus, post-compose) flows straight into the open viewer instead of leaving it
  // pinned to the snapshot captured at click time. A group that disappears (all items expired)
  // simply closes the viewer.
  const [activeStatusContactId, setActiveStatusContactId] = useState<string | null>(null);

  // Chats/Channels/Status tab selection. Switching tabs closes whatever conversation is open so a
  // press on another tab doesn't leave a Chats-tab room rendered underneath a Channels/Status list.
  const [activeTab, setActiveTab] = useState<'chats' | 'channels' | 'status'>('chats');
  const switchTab = useCallback((tab: 'chats' | 'channels' | 'status') => {
    setActiveTab(tab);
    setActiveChat(null);
    setActiveChannel(null);
    setActiveStatusContactId(null);
  }, []);

  // Channels tab: only whatsapp-web.js implements channel listing/reading — Baileys throws 501 for
  // both, so the query is gated off entirely (never fired) rather than left to fail per-request.
  const currentEngine = useCurrentEngineQuery();
  const channelsSupported = currentEngine.data?.engineType === 'whatsapp-web.js';
  const channelsQuery = useQuery({
    queryKey: ['channels', selectedSessionId],
    queryFn: () => sessionApi.getSubscribedChannels(selectedSessionId!),
    enabled: Boolean(selectedSessionId) && channelsSupported && activeTab === 'channels',
  });
  const channelMessages = useChannelMessages(selectedSessionId, activeChannel?.id ?? null);

  // Status tab: both engines expose stored status content, so this query isn't engine-gated (unlike
  // channelsQuery above) — but it is tab-gated the same way, so selecting a session on another tab
  // doesn't fire a background /status fetch nobody is looking at.
  const statusesQuery = useContactStatuses(selectedSessionId, activeTab === 'status');

  // A channel feed opens at its newest post, mirroring the chat room's initial scroll. The pane is
  // also keyed by channel id, so switching channels remounts the feed instead of reusing the DOM
  // (and its stale scroll offset) of the previous channel.
  const channelFeedRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const el = channelFeedRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [activeChannel?.id, channelMessages.data]);

  // --- Status compose modal ---
  // The page owns only the open flag (its trigger sits in the sidebar header below); the form
  // itself — state, contacts query, submit — is components/chats/StatusComposeModal.
  const [composeOpen, setComposeOpen] = useState<boolean>(false);
  // A7: the two sidebar actions. Both are dialogs rather than routes — an agent
  // opening either is stepping aside from a conversation, not leaving it.
  const [newContactOpen, setNewContactOpen] = useState<boolean>(false);
  const [newContactPhone, setNewContactPhone] = useState<string>('');
  const [profileOpen, setProfileOpen] = useState<boolean>(false);
  const [healthOpen, setHealthOpen] = useState<boolean>(false);
  /** Customer contact card (right drawer) — distinct from the agent's own Profile modal. */
  const [contactPanelOpen, setContactPanelOpen] = useState(false);
  const { registerChatsActions } = useAppMenu();

  // App dropdown (pic-1) calls these — Conversation Health (admin) / New contact / Profile.
  useEffect(() => {
    registerChatsActions({
      onNewContact: () => setNewContactOpen(true),
      onOpenProfile: () => setProfileOpen(true),
      onOpenHealth: () => {
        if (isAdmin) setHealthOpen(true);
      },
    });
    return () => registerChatsActions(null);
  }, [registerChatsActions, isAdmin]);

  useEffect(() => {
    if (!isAdmin && healthOpen) setHealthOpen(false);
  }, [isAdmin, healthOpen]);
  // The whole row, not just its id: one dialog reads the linked number's country
  // to make sense of a local number, the other names the phone it is reporting on.
  const allChatsMode = selectedSessionId === ALL_CHATS_SESSION_ID;
  const selectedSession = allChatsMode
    ? null
    : (sessions.find(s => s.id === selectedSessionId) ?? null);
  // All-chats rows carry their own sessionId; single-session mode uses the picker.
  const threadSessionId = activeChat?.sessionId || (allChatsMode ? '' : selectedSessionId);

  const {
    data: messages = [],
    isLoading: loadingMessages,
    isError: messagesError,
  } = useChatMessages(threadSessionId, activeChat?.id ?? null);
  const { appendMessage, updateMessage, loadMessageMedia } = useChatMessagesActions();
  const queryClient = useQueryClient();

  // Lightbox state for media viewer
  const [lightboxIndex, setLightboxIndex] = useState<number | null>(null);

  const [replyingTo, setReplyingTo] = useState<ChatMessageView | null>(null);
  // Draft text lives here (not in ChatComposer) so it survives closing/switching the room.
  const [messageInput, setMessageInput] = useState<string>('');
  // The staged attachment lives here for the same reason the draft text does — ChatComposer
  // unmounts when the room closes, which would silently discard a picked file. Unlike the text
  // draft it is dropped when a DIFFERENT chat is opened (see the effect below): a file that
  // follows the user into another conversation can be sent to the wrong recipient.
  const [attachment, setAttachment] = useState<StagedAttachment | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);

  // Revoke the object URL created for an image-attachment preview once it is replaced or cleared.
  // The cleanup runs with the previous value on every change, so this single effect covers all
  // paths (new file, remove, send, chat switch) — otherwise each preview leaks a blob held for the
  // lifetime of the document. It lives here, not in ChatComposer: revoking on the composer's
  // unmount would hand a reopened room a dead blob URL for an attachment that is still staged.
  useEffect(() => {
    if (!previewUrl) return;
    return () => URL.revokeObjectURL(previewUrl);
  }, [previewUrl]);

  // Drop a staged attachment when the user moves to a DIFFERENT chat. Closing the room
  // (`activeChat` → null) deliberately keeps it, so close/reopen is a lossless round trip; only an
  // actual change of conversation clears. The composer invalidates its in-flight FileReader on the
  // same transition, so a late read cannot re-stage the file against the new chat.
  const lastRoomIdRef = useRef<string | null>(null);
  useEffect(() => {
    const current = activeChat?.id ?? null;
    if (current === null) return;
    const previous = lastRoomIdRef.current;
    lastRoomIdRef.current = current;
    if (previous === null || previous === current) return;
    setAttachment(null);
    setPreviewUrl(null);
  }, [activeChat]);

  // Per-chat scroll-position memory + auto-scroll heuristic.
  // Pass `messages.length > 0` as the loaded signal: it stays stable once the
  // chat has any message (doesn't toggle per append) and covers both the
  // first-fetch resolution and a WS-driven first message on a previously-empty
  // chat. `loadingMessages` alone would miss the latter case.
  const {
    containerRef: messagesContainerRef,
    onMessageAppended,
    onMediaLoad,
  } = useChatScrollPosition(activeChat?.id ?? null, messages.length > 0);

  // Batch profile-picture fetch for the visible chat list — ONE request for the whole sidebar
  // (per-row queries burst the per-IP throttle into 429s). Sorted-key cached 1h; rows fall back
  // to the generic icon for ids that resolve null.
  const chatIds = useMemo(() => chats.map(c => c.id), [chats]);
  const listPics = useProfilePictures(allChatsMode ? undefined : selectedSessionId || undefined, chatIds);

  // Profile-picture fetch for the active room (cached 1h by useProfilePicture; TanStack Query
  // dedupes, so other components querying the same key share this slice).
  const activePp = useProfilePicture(threadSessionId || undefined, activeChat?.id);

  // Header phone line. Local formatting handles @c.us ids offline; for anything else personal
  // (notably @lid privacy ids, which are NOT phones and must never be formatted as one) resolve
  // the real number through the engine — cached a day, and only fired when local formatting failed.
  const activePhoneDisplay = activeChat ? formatPhoneForDisplay(activeChat.id) : null;
  const needsPhoneResolution = Boolean(activeChat && activeChat.kind === 'individual' && !activePhoneDisplay);
  const resolvedPhoneQ = useResolvedPhone(
    needsPhoneResolution ? threadSessionId || undefined : undefined,
    needsPhoneResolution ? activeChat?.id : undefined,
  );
  const activePhoneText =
    activePhoneDisplay ?? (resolvedPhoneQ.data ? formatPhoneForDisplay(resolvedPhoneQ.data) : null);

  const chatLeadQ = useQuery({
    queryKey: ['chat-lead', threadSessionId, activeChat?.id],
    queryFn: () => conversationHealthApi.getChatLead(threadSessionId!, activeChat!.id),
    enabled: Boolean(threadSessionId && activeChat?.id && !activeChat.isGroup),
    staleTime: 60_000,
    retry: false,
  });
  const chatLead =
    chatLeadQ.data && 'bitrixLeadId' in chatLeadQ.data && chatLeadQ.data.bitrixLeadId
      ? chatLeadQ.data
      : null;

  // Deep-link from Conversation Health list: open a specific session + chat.
  useEffect(() => {
    const state = location.state as { openSessionId?: string; openChatId?: string } | null;
    if (!state?.openSessionId || !state?.openChatId) return;
    setSelectedSessionId(state.openSessionId);
    const chatId = state.openChatId;
    void sessionApi
      .getChats(state.openSessionId)
      .then(list => {
        const found = list.find(c => c.id === chatId);
        if (found) setActiveChat({ ...found, sessionId: state.openSessionId });
      })
      .catch(() => undefined);
  }, [location.state]);

  // Deep-link from Bitrix CRM tab: /chats?phone=971… (also sessionStorage + postMessage).
  const pendingPhoneRef = useRef<string | null>(null);
  useEffect(() => {
    const fromQuery = digitsOnly(new URLSearchParams(location.search).get('phone') || '');
    const fromStore = digitsOnly(sessionStorage.getItem('openwa_open_phone') || '');
    const phone = fromQuery.length >= 8 ? fromQuery : fromStore.length >= 8 ? fromStore : '';
    if (phone) pendingPhoneRef.current = phone;
  }, [location.search]);

  useEffect(() => {
    const trusted = new Set([
      window.location.origin,
      'https://wa.srv1802669.hstgr.cloud',
      ...(import.meta.env.DEV ? ['http://localhost:5173', 'http://127.0.0.1:5173'] : []),
    ]);
    const onMessage = (event: MessageEvent) => {
      if (!trusted.has(event.origin)) return;
      if (!event.data || typeof event.data !== 'object') return;
      if (event.data.type !== 'openwa_open_phone') return;
      const phone = digitsOnly(String(event.data.phone || ''));
      if (phone.length < 8) return;
      pendingPhoneRef.current = phone;
      sessionStorage.setItem('openwa_open_phone', phone);
      setSearchQuery(phone);
    };
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, []);

  useEffect(() => {
    const phone = pendingPhoneRef.current;
    if (!phone || phone.length < 8) return;
    if (loadingChats || loadingSessions) return;
    if (!selectedSessionId && !isAdmin) return;

    const clearPending = () => {
      sessionStorage.removeItem('openwa_open_phone');
      pendingPhoneRef.current = null;
    };

    const openFound = (found: Chat, sessionId: string) => {
      setSelectedSessionId(sessionId === ALL_CHATS_SESSION_ID ? ALL_CHATS_SESSION_ID : sessionId);
      setActiveChat({ ...found, sessionId: found.sessionId || sessionId });
      setSearchQuery(phone);
      setActiveTab('chats');
      clearPending();
    };

    const openNewContact = () => {
      const sid =
        selectedSessionId && selectedSessionId !== ALL_CHATS_SESSION_ID
          ? selectedSessionId
          : sessions[0]?.id || '';
      if (!sid) {
        setSearchQuery(phone);
        clearPending();
        return;
      }
      setSelectedSessionId(sid);
      setActiveTab('chats');
      setNewContactPhone(phone);
      setNewContactOpen(true);
      clearPending();
    };

    const local = chats.find(c => chatMatchesPhone(c, phone));
    if (local) {
      openFound(local, local.sessionId || selectedSessionId);
      return;
    }

    // Still loading this session's list — wait for the next paint.
    if (loadingChats) return;

    // Admin: scan All chats once if the current session list missed it.
    if (isAdmin) {
      let cancelled = false;
      void sessionApi
        .getAllChats()
        .then(list => {
          if (cancelled) return;
          const found = list.find(c => chatMatchesPhone(c, phone));
          if (found) openFound(found, found.sessionId || ALL_CHATS_SESSION_ID);
          else openNewContact();
        })
        .catch(() => openNewContact());
      return () => {
        cancelled = true;
      };
    }

    // Agent: no matching chat on their session → new contact form.
    openNewContact();
  }, [chats, selectedSessionId, loadingChats, loadingSessions, isAdmin, sessions]);

  // 1. Fetch available connected sessions.
  //
  // A7: hoisted out of the mount effect so the poll below can reuse it. A session held back for an
  // import is not permanently unusable — it becomes usable the moment the import finishes, and
  // without a second look this screen would sit on an empty state until somebody reloaded the page.
  const loadSessions = useCallback(
    async (quiet = false) => {
      try {
        if (!quiet) setLoadingSessions(true);
        const list = await sessionApi.list();
        const isSynced = (s: Session) =>
          s.syncProgress === undefined || s.syncProgress === null || s.syncProgress >= 100;
        // Soft-removed sessions stay out of the picker — All chats (admin) still lists them.
        const activeList = list.filter(s => !s.removedAt);
        const readySessions = activeList.filter(s => s.status === 'ready' && isSynced(s));
        setImportingSessions(activeList.filter(s => s.status === 'ready' && !isSynced(s)));

        // A7: a number that is not connected still has its conversations in our
        // own tables, and the server now answers the chat list from those when no
        // engine is loaded. Leaving those sessions out of the picker was the last
        // thing keeping them off the screen — a phone going offline took months of
        // history with it, which is the opposite of why any of it is stored.
        //
        // Live ones first so the common case is still the top of the list, and
        // offline ones after, labelled. Read-only over there: no unread counts, no
        // presence, and sending stays unavailable because that needs the handset.
        const offlineSessions = activeList
          .filter(s => s.status !== 'ready')
          .map(s => ({ ...s, name: `${s.name} (offline)` }));
        setSessions([...readySessions, ...offlineSessions]);
        // Functional: a poll must not pull the selection back to the first session while an agent
        // is reading a different one. Only an empty selection is filled in.
        // Keep admin All chats selection stable across quiet polls.
        setSelectedSessionId(current => {
          if (current === ALL_CHATS_SESSION_ID) return current;
          if (current && [...readySessions, ...offlineSessions].some(s => s.id === current)) return current;
          return readySessions[0]?.id || offlineSessions[0]?.id || (isAdmin ? ALL_CHATS_SESSION_ID : '');
        });
      } catch (err) {
        if (!quiet) showErrorToast(t('chats.errors.loadSessions'), err instanceof Error ? err.message : undefined);
      } finally {
        if (!quiet) setLoadingSessions(false);
      }
    },
    [t, showErrorToast, isAdmin],
  );

  useEffect(() => {
    void loadSessions();
  }, [loadSessions]);

  // A7: an import raises no status transition, so nothing already on this screen would ever learn
  // that it finished. Poll only while one is running, and stop the moment none is — quietly, so a
  // failed poll does not throw a toast at somebody who is just waiting.
  useEffect(() => {
    if (importingSessions.length === 0) return;
    const timer = setInterval(() => {
      void loadSessions(true);
    }, 5000);
    return () => clearInterval(timer);
  }, [importingSessions.length, loadSessions]);

  // 2. Fetch chats when active session changes
  const loadChats = useCallback(
    async (sessionId: string) => {
      if (!sessionId) return;
      try {
        setLoadingChats(true);
        const data =
          sessionId === ALL_CHATS_SESSION_ID ? await sessionApi.getAllChats() : await sessionApi.getChats(sessionId);
        let sorted = [...data].sort((a, b) => (b.timestamp || 0) - (a.timestamp || 0));
        // Overlay team-local display names + pins (contact panel) onto the engine list.
        if (sessionId !== ALL_CHATS_SESSION_ID) {
          try {
            const { names, pinned } = await chatProfileApi.listNames(sessionId);
            const pinnedSet = new Set(pinned || []);
            sorted = sorted.map(chat => ({
              ...chat,
              name: names[chat.id] || chat.name,
              teamPinned: pinnedSet.has(chat.id),
            }));
            sorted.sort((a, b) => {
              const pin = Number(Boolean(b.teamPinned)) - Number(Boolean(a.teamPinned));
              if (pin !== 0) return pin;
              return (b.timestamp || 0) - (a.timestamp || 0);
            });
          } catch {
            // Profile names are optional polish — a failed overlay must not blank the list.
          }
        }
        setChats(sorted);
      } catch (err) {
        showErrorToast(t('chats.errors.loadChats'), err instanceof Error ? err.message : undefined);
        setChats([]);
      } finally {
        setLoadingChats(false);
      }
    },
    [t, showErrorToast],
  );

  const handleSelectChat = useCallback(
    (chat: Chat) => {
      if (chat.canOpenThread === false) {
        showWarningToast('Removed session', 'History stays in the list; open the thread after reconnecting.');
        setActiveChat(null);
        setContactPanelOpen(false);
        return;
      }
      setActiveChat(chat);
      setContactPanelOpen(false);
    },
    [showWarningToast],
  );

  useEffect(() => {
    if (selectedSessionId) {
      void loadChats(selectedSessionId);
      setActiveChat(null);
      setActiveChannel(null);
      setActiveStatusContactId(null);
      // A staged attachment belongs to a chat in the session being left, so it is dropped here
      // rather than carried across — the close/reopen round trip that preserves it is scoped to a
      // single session. Clearing previewUrl runs the revoke effect's cleanup; the composer
      // unmounts with the closed room and invalidates its own in-flight FileReader.
      setAttachment(null);
      setPreviewUrl(null);
      lastRoomIdRef.current = null;
    }
  }, [selectedSessionId, loadChats]);

  // Coalesce mark-as-read RPCs per chat: every incoming message in the visible chat raises a
  // read event, and a per-event POST sprays the gateway into 429s. One trailing call per chat
  // after a quiet window carries the same effect.
  const markReadCoalescer = useMemo(
    () =>
      createTrailingCoalescer<string>(chatId => {
        const sid = threadSessionId;
        if (!sid || sid === ALL_CHATS_SESSION_ID) return;
        void sessionApi.markChatRead(sid, chatId).catch(err => {
          showWarningToast(t('chats.errors.markRead'), err instanceof Error ? err.message : undefined);
        });
      }, MARK_READ_DEBOUNCE_MS),
    [threadSessionId, t, showWarningToast],
  );

  // Flush pending trailing calls on unmount / session switch: the mark-as-read POST is
  // fire-and-forget (a failure only raises a warning toast), so firing on the way out is safe —
  // and dropping the pending call would leave the last messages of a quickly-exited chat unread.
  // The flush closure still references the PREVIOUS session on a session switch, which is exactly
  // where those queued reads belong.
  useEffect(() => () => markReadCoalescer.flush(), [markReadCoalescer]);

  const markChatRead = useCallback(
    (chatId: string) => {
      markReadCoalescer.call(chatId);
    },
    [markReadCoalescer],
  );

  // 3. WebSocket integration for real-time messages
  const handleIncomingMessage = useCallback(
    (event: { sessionId: string; message: Record<string, unknown> }) => {
      if (event.sessionId !== selectedSessionId) return;

      const newMsg = event.message as unknown as IncomingWsMessage;

      const mappedMessage: ChatMessageView = {
        id: newMsg.id,
        waMessageId: newMsg.id,
        chatId: newMsg.chatId,
        // For a group post `from` is the group JID, so the sender's name is carried on `contact`.
        // Persisted rows keep the same value in `chatName`; normalize both to one field for the thread.
        chatName: newMsg.contact?.pushName ?? newMsg.contact?.name,
        author: newMsg.author,
        from: newMsg.from,
        to: newMsg.to,
        body: newMsg.body,
        type: asMessageType(newMsg.type),
        direction: newMsg.fromMe ? 'outgoing' : 'incoming',
        status: 'sent',
        timestamp: newMsg.timestamp,
        createdAt: new Date(newMsg.timestamp * 1000).toISOString(),
        metadata: newMsg.metadata || {
          media: newMsg.media,
          quotedMessage: newMsg.quotedMessage,
          call: newMsg.call,
        },
        kind: newMsg.kind,
      };

      // Always write to the React Query cache for this message's session — keeps non-active chats
      // up to date so re-opening them shows fresh data without a refetch.
      appendMessage(event.sessionId, newMsg.chatId, mappedMessage);

      // If the message belongs to the currently visible chat, mark-as-read and run the scroll heuristic.
      if (activeChat && newMsg.chatId === activeChat.id) {
        markChatRead(activeChat.id);
        if (!newMsg.fromMe) onMessageAppended('incoming');
      }

      // Update sidebar chat list. The refetch is REPORTED by the reducer and fired below, never from
      // inside the updater: React double-invokes updaters under StrictMode, so a side effect in there
      // ran twice for every message arriving in a chat the sidebar does not have.
      let needsSidebarRefetch = false;
      setChats(prevChats => {
        const result = applyIncomingToChatList(prevChats, newMsg, {
          activeChatId: activeChat?.id,
          // A location message's body is the (multi-KB) base64 map thumbnail; show a label instead.
          locationLabel: `📍 ${t('chats.media.location')}`,
        });
        needsSidebarRefetch = result.needsSidebarRefetch;
        return result.chats;
      });
      if (needsSidebarRefetch) {
        void loadChats(selectedSessionId);
      }
    },
    [selectedSessionId, activeChat, loadChats, markChatRead, appendMessage, onMessageAppended, t],
  );

  const handleIncomingMessageAck = useCallback(
    (event: { sessionId: string; messageId: string; status: ChatMessageView['status'] }) => {
      if (event.sessionId !== selectedSessionId) return;

      // Acks can arrive for any cached chat under this session. Walk every cache entry under
      // ['messages', event.sessionId, *] and apply the forward-only delivery merge in place.
      const caches = queryClient.getQueriesData<ChatMessageView[]>({
        queryKey: ['messages', event.sessionId],
      });
      for (const [key, list] of caches) {
        if (!list) continue;
        const idx = list.findIndex(m => m.id === event.messageId || m.waMessageId === event.messageId);
        if (idx === -1) continue;
        const target = list[idx];
        // Backend now sends the neutral delivery status directly (no engine-specific ack codes).
        // Merge forward-only so an out-of-order/replayed lower ack can't downgrade the tick.
        const nextStatus = mergeDeliveryStatus(target.status, event.status) ?? target.status;
        const next = list.slice();
        next[idx] = { ...target, status: nextStatus };
        queryClient.setQueryData(key, next);
      }
    },
    [selectedSessionId, queryClient],
  );

  const handleIncomingMessageReaction = useCallback(
    (event: { sessionId: string; messageId: string; reactions: Record<string, string> }) => {
      if (event.sessionId !== selectedSessionId) return;

      // Reactions update `metadata.reactions` while preserving `metadata.media` / `metadata.quotedMessage`,
      // so we must read the prior message and deep-merge — `updateMessage`'s shallow merge would clobber
      // the rest of metadata.
      const caches = queryClient.getQueriesData<ChatMessageView[]>({
        queryKey: ['messages', event.sessionId],
      });
      for (const [key, list] of caches) {
        if (!list) continue;
        const idx = list.findIndex(m => m.id === event.messageId || m.waMessageId === event.messageId);
        if (idx === -1) continue;
        const target = list[idx];
        const next = list.slice();
        next[idx] = {
          ...target,
          metadata: { ...(target.metadata || {}), reactions: event.reactions },
        };
        queryClient.setQueryData(key, next);
      }
    },
    [selectedSessionId, queryClient],
  );

  const handleIncomingMessageRevoked = useCallback(
    (event: { sessionId: string; id: string; revokedId?: string; type: string }) => {
      if (event.sessionId !== selectedSessionId) return;

      // Walk every cached chat under this session, find the deleted message and zero it — the
      // backend emits an empty body; the localized "deleted" label is rendered below. Matching is
      // in findRevokedIndex: the event carries two candidate ids and wwebjs's `id` alone can miss.
      const caches = queryClient.getQueriesData<ChatMessageView[]>({
        queryKey: ['messages', event.sessionId],
      });
      for (const [key, list] of caches) {
        if (!list) continue;
        const idx = findRevokedIndex(list, event);
        if (idx === -1) continue;
        const target = list[idx];
        const next = list.slice();
        next[idx] = { ...target, body: '', type: asMessageType(event.type) };
        queryClient.setQueryData(key, next);
      }
    },
    [selectedSessionId, queryClient],
  );

  const handleIncomingMessageEdited = useCallback(
    (event: { sessionId: string; messageId: string; chatId: string; body: string }) => {
      if (event.sessionId !== selectedSessionId) return;

      const caches = queryClient.getQueriesData<ChatMessageView[]>({
        queryKey: ['messages', event.sessionId],
      });
      let matchedCachedMessage = false;
      let editedLastMessage = false;
      for (const [key, list] of caches) {
        if (!list) continue;
        const next = applyMessageEdit(list, event);
        if (next === list) continue;
        matchedCachedMessage = true;
        queryClient.setQueryData(key, next);

        // Message caches are chronological; only editing the final row changes the sidebar preview.
        // Confirm the cache belongs to the event chat before touching that summary.
        const cachedChatId = Array.isArray(key) && typeof key[2] === 'string' ? key[2] : undefined;
        const editedIndex = list.findIndex(m => m.id === event.messageId || m.waMessageId === event.messageId);
        if (cachedChatId === event.chatId && editedIndex === list.length - 1) editedLastMessage = true;
      }
      if (editedLastMessage) {
        setChats(previous =>
          previous.map(chat => (chat.id === event.chatId ? { ...chat, lastMessage: event.body } : chat)),
        );
      } else if (!matchedCachedMessage) {
        // The chat may never have been opened, so there is no message cache from which to prove
        // whether this was its latest row. Refresh summaries instead of guessing and overwriting the
        // sidebar with the body of an older edited message.
        void loadChats(selectedSessionId);
      }
    },
    [selectedSessionId, queryClient, loadChats],
  );

  // A contact's new story lands here instead of in the message pipeline; invalidate the statuses
  // query so the Status tab refetches live. A disabled query (another tab active) just goes stale
  // and refetches on open — no background fetch either way.
  const handleStatusReceived = useCallback(
    (event: { sessionId: string }) => {
      queryClient.invalidateQueries({ queryKey: ['contact-statuses', event.sessionId] });
    },
    [queryClient],
  );

  const { isConnected, connectionFailed, reconnect, subscribe, unsubscribe } = useWebSocket({
    onMessage: handleIncomingMessage,
    onMessageAck: handleIncomingMessageAck,
    onMessageReaction: handleIncomingMessageReaction,
    onMessageRevoked: handleIncomingMessageRevoked,
    onMessageEdited: handleIncomingMessageEdited,
    onStatusReceived: handleStatusReceived,
  });

  // A transient WebSocket gap means message.received/ack/revoke events were missed, and the chat
  // cache uses staleTime: Infinity so it won't refetch on its own. On a reconnect (isConnected
  // false→true after a prior connect), invalidate the active session's messages so the thread the
  // gap left stale refreshes. The transition logic is unit-tested in utils/reconnectState.
  const reconnectHadConnected = useRef(false);
  const reconnectWasDisconnected = useRef(false);
  useEffect(() => {
    const decision = nextReconnectState({
      isConnected,
      hadConnected: reconnectHadConnected.current,
      wasDisconnected: reconnectWasDisconnected.current,
    });
    reconnectHadConnected.current = decision.hadConnected;
    reconnectWasDisconnected.current = decision.wasDisconnected;
    if (decision.invalidate) {
      queryClient.invalidateQueries({ queryKey: ['messages', selectedSessionId] });
      // Statuses are live now (status.received): a story posted during the socket gap would
      // otherwise stay invisible until a focus refetch.
      queryClient.invalidateQueries({ queryKey: ['contact-statuses', selectedSessionId] });
    }
  }, [isConnected, selectedSessionId, queryClient]);

  useEffect(() => {
    if (selectedSessionId && isConnected) {
      subscribe(selectedSessionId, [
        'message.received',
        'message.sent',
        'message.ack',
        'message.reaction',
        'message.revoked',
        'message.edited',
        'status.received',
      ]);
      return () => {
        unsubscribe(selectedSessionId);
      };
    }
  }, [selectedSessionId, isConnected, subscribe, unsubscribe]);

  // 4. Message history is fetched by useChatMessages (React Query). The active-chat side effects
  // (mark-as-read + clear sidebar unread badge) live in a small effect below.

  const handleReactMessage = async (msg: ChatMessageView, emoji: string) => {
    if (!threadSessionId || !activeChat) return;

    const msgId = msg.waMessageId || msg.id;
    const currentReactions = msg.metadata?.reactions || {};
    const sessionPhone = sessions.find(s => s.id === threadSessionId)?.phone || 'me';

    let alreadyReacted = false;
    for (const [sender, emo] of Object.entries(currentReactions)) {
      if ((sender === 'me' || sender.includes(sessionPhone)) && emo === emoji) {
        alreadyReacted = true;
        break;
      }
    }

    const emojiToSend = alreadyReacted ? '' : emoji;

    try {
      await messageApi.react(threadSessionId, {
        chatId: activeChat.id,
        messageId: msgId,
        emoji: emojiToSend,
      });

      // Deep-merge metadata.reactions so existing media / quotedMessage on metadata survive.
      const key = messagesQueryKey(threadSessionId, activeChat.id);
      queryClient.setQueryData<ChatMessageView[]>(key, (old = []) =>
        old.map(m => {
          if (m.id === msg.id || m.waMessageId === msg.id) {
            const metadata = m.metadata || {};
            const reactions = { ...(metadata.reactions || {}) };
            if (emojiToSend === '') {
              delete reactions['me'];
            } else {
              reactions['me'] = emojiToSend;
            }
            return { ...m, metadata: { ...metadata, reactions } };
          }
          return m;
        }),
      );
    } catch (err) {
      showErrorToast(t('chats.errors.react'), err instanceof Error ? err.message : undefined);
    }
  };

  const handleDeleteMessage = async (msg: ChatMessageView) => {
    if (!threadSessionId || !activeChat) return;
    const msgId = msg.waMessageId || msg.id;

    // Soft-delete always keeps the body for admin; agents see a deleted placeholder.
    if (!window.confirm(t(isAdmin ? 'chats.deleteConfirm' : 'chats.deleteConfirmAgent'))) return;

    try {
      await messageApi.delete(threadSessionId, {
        chatId: activeChat.id,
        messageId: msgId,
        forEveryone: isAdmin,
      });

      // Admin keeps content + Deleted tag; agents get the redacted placeholder locally too.
      updateMessage(threadSessionId, activeChat.id, msg.id, {
        ...(isAdmin ? {} : { body: '', type: 'revoked' as const }),
        metadata: { ...msg.metadata, agentDeleted: true },
      });
    } catch (err) {
      showErrorToast(t('chats.errors.delete'), err instanceof Error ? err.message : undefined);
    }
  };

  // Side effects when the active chat changes: mark-as-read on the gateway + clear sidebar unread badge.
  // The message-history fetch is driven by useChatMessages; scroll restoration is driven by
  // useChatScrollPosition (both keyed off activeChat?.id). Deliberately keying off `activeChat?.id`
  // (not the whole object) so a sidebar reshuffle that mutates the activeChat instance doesn't re-fire
  // the mark-as-read RPC for the same chat.
  useEffect(() => {
    if (!activeChat) return;
    markChatRead(activeChat.id);
    setChats(prev => prev.map(c => (c.id === activeChat.id ? { ...c, unreadCount: 0 } : c)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeChat?.id, markChatRead]);

  // --- Global search: jump to a hit's chat (and best-effort scroll to the message) ---
  // A cross-session hit switches session, which asynchronously reloads the chats list — so the
  // target chat may not be available at click time. pendingHitRef carries the intent across that
  // async gap: the chat-select effect picks it up once the list lands, and the scroll effect runs
  // once the messages have rendered.
  const pendingHitRef = useRef<{ chatId: string; waMessageId: string } | null>(null);

  const handleSearchHit = useCallback(
    (hit: SearchHit) => {
      pendingHitRef.current = { chatId: hit.chatId, waMessageId: hit.waMessageId };
      if (hit.sessionId !== selectedSessionId) {
        // Switching session triggers loadChats; the effect below selects the chat once the list lands.
        setSelectedSessionId(hit.sessionId);
      } else {
        const chat = chats.find(c => c.id === hit.chatId);
        if (chat) {
          if (chat.kind === 'channel') {
            // Channels render their own read-only list on the Channels tab, not via activeChat — the
            // hit's message-highlight is intentionally dropped here since that pane has no per-message scroll target.
            switchTab('channels');
            pendingHitRef.current = null;
          } else if (chat.kind === 'status') {
            setActiveTab('status');
            setActiveChat(chat);
            setActiveChannel(null);
            setActiveStatusContactId(null);
          } else {
            setActiveTab('chats');
            setActiveChat(chat);
            setActiveChannel(null);
            setActiveStatusContactId(null);
          }
        } else {
          pendingHitRef.current = null;
        }
      }
    },
    [selectedSessionId, chats, switchTab],
  );

  // After a session switch the chats list reloads — pick up the pending chat once it appears.
  useEffect(() => {
    const pending = pendingHitRef.current;
    if (!pending || activeChat?.id === pending.chatId) return;
    const chat = chats.find(c => c.id === pending.chatId);
    if (chat) {
      if (chat.kind === 'channel') {
        switchTab('channels');
        pendingHitRef.current = null;
      } else if (chat.kind === 'status') {
        setActiveTab('status');
        setActiveChat(chat);
        setActiveChannel(null);
        setActiveStatusContactId(null);
      } else {
        setActiveTab('chats');
        setActiveChat(chat);
        setActiveChannel(null);
        setActiveStatusContactId(null);
      }
    }
  }, [chats, activeChat, switchTab]);

  // Best-effort scroll to the hit message. Runs as a layout effect (after useChatScrollPosition's
  // own restore on the same commit) so it overrides the bottom/saved jump with no visible flash.
  // Degrades silently to session+chat selection when the element isn't present — the message is
  // still visible in the conversation.
  useLayoutEffect(() => {
    const pending = pendingHitRef.current;
    if (!pending || !activeChat || activeChat.id !== pending.chatId) return;
    if (loadingMessages || messages.length === 0) return;
    const container = messagesContainerRef.current;
    if (container) {
      try {
        const el = container.querySelector(`[data-wa-message-id="${pending.waMessageId}"]`);
        if (el instanceof HTMLElement) el.scrollIntoView({ block: 'center' });
      } catch {
        // Unexpected chars in the id made the selector invalid — ignore.
      }
    }
    pendingHitRef.current = null;
  }, [activeChat, loadingMessages, messages, messagesContainerRef]);

  // Helper formats
  const formatChatTime = useCallback(
    (timestamp?: number) => {
      if (!timestamp) return '';
      const date = new Date(timestamp * 1000);
      const today = new Date();
      if (date.toDateString() === today.toDateString()) {
        return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
      }
      const yesterday = new Date(today);
      yesterday.setDate(yesterday.getDate() - 1);
      if (date.toDateString() === yesterday.toDateString()) {
        return t('chats.yesterday');
      }
      return date.toLocaleDateString([], { month: 'short', day: 'numeric' });
    },
    [t],
  );

  // One search box drives all three tabs; each matches on its own fields. Plain consts (not useMemo)
  // because chats/channelsQuery.data/statusesQuery.data are already stable, query-cached references,
  // so re-filtering on every render is cheap. See utils/chatFilters for the two status orderings.
  const filteredChats = filterChats(chats, searchQuery);

  // A7: the one search box in the sidebar looks inside the messages as well as
  // across the chat names. The floating box that used to do this sat in the
  // top-right corner of a framed panel and read as part of Bitrix rather than
  // part of this screen; an agent hunting for "the deed I sent Khaled" should
  // not have to know which of two boxes to type into.
  //
  // Chat names are matched locally and instantly. Message bodies are a request
  // to the server, so they are debounced and land underneath a moment later —
  // the chat list never waits for them.
  useEffect(() => {
    const query = searchQuery.trim();
    if (!query) {
      setMessageHits([]);
      setMessageHitsLoading(false);
      return;
    }
    const params = buildSearchParams(
      query,
      allChatsMode || !selectedSessionId ? undefined : { sessionId: selectedSessionId },
      {
        limit: 20,
        offset: 0,
      },
    );
    if (!params) {
      setMessageHits([]);
      return;
    }
    setMessageHitsLoading(true);
    let live = true;
    const timer = setTimeout(() => {
      searchApi
        .search(params)
        .then(res => {
          if (live) setMessageHits(res.hits);
        })
        // Silent: full-text search is optional on this deployment (501 when the
        // index is absent), and a red banner over the chat list for a search
        // that simply is not offered would be worse than no message results.
        .catch(() => {
          if (live) setMessageHits([]);
        })
        .finally(() => {
          if (live) setMessageHitsLoading(false);
        });
    }, 300);
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [searchQuery, selectedSessionId, allChatsMode]);
  // The channels zero-state ("not subscribed to any channels") stays keyed on the UNFILTERED list
  // below, so a non-matching search renders an empty list rather than claiming there are none.
  const filteredChannels = filterChannels(channelsQuery.data ?? [], searchQuery);
  const groupedStatuses: ContactStatusGroup[] = groupStatusesByContact(statusesQuery.data ?? [], searchQuery);

  // The open status group, derived — see the activeStatusContactId declaration.
  const activeStatusGroup = activeStatusContactId
    ? (groupedStatuses.find(g => g.contact.id === activeStatusContactId) ?? null)
    : null;

  // Same open-at-newest behavior for the status viewer pane, keyed off the active contact and its
  // item list. Declared after activeStatusGroup: the viewer follows refetches because the deps are
  // the derived group's items, not a click-time snapshot.
  const statusFeedRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const el = statusFeedRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [activeStatusGroup?.contact.id, activeStatusGroup?.items]);

  // Image media items for the lightbox, in render order. `getMediaSrc` reconstructs a usable src
  // from either a base64 payload or a URL — the ChatMessageView shape stores both in `data`.
  const imageMedia = useMemo<LightboxItem[]>(
    () =>
      messages
        .filter(m => m.type === 'image' && Boolean(getMediaSrc(m.metadata?.media)))
        .map(m => ({
          id: m.id,
          url: getMediaSrc(m.metadata?.media),
          alt: m.body || m.metadata?.media?.filename || '',
          senderName: undefined,
          timestamp: formatChatTime(m.timestamp || Math.floor(new Date(m.createdAt).getTime() / 1000)),
        })),
    [messages, formatChatTime],
  );

  return (
    <div className="chats-page">
      <PageHeader
        title={t('nav.chats')}
        subtitle={t('chats.subtitle')}
        // A7: no floating "Search messages…" in the corner. The sidebar already
        // has a search over the chat list, which is what an agent is looking for;
        // a second box hanging in the top-right of a framed panel read as part of
        // Bitrix rather than part of this screen.
        actions={null}
      />

      {/* Conversation Health lives in the sidebar tools menu (hamburger beside
          "WhatsApp session"), not as a permanent strip above the layout. */}

      {/* Real-time connection permanently dropped — let the user re-establish it instead of
          silently showing stale chats. */}
      {connectionFailed && (
        <div className="chats-reconnect-banner" role="alert">
          <AlertCircle size={16} />
          <span>{t('common.disconnected')}</span>
          <button className="btn-secondary" onClick={reconnect}>
            {t('common.refresh')}
          </button>
        </div>
      )}

      {loadingSessions ? (
        <div className="chats-loading-container">
          <Loader2 className="animate-spin" size={32} />
          <p>{t('common.loading')}</p>
        </div>
      ) : sessions.length === 0 && importingSessions.length > 0 ? (
        // A7: a connected phone whose history is still being read. Telling this agent to "connect a
        // session first" would be plainly false — theirs is connected, and the number is right
        // there on the card. The screen recovers on its own: the poll above notices the finish.
        <div className="chats-error-state">
          <Loader2 className="animate-spin" size={40} />
          <h3>Reading this number&rsquo;s history</h3>
          <p>
            {importingSessions
              .map(s => `${s.name}${s.phone ? ` (${s.phone})` : ''} — ${s.syncProgress ?? 0}%`)
              .join(', ')}
          </p>
          <p>Chats appear as soon as this finishes. Showing a half-imported list would look like the rest was lost.</p>
        </div>
      ) : sessions.length === 0 && !isAdmin ? (
        <div className="chats-error-state">
          <AlertCircle size={48} className="text-warn" />
          <h3>{t('chats.noSessionsTitle')}</h3>
          <p>
            <Trans i18nKey="chats.noSessionsDesc">
              Please connect a WhatsApp session from the <strong>Sessions</strong> menu first to use the chat feature.
            </Trans>
          </p>
        </div>
      ) : (
        <div className={`chats-layout ${activeChat || activeChannel || activeStatusGroup ? 'has-active-chat' : ''}`}>
          {/* LEFT SIDEBAR: session & chat rooms */}
          <ChatSidebar
            sessions={sessions}
            selectedSessionId={allChatsMode ? ALL_CHATS_SESSION_ID : selectedSessionId}
            onSelectSession={setSelectedSessionId}
            showAllChats={isAdmin}
            allChatsSelected={allChatsMode}
            activeTab={activeTab}
            onSwitchTab={switchTab}
            searchQuery={searchQuery}
            onSearchQueryChange={setSearchQuery}
            messageHits={messageHits}
            messageHitsLoading={messageHitsLoading}
            onSelectMessageHit={handleSearchHit}
            onComposeStatus={() => setComposeOpen(true)}
            onNewContact={() => setNewContactOpen(true)}
            onOpenProfile={() => setProfileOpen(true)}
            formatChatTime={formatChatTime}
            chatsTab={{
              loading: loadingChats,
              chats: filteredChats,
              activeChatId: activeChat?.id,
              activeSessionId: activeChat?.sessionId || threadSessionId,
              pictures: listPics.data,
              onSelectChat: handleSelectChat,
            }}
            channelsTab={{
              engineLoading: currentEngine.isLoading,
              supported: channelsSupported,
              query: channelsQuery,
              channels: filteredChannels,
              activeChannelId: activeChannel?.id,
              onSelectChannel: setActiveChannel,
            }}
            statusTab={{
              loading: statusesQuery.isLoading,
              error: statusesQuery.isError,
              groups: groupedStatuses,
              activeContactId: activeStatusContactId,
              onSelectContact: setActiveStatusContactId,
            }}
          />

          {/* RIGHT VIEW: active chat room */}
          <main className="chats-room">
            {activeChat ? (
              <div className="room-container">
                {/* Room header */}
                <header className="room-header">
                  <button className="room-back" onClick={() => setActiveChat(null)} aria-label={t('common.back')}>
                    <ArrowLeft size={20} />
                  </button>
                  <button
                    type="button"
                    className="room-contact-btn"
                    onClick={() => setContactPanelOpen(open => !open)}
                    aria-pressed={contactPanelOpen}
                    aria-label="Open contact profile"
                    title="Open contact profile"
                  >
                    <div className="room-avatar">
                      {activePp.data ? (
                        <img
                          src={activePp.data}
                          alt=""
                          // Signed CDN URLs rotate every few hours; refetch the slice on a stale load.
                          onError={() => activePp.refetch()}
                        />
                      ) : (
                        <KindIcon kind={activeChat.kind} />
                      )}
                    </div>
                    <div className="room-contact-info">
                      <h3>{activeChat.name || activeChat.id.split('@')[0]}</h3>
                      {/* Personal chats show the prettified phone number — local formatting for
                          @c.us ids, engine-resolved for @lid privacy ids (which are NOT phones and
                          must never be formatted as one). Groups fall back to a semantic label;
                          the raw JID follows below for the technical case. */}
                      <span className="room-contact-phone">
                        {activePhoneText ??
                          (activeChat.isGroup ? t('chats.groupSubtitle') : t('chats.privateContactSubtitle'))}
                      </span>
                      {/* Raw JID stays on the contact side panel — not in the room header. */}
                    </div>
                  </button>
                  {chatLead && (
                    <button
                      type="button"
                      className="room-open-lead"
                      title={
                        chatLead.colour
                          ? `Conversation Health: ${chatLead.colour.toUpperCase()}`
                          : 'Open linked CRM record'
                      }
                      onClick={() => window.open(chatLead.leadUrl, '_blank', 'noopener,noreferrer')}
                    >
                      <ExternalLink size={14} />
                      {t('conversationHealth.openLeadButton')}
                    </button>
                  )}
                </header>

                {/* Messages body (list, media, reactions, scroll-to-bottom) — components/chats/ChatThread. */}
                <ChatThread
                  activeChat={activeChat}
                  messages={messages}
                  loadingMessages={loadingMessages}
                  messagesError={messagesError}
                  messagesContainerRef={messagesContainerRef}
                  onMediaLoad={onMediaLoad}
                  onOpenImage={messageId => {
                    const idx = imageMedia.findIndex(x => x.id === messageId);
                    if (idx >= 0) setLightboxIndex(idx);
                  }}
                  onReply={setReplyingTo}
                  onReact={handleReactMessage}
                  onDelete={handleDeleteMessage}
                  isAdmin={isAdmin}
                  // A7: history is read media-free, so an imported photo or clip has no bytes until
                  // somebody asks. The thread owns the button; this fetches that one message's file.
                  onLoadMedia={messageId => loadMessageMedia(threadSessionId, activeChat.id, messageId)}
                />

                {/* Composer: attachment preview, emoji panel, reply banner, input bar —
                    components/chats/ChatComposer. */}
                <ChatComposer
                  selectedSessionId={threadSessionId}
                  activeChat={activeChat}
                  replyingTo={replyingTo}
                  setReplyingTo={setReplyingTo}
                  onMessageAppended={onMessageAppended}
                  setChats={setChats}
                  messageInput={messageInput}
                  setMessageInput={setMessageInput}
                  attachment={attachment}
                  setAttachment={setAttachment}
                  previewUrl={previewUrl}
                  setPreviewUrl={setPreviewUrl}
                />

                {/* Contact drawer lives inside the room so it paints over the thread only —
                    not as a fixed viewport sheet that inherits translucent glass tokens. */}
                {contactPanelOpen && activeChat && threadSessionId ? (
                  <ContactProfilePanel
                    session={selectedSession}
                    sessionId={threadSessionId}
                    chat={activeChat}
                    pictureUrl={activePp.data}
                    phoneText={activePhoneText}
                    onClose={() => setContactPanelOpen(false)}
                    onDisplayNameSaved={(chatId, displayName) => {
                      const nextName = displayName?.trim() || null;
                      setChats(prev =>
                        prev.map(c => {
                          if (c.id !== chatId) return c;
                          if (nextName) return { ...c, name: nextName };
                          return c;
                        }),
                      );
                      setActiveChat(prev => {
                        if (!prev || prev.id !== chatId) return prev;
                        if (nextName) return { ...prev, name: nextName };
                        return prev;
                      });
                      if (!nextName) void loadChats(threadSessionId);
                    }}
                    onPinnedChange={(chatId, pinned) => {
                      setChats(prev => {
                        const next = prev.map(c => (c.id === chatId ? { ...c, teamPinned: pinned } : c));
                        next.sort((a, b) => {
                          const pin = Number(Boolean(b.teamPinned)) - Number(Boolean(a.teamPinned));
                          if (pin !== 0) return pin;
                          return (b.timestamp || 0) - (a.timestamp || 0);
                        });
                        return next;
                      });
                      setActiveChat(prev => (prev && prev.id === chatId ? { ...prev, teamPinned: pinned } : prev));
                    }}
                    onArchived={chatId => {
                      setChats(prev => prev.filter(c => c.id !== chatId));
                      setActiveChat(prev => (prev && prev.id === chatId ? null : prev));
                      setContactPanelOpen(false);
                    }}
                    onOpenMedia={messageId => {
                      const idx = imageMedia.findIndex(x => x.id === messageId);
                      if (idx >= 0) setLightboxIndex(idx);
                      else void loadMessageMedia(threadSessionId, activeChat.id, messageId);
                    }}
                  />
                ) : null}
              </div>
            ) : activeChannel ? (
              // Read-only channel pane: no send footer, reactions, delete, reply, or markChatRead —
              // subscribed channels are a broadcast feed, not a two-way conversation.
              <div key={activeChannel.id} className="channel-room">
                <header className="chats-room-header">
                  <button className="room-back" onClick={() => setActiveChannel(null)} aria-label={t('common.back')}>
                    <ArrowLeft size={20} />
                  </button>
                  <Megaphone size={20} />
                  <h2>{activeChannel.name}</h2>
                </header>
                <div className="messages-list" ref={channelFeedRef}>
                  {channelMessages.isLoading ? (
                    <div className="messages-loading">
                      <Loader2 className="animate-spin" size={32} />
                      <span>{t('chats.loadingMessages')}</span>
                    </div>
                  ) : channelMessages.error ? (
                    <div className="messages-empty">
                      <MessageSquare size={32} />
                      <span>{t('chats.loadMessagesError')}</span>
                    </div>
                  ) : (channelMessages.data ?? []).length === 0 ? (
                    <div className="messages-empty">
                      <MessageSquare size={32} />
                      <span>{t('chats.noMessagesInChat')}</span>
                    </div>
                  ) : (
                    (channelMessages.data ?? []).map(m => (
                      <div key={m.id} className="message-bubble incoming">
                        {m.hasMedia && m.mediaUrl && <img className="channel-media" src={m.mediaUrl} alt="" />}
                        {m.body && <MessageBody text={m.body} className="message-text" />}
                        <span className="message-time">{formatChatTime(m.timestamp)}</span>
                      </div>
                    ))
                  )}
                </div>
              </div>
            ) : activeStatusGroup ? (
              // Read-only status viewer: no send footer, reactions, delete, reply, or markChatRead —
              // statuses are ephemeral broadcast posts, not a two-way conversation.
              <div key={activeStatusGroup.contact.id} className="channel-room">
                <header className="chats-room-header">
                  <button
                    className="room-back"
                    onClick={() => setActiveStatusContactId(null)}
                    aria-label={t('common.back')}
                  >
                    <ArrowLeft size={20} />
                  </button>
                  <CircleDashed size={20} />
                  <h2>
                    {activeStatusGroup.contact.name ??
                      activeStatusGroup.contact.pushName ??
                      activeStatusGroup.contact.id}
                  </h2>
                </header>
                <div className="messages-list" ref={statusFeedRef}>
                  {activeStatusGroup.items.map(item => (
                    <div
                      key={item.id}
                      className="message-bubble incoming"
                      // A text status keeps the look it was posted with: background colour (white
                      // text like WhatsApp) and the closest generic font family we have for the
                      // proprietary WhatsApp font slots.
                      style={
                        item.type === 'text' && (item.backgroundColor || item.font)
                          ? {
                              ...(item.backgroundColor ? { backgroundColor: item.backgroundColor, color: '#fff' } : {}),
                              ...statusFontStyle(item.font),
                            }
                          : undefined
                      }
                    >
                      {item.mediaUrl && (
                        <StatusMedia
                          sessionId={selectedSessionId || null}
                          statusId={item.id}
                          type={item.type === 'video' ? 'video' : item.type === 'voice' ? 'audio' : 'image'}
                        />
                      )}
                      {item.caption && <MessageBody text={item.caption} className="message-text" />}
                      <span className="message-time">
                        {formatChatTime(Math.floor(new Date(item.timestamp).getTime() / 1000))}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <div className="chats-room-placeholder">
                <MessageSquare size={80} className="placeholder-icon" />
                <h2>{t('chats.placeholderTitle')}</h2>
                <p>{t('chats.placeholderDesc')}</p>
              </div>
            )}
          </main>
        </div>
      )}

      <MediaLightbox
        items={imageMedia}
        index={lightboxIndex}
        onClose={() => setLightboxIndex(null)}
        onNavigate={setLightboxIndex}
      />

      {composeOpen && (
        <StatusComposeModal
          sessionId={selectedSessionId}
          onClose={() => setComposeOpen(false)}
          onPosted={() => statusesQuery.refetch()}
        />
      )}

      {/* Prefer the picker session; in All chats fall back to the active chat's
          session, then the first connected session so menu actions never no-op. */}
      {newContactOpen && (selectedSession || sessions[0]) && (
        <NewContactModal
          session={selectedSession || (activeChat?.sessionId
            ? sessions.find(s => s.id === activeChat.sessionId) || sessions[0]
            : sessions[0])!}
          initialPhone={newContactPhone}
          onClose={() => {
            setNewContactOpen(false);
            setNewContactPhone('');
          }}
          onStarted={chat => {
            setNewContactOpen(false);
            setNewContactPhone('');
            setActiveChat(chat);
            if (chat.sessionId) setSelectedSessionId(chat.sessionId);
            void loadChats(chat.sessionId || selectedSessionId);
          }}
        />
      )}

      {profileOpen && (selectedSession || sessions[0]) && (
        <AgentProfileModal
          session={selectedSession || (activeChat?.sessionId
            ? sessions.find(s => s.id === activeChat.sessionId) || sessions[0]
            : sessions[0])!}
          openChats={chats.length}
          onClose={() => setProfileOpen(false)}
        />
      )}

      {healthOpen ? (
        <div
          className="a7-health-modal-backdrop"
          role="presentation"
          onClick={() => setHealthOpen(false)}
        >
          <div
            className="a7-health-modal"
            role="dialog"
            aria-modal="true"
            aria-label="Conversation Health"
            onClick={e => e.stopPropagation()}
          >
            <div className="a7-health-modal-head">
              <h3>Conversation Health</h3>
              <button
                type="button"
                className="a7-health-modal-close"
                aria-label="Close"
                onClick={() => setHealthOpen(false)}
              >
                ×
              </button>
            </div>
            <div className="a7-health-modal-body">
              <ConversationHealthPanel compact />
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
