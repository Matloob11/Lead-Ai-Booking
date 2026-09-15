import { useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertCircle, CircleDashed, Loader2, Megaphone, Menu, Pin, Plus, Search, X } from 'lucide-react';
import type { UseQueryResult } from '@tanstack/react-query';
import {
  ALL_CHATS_SESSION_ID,
  type Channel,
  type Chat,
  type ContactStatusGroup,
  type SearchHit,
  type Session,
} from '../../services/api';
import { renderHighlightedSnippet } from '../../utils/search-highlight';
import { useAppMenu } from '../../hooks/useAppMenu';
import ChatAvatar from './ChatAvatar';

export type ChatsTab = 'chats' | 'channels' | 'status';

interface ChatSidebarProps {
  sessions: Session[];
  selectedSessionId: string;
  onSelectSession: (sessionId: string) => void;
  /** Admin-only: All chats option in the session picker. */
  showAllChats?: boolean;
  allChatsSelected?: boolean;
  activeTab: ChatsTab;
  onSwitchTab: (tab: ChatsTab) => void;
  searchQuery: string;
  onSearchQueryChange: (query: string) => void;
  onComposeStatus: () => void;
  /** Kept for Chats.tsx call-site stability; app menu owns these actions now. */
  onNewContact?: () => void;
  onOpenProfile?: () => void;
  /** A7: what the search box found inside the messages, shown under the chats. */
  messageHits: SearchHit[];
  messageHitsLoading: boolean;
  onSelectMessageHit: (hit: SearchHit) => void;
  formatChatTime: (timestamp?: number) => string;
  chatsTab: {
    loading: boolean;
    chats: Chat[];
    activeChatId?: string;
    activeSessionId?: string;
    pictures?: Record<string, string | null>;
    onSelectChat: (chat: Chat) => void;
  };
  channelsTab: {
    engineLoading: boolean;
    supported: boolean;
    query: UseQueryResult<Channel[], Error>;
    channels: Channel[];
    activeChannelId?: string;
    onSelectChannel: (channel: Channel) => void;
  };
  statusTab: {
    loading: boolean;
    error: boolean;
    groups: ContactStatusGroup[];
    activeContactId: string | null;
    onSelectContact: (contactId: string) => void;
  };
}

