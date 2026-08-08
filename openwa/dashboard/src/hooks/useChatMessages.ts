import { useQuery, useQueryClient, type UseQueryResult } from '@tanstack/react-query';
import {
  mergeChatMessages,
  mapEngineHistoryMessage,
  mergeOrAppend,
  updateMessageById,
  removeMessageById,
  type ChatMessageView,
} from '../utils/chatMessages';
import { sessionApi } from '../services/api';

export type MessagesQueryKey = readonly ['messages', string, string];

export function messagesQueryKey(sessionId: string, chatId: string): MessagesQueryKey {
  return ['messages', sessionId, chatId] as const;
}

/**
 * Fetch messages for one (sessionId, chatId) and keep them cached (staleTime: Infinity); realtime
 * updates flow through useChatMessagesActions, not refetches. Engine history is fetched WITHOUT media
 * to keep the cache small — a single 50 MiB message would otherwise sit in heap as base64 (held twice
 * as a `data:` URI). Recent media still renders from the DB copy (which wins in mergeChatMessages);
 * older history media shows the omitted placeholder. Live/DB payloads that do arrive are additionally
 * bounded per slice: mergeChatMessages/mergeOrAppend run the result through capMediaPayloads, which
 * strips the oldest base64 beyond MEDIA_PAYLOAD_CACHE_LIMIT so a long media-heavy session can't grow
 * the tab's heap without bound. Cache eviction happens 5 min after the chat stops being observed
 * (gcTime), so browsing several media-rich chats doesn't accumulate large slices.
 */
export function useChatMessages(sessionId: string, chatId: string | null): UseQueryResult<ChatMessageView[], Error> {
  return useQuery<ChatMessageView[], Error>({
    queryKey: messagesQueryKey(sessionId, chatId ?? ''),
    queryFn: async () => {
      const [dbRes, historyRes] = await Promise.allSettled([
        sessionApi.getChatMessages(sessionId, chatId!, 100),
        sessionApi.getChatHistory(sessionId, chatId!, 100, false),
      ]);
      if (dbRes.status === 'rejected' && historyRes.status === 'rejected') throw dbRes.reason;
      const dbMessages = dbRes.status === 'fulfilled' ? dbRes.value.messages : [];
      const history = historyRes.status === 'fulfilled' ? historyRes.value.map(mapEngineHistoryMessage) : [];
      return mergeChatMessages(dbMessages, history);
    },
    enabled: Boolean(sessionId && chatId),
    staleTime: Infinity,
    gcTime: 5 * 60 * 1000,
  });
}

/**
 * Mutation helpers that write directly to the React Query cache. Use these
 * from the WebSocket subscriber, the optimistic-send flow, and ACK handlers
 * instead of calling setMessages locally.
 */
export function useChatMessagesActions() {
  const qc = useQueryClient();

  return {
    appendMessage(sessionId: string, chatId: string, msg: ChatMessageView) {
      // Only append to a slice that already exists (a chat that has been opened). Do NOT seed a slice
      // for a never-opened chat: with staleTime: Infinity that phantom slice would be "fresh", so
      // opening the chat would skip the full-history queryFn and show only this one message (truncated
      // history). Returning undefined from the updater is a no-op when there is no cached data.
      qc.setQueryData<ChatMessageView[]>(messagesQueryKey(sessionId, chatId), old =>
        old === undefined ? undefined : mergeOrAppend(old, msg),
      );
    },
    updateMessage(sessionId: string, chatId: string, id: string, patch: Partial<ChatMessageView>) {
      qc.setQueryData<ChatMessageView[]>(messagesQueryKey(sessionId, chatId), (old = []) =>
        updateMessageById(old, id, patch),
      );
    },
    removeMessage(sessionId: string, chatId: string, id: string) {
      qc.setQueryData<ChatMessageView[]>(messagesQueryKey(sessionId, chatId), (old = []) => removeMessageById(old, id));
    },

    /**
     * A7: fetch this chat's history AGAIN, this time with the media, and merge the bytes in.
     *
     * The first read is deliberately media-free (see the hook above) — a 50 MiB video would sit in
     * heap as base64, held twice as a `data:` URI, and every chat an agent opened would add to it. The
     * cost of that choice is that anything imported from the phone's history shows the omitted
     * placeholder for ever: 187 of 190 media rows on the live account had no bytes, so a video the
     * agent needed read as `📎 Media` with a filename under it and nothing to play.
     *
     * So the bytes are fetched when somebody actually asks for them, per chat, which is the only
     * moment we know they are wanted. The gateway's own aggregate budget
     * (CHAT_HISTORY_MEDIA_BUDGET_BYTES) and per-message cap bound the response, so a chat full of
     * films cannot be turned into one enormous reply — anything past the budget comes back still
     * marked omitted, and the bubble keeps saying so honestly.
     *
     * Merged rather than replaced: `mergeChatMessages` lets the DB copy win, which is what carries
     * live media and the delivery ticks, so pulling history in again cannot undo either.
     */
    async loadChatMedia(sessionId: string, chatId: string): Promise<number> {
      const key = messagesQueryKey(sessionId, chatId);
      // The ids that were WAITING, captured before the fetch. Counting bytes across the whole slice
      // afterwards is not the same question and gets the answer wrong: a chat with one live photo
      // already in it would report success while every omitted bubble the agent pressed stayed
      // omitted — which is exactly what happened the first time this was tried.
      const waiting = new Set(
        (qc.getQueryData<ChatMessageView[]>(key) ?? [])
          .filter(m => m.metadata?.media?.omitted)
          .map(m => m.id),
      );

      const withMedia = await sessionApi.getChatHistory(sessionId, chatId, 100, true);
      const history = withMedia.map(mapEngineHistoryMessage);
      qc.setQueryData<ChatMessageView[]>(key, old => (old === undefined ? undefined : mergeChatMessages(old, history)));

      // How many of those actually arrived with bytes. Zero is a real and common answer rather than a
      // failure: WhatsApp stops serving old media, and on the live account every download for a
      // month-old file hit MEDIA_DOWNLOAD_TIMEOUT_MS and came back still marked omitted. The caller
      // needs to tell that apart, or the bubble invites the agent to press it again for ever.
      return history.filter(m => waiting.has(m.id) && m.metadata?.media?.data).length;
    },
  };
}
