import { useTranslation } from 'react-i18next';
import { AlertCircle, CircleDashed, Loader2, Megaphone, Search, SquarePen, UserRound } from 'lucide-react';
import type { UseQueryResult } from '@tanstack/react-query';
import type { Channel, Chat, ContactStatusGroup, Session } from '../../services/api';
import ChatAvatar from './ChatAvatar';

export type ChatsTab = 'chats' | 'channels' | 'status';

interface ChatSidebarProps {
  sessions: Session[];
  selectedSessionId: string;
  onSelectSession: (sessionId: string) => void;
  activeTab: ChatsTab;
  onSwitchTab: (tab: ChatsTab) => void;
  searchQuery: string;
  onSearchQueryChange: (query: string) => void;
  onComposeStatus: () => void;
  /** A7: the two things an agent can do that are not answering somebody. */
  onNewContact: () => void;
  onOpenProfile: () => void;
  formatChatTime: (timestamp?: number) => string;
  chatsTab: {
    loading: boolean;
    chats: Chat[];
    activeChatId?: string;
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
  activeTab,
  searchQuery,
  onSearchQueryChange,
  onNewContact,
  onOpenProfile,
  formatChatTime,
  chatsTab,
  channelsTab,
  statusTab,
}: ChatSidebarProps) {
  const { t } = useTranslation();

  const formatLastMessageSnippet = (chat: Chat) => chat.lastMessage || '';

  // Shared row markup for the Chats and Status lists — a plain function (not memoized) since it
  // closes over render-scoped props (chatsTab.activeChatId, chatsTab.pictures) that already
  // change every render.
  const renderChatRow = (chat: Chat) => {
    const isActive = chatsTab.activeChatId === chat.id;
    return (
      <div
        key={chat.id}
        className={`chat-item-card ${isActive ? 'active' : ''}`}
        onClick={() => chatsTab.onSelectChat(chat)}
      >
        <ChatAvatar pictureUrl={chatsTab.pictures?.[chat.id]} kind={chat.kind} />

        <div className="chat-item-info">
          <div className="chat-item-top">
            <span className="chat-item-name" title={chat.name || chat.id}>
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
        </div>
      </div>
    );
  };

  return (
    <aside className="chats-sidebar">
      <div className="sidebar-header-box">
        {/* Session selector */}
        <div className="session-select-group">
          <label className="form-label">{t('chats.sessionLabel')}</label>
          <select
            value={selectedSessionId}
            onChange={e => onSelectSession(e.target.value)}
            className="session-selector"
          >
            {sessions.map(s => (
              <option key={s.id} value={s.id}>
                {s.name} ({s.phone || t('chats.noPhone')})
              </option>
            ))}
          </select>
        </div>

        {/* A7: the Chats / Channels / Status tab bar is gone.
            A7 does not use WhatsApp channels or statuses, and the two tabs were
            two thirds of a switch that only ever had one useful position. The
            lists below still key off `activeTab`, which nothing can move off
            'chats' now that the only control that set it has been removed —
            they are left in place rather than deleted so an upstream merge
            stays readable. */}

        {/* A7: the two things on this screen that are not answering somebody —
            reaching a number for the first time, and seeing how the day has
            gone. Above the search rather than below it: the list underneath is
            people who already wrote, and neither of these is about them. */}
        <div className="a7-sidebar-actions">
          <button type="button" className="a7-side-btn" onClick={onNewContact}>
            <SquarePen size={16} />
            New contact
          </button>
          <button type="button" className="a7-side-btn" onClick={onOpenProfile}>
            <UserRound size={16} />
            Profile
          </button>
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

      {/* Chat list */}
      {activeTab === 'chats' && (
        <div className="chats-list">
          {chatsTab.loading ? (
            <div className="chats-list-loading">
              <Loader2 className="animate-spin" size={24} />
              <span>{t('chats.loadingChats')}</span>
            </div>
          ) : chatsTab.chats.length === 0 ? (
            <div className="chats-list-empty">
              <span>{t('chats.empty')}</span>
            </div>
          ) : (
            chatsTab.chats.map(renderChatRow)
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
    </aside>
  );
}

export default ChatSidebar;