// LEFT SIDEBAR: session selector, search, and the chat list.
// The page owns all queries/state; this component renders them and reports interactions up.
//
// A7: `onSwitchTab` and `onComposeStatus` stay on the props interface but are no
// longer taken here — the tab bar and the status composer they drove are gone, and
// leaving them on the interface means Chats.tsx still passes what it always passed
// and an upstream merge has less to reconcile.
function ChatSidebar({
  sessions,
  selectedSessionId,
  onSelectSession,
  showAllChats = false,
  allChatsSelected = false,
  activeTab,
  searchQuery,
  onSearchQueryChange,
  onNewContact,
  messageHits,
  messageHitsLoading,
  onSelectMessageHit,
  formatChatTime,
  chatsTab,
  channelsTab,
  statusTab,
}: ChatSidebarProps) {
  const { t } = useTranslation();
  const { menuOpen, toggleMenu, setChatsHostsMenu } = useAppMenu();

  // This screen owns the hamburger (pic-1 style). Hide Layout's floating trigger.
  useEffect(() => {
    setChatsHostsMenu(true);
    return () => setChatsHostsMenu(false);
  }, [setChatsHostsMenu]);

  const formatLastMessageSnippet = (chat: Chat) => chat.lastMessage || '';

  const sessionStatusLabel = (chat: Chat): string => {
    if (chat.removed) return 'removed';
    if (chat.sessionStatus === 'ready') return 'connected';
    return chat.sessionStatus || 'offline';
  };

  // Shared row markup for the Chats and Status lists — a plain function (not memoized) since it
  // closes over render-scoped props (chatsTab.activeChatId, chatsTab.pictures) that already
  // change every render.
  const renderChatRow = (chat: Chat) => {
    const rowKey = chat.sessionId ? `${chat.sessionId}:${chat.id}` : chat.id;
    const isActive =
      chatsTab.activeChatId === chat.id &&
      (!chat.sessionId || chatsTab.activeSessionId === chat.sessionId);
    const locked = chat.canOpenThread === false;
    return (
      <div
        key={rowKey}
        className={`chat-item-card ${isActive ? 'active' : ''} ${locked ? 'chat-item-locked' : ''}`}
        onClick={() => chatsTab.onSelectChat(chat)}
        title={locked ? 'Session removed — history is listed only' : undefined}
      >
        <ChatAvatar pictureUrl={chatsTab.pictures?.[chat.id]} kind={chat.kind} />

        <div className="chat-item-info">
          <div className="chat-item-top">
            <span className="chat-item-name" title={chat.name || chat.id}>
              {chat.teamPinned ? <Pin size={12} className="chat-item-pin" aria-hidden /> : null}
              {chat.name || chat.id.split('@')[0]}
            </span>
            {chat.kind !== 'individual' && chat.kind !== 'unknown' && (
              <span className={`chat-kind-badge kind-${chat.kind}`}>{t(`chats.kind.${chat.kind}`)}</span>
            )}
            {/* Ternary, not `&&`: a chat with no messages carries timestamp 0, and React
                renders the number 0 as text — so `0 && <span/>` painted a literal "0"
                where the time belongs, on every such row. */}
            {chat.timestamp ? <span className="chat-item-time">{formatChatTime(chat.timestamp)}</span> : null}
          </div>
          <div className="chat-item-bottom">
            <span className="chat-item-snippet" title={formatLastMessageSnippet(chat)}>
              {formatLastMessageSnippet(chat) || <span className="no-message">{t('chats.noMessageYet')}</span>}
            </span>
            {chat.unreadCount > 0 && (
              <span
                className="chat-unread-badge"
                title={t('chats.unreadBadge', { count: chat.unreadCount })}
                aria-label={t('chats.unreadBadge', { count: chat.unreadCount })}
              >
                {chat.unreadCount > 99 ? '99+' : chat.unreadCount}
              </span>
            )}
          </div>
          {chat.sessionName ? (
            <div className="chat-item-session">
              <span>{chat.sessionName}</span>
              <span className={`chat-session-status status-${sessionStatusLabel(chat)}`}>
                {sessionStatusLabel(chat)}
              </span>
            </div>
          ) : null}
        </div>
      </div>
    );
  };

  return (
    <aside className="chats-sidebar">
      <div className="sidebar-header-box">
        {/* Pic-1: "WhatsApp session" + hamburger opens the app dropdown (nav +
            Conversation Health / New contact / Profile). Chats stay full-width. */}
        <div className="session-select-group">
          <div className="a7-session-label-row">
            <label className="form-label">{t('chats.sessionLabel')}</label>
            <button
              type="button"
              className={`a7-tools-menu-btn ${menuOpen ? 'open' : ''}`}
              data-a7-menu-trigger
              aria-expanded={menuOpen}
              aria-controls="a7-app-menu"
              aria-label={menuOpen ? 'Close menu' : 'Open menu'}
              onClick={toggleMenu}
            >
              {menuOpen ? <X size={18} strokeWidth={2.25} /> : <Menu size={18} strokeWidth={2.25} />}
            </button>
          </div>

          <div className="session-select-row">
            <select
              value={allChatsSelected ? ALL_CHATS_SESSION_ID : selectedSessionId}
              onChange={e => onSelectSession(e.target.value)}
              className="session-selector"
            >
              {showAllChats ? <option value={ALL_CHATS_SESSION_ID}>All chats</option> : null}
              {sessions.map(s => (
                <option key={s.id} value={s.id}>
                  {s.name} ({s.phone || t('chats.noPhone')})
                </option>
              ))}
            </select>
          </div>
        </div>

        {/* Search bar */}
        <div className="chat-search-input">
          <Search size={18} />
          <input
            type="text"
            placeholder={t('chats.searchPlaceholder')}
            value={searchQuery}
            onChange={e => onSearchQueryChange(e.target.value)}
          />
        </div>

        {/* A7: the "compose a status" button went with the Status tab. */}
      </div>

      {/* Chat list, and — while something is typed — what the same box found
          inside the messages, underneath it. Chats first because a name is what
          an agent usually means; the message hits are the fallback for "I know
          what was said but not who said it". */}
      {activeTab === 'chats' && (
        <div className="chats-list">
          {chatsTab.loading ? (
            <div className="chats-list-loading">
              <Loader2 className="animate-spin" size={24} />
              <span>{t('chats.loadingChats')}</span>
            </div>
          ) : chatsTab.chats.length === 0 && !searchQuery.trim() ? (
            <div className="chats-list-empty">
              <span>{t('chats.empty')}</span>
            </div>
          ) : (
            <>
              {chatsTab.chats.length > 0 && (
                <>
                  {searchQuery.trim() && <div className="a7-search-group">Chats</div>}
                  {chatsTab.chats.map(renderChatRow)}
                </>
              )}

              {searchQuery.trim() && (
                <>
                  <div className="a7-search-group">
                    Messages
                    {messageHitsLoading && <Loader2 className="animate-spin" size={13} />}
                  </div>

                  {!messageHitsLoading && messageHits.length === 0 && (
                    <div className="a7-search-none">No messages match.</div>
                  )}

                  {messageHits.map(hit => {
                    // A hit carries only the chat's id. The loaded chat list
                    // usually knows its name, and a name is what the agent
                    // recognises; the bare id is the honest fallback.
                    const named = chatsTab.chats.find(c => c.id === hit.chatId);
                    return (
                      <button
                        key={hit.messageId}
                        type="button"
                        className="a7-hit"
                        onClick={() => onSelectMessageHit(hit)}
                      >
                        <span className="a7-hit__who">
                          {named?.name || hit.chatId.split('@')[0]}
                          <span className="a7-hit__when">
                            {new Date(hit.timestamp * 1000).toLocaleDateString()}
                          </span>
                        </span>
                        {/* The server marks the matched run and
                            renderHighlightedSnippet returns it as segments. Built
                            as nodes, never innerHTML — this is whatever a customer
                            typed. */}
                        <span className="a7-hit__text">
                          {renderHighlightedSnippet(hit.snippet).map((seg, i) =>
                            seg.marked ? <mark key={i}>{seg.text}</mark> : <span key={i}>{seg.text}</span>,
                          )}
                        </span>
                      </button>
                    );
                  })}
                </>
              )}
            </>
          )}
        </div>
      )}

      {/* Channels list — wwjs-only (newsletter/channel API isn't implemented on Baileys, which
          throws 501 for both listing and reading). channelsQuery is gated off entirely on that
          engine, so the branch order below never depends on a request having actually run. */}
      {activeTab === 'channels' && (
        <div className="chats-list">
          {channelsTab.engineLoading ? (
            <div className="chats-list-loading">
              <Loader2 className="animate-spin" size={24} />
            </div>
          ) : !channelsTab.supported ? (
            <div className="chats-list-empty">
              <span>{t('chats.channels.notSupported')}</span>
            </div>
          ) : channelsTab.query.isLoading ? (
            <div className="chats-list-loading">
              <Loader2 className="animate-spin" size={24} />
            </div>
          ) : channelsTab.query.error ? (
            <div className="chats-list-empty">
              <AlertCircle size={24} className="text-warn" />
              <span>{t('chats.channels.notReady')}</span>
            </div>
          ) : (channelsTab.query.data?.length ?? 0) === 0 ? (
            <div className="chats-list-empty">
              <span>{t('chats.channels.empty')}</span>
            </div>
          ) : (
            channelsTab.channels.map(ch => (
              <div
                key={ch.id}
                className={`chat-item-card ${channelsTab.activeChannelId === ch.id ? 'active' : ''}`}
                onClick={() => channelsTab.onSelectChannel(ch)}
              >
                <div className="chat-avatar">
                  <Megaphone size={20} />
                </div>
                <div className="chat-item-info">
                  <div className="chat-item-top">
                    <span className="chat-item-name">{ch.name}</span>
                  </div>
                  {ch.subscriberCount != null && (
                    <div className="chat-item-bottom">
                      <span className="chat-item-snippet">
                        {t('chats.channels.subscribers', { count: ch.subscriberCount })}
                      </span>
                    </div>
                  )}
                </div>
              </div>
            ))
          )}
        </div>
      )}

      {/* Status list — per-contact status groups read from the 24h store. Not engine-gated:
          both engines now have status content. */}
      {activeTab === 'status' && (
        <div className="chats-list">
          {statusTab.loading ? (
            <div className="chats-list-loading">
              <Loader2 className="animate-spin" size={24} />
            </div>
          ) : statusTab.error ? (
            <div className="chats-list-empty">
              <AlertCircle size={24} className="text-warn" />
              <span>{t('chats.status.loadError')}</span>
            </div>
          ) : statusTab.groups.length === 0 ? (
            <div className="chats-list-empty">
              <span>{t('chats.status.empty')}</span>
            </div>
          ) : (
            statusTab.groups.map(group => (
              <div
                key={group.contact.id}
                className={`chat-item-card ${statusTab.activeContactId === group.contact.id ? 'active' : ''}`}
                onClick={() => statusTab.onSelectContact(group.contact.id)}
              >
                <div className="chat-avatar">
                  <CircleDashed size={20} />
                </div>
                <div className="chat-item-info">
                  <div className="chat-item-top">
                    <span className="chat-item-name">
                      {group.contact.name ?? group.contact.pushName ?? group.contact.id}
                    </span>
                    <span className="chat-item-time">
                      {formatChatTime(Math.floor(new Date(group.latest).getTime() / 1000))}
                    </span>
                  </div>
                  <div className="chat-item-bottom">
                    <span className="chat-item-snippet">
                      {t('chats.status.itemCount', { count: group.items.length })}
                    </span>
                  </div>
                </div>
              </div>
            ))
          )}
        </div>
      )}

      {/* Always visible over the chat list — same idea as Official API FAB. */}
      {onNewContact ? (
        <button
          type="button"
          className="a7-new-contact-fab"
          title="New contact"
          aria-label="New contact"
          onClick={onNewContact}
        >
          <Plus size={22} strokeWidth={2.4} />
          <span>New</span>
        </button>
      ) : null}
    </aside>
  );
}

export default ChatSidebar;
