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
     * A7: fetch the bytes for ONE message the first history read deliberately left out, and merge
     * them in. Resolves true when that message came back carrying its payload.
     *
     * The first read is media-free on purpose (see the hook above) — a 50 MiB video would sit in
     * heap as base64, held twice as a `data:` URI, and every chat an agent opened would add to it.
     * The cost of that choice is that anything imported from the phone's history shows the omitted
     * placeholder for ever: 187 of 190 media rows on the live account had no bytes, so a video the
     * agent needed read as `📎 Media` with a filename under it and nothing to play.
     *
     * This asked for the whole chat's media at first, which is the wrong unit — and measuring it
     * showed why. WhatsApp stops serving old media, and it does not say so: each dead file is waited
     * on for the gateway's full MEDIA_DOWNLOAD_TIMEOUT_MS before it can be called gone. A chat
     * holding ten of them charged the agent ten timeouts — about five minutes of spinner — to answer
     * a question about the one bubble they pressed. Asking per message costs one timeout, and the
     * other bubbles keep their own state instead of being condemned by a neighbour's result.
     *
     * The slice still comes back whole (media-free apart from the one), because merging it is how
     * the thread stays consistent; the gateway's per-message cap still bounds the payload.
     *
     * Merged rather than replaced: `mergeChatMessages` lets the DB copy win for status and identity
     * while media already in hand survives a payload-less marker — so bytes fetched for an earlier
     * bubble are not wiped by the next bubble's fetch.
     */
    async loadMessageMedia(sessionId: string, chatId: string, messageId: string): Promise<boolean> {
      const key = messagesQueryKey(sessionId, chatId);

      const withMedia = await sessionApi.getChatHistory(sessionId, chatId, 100, true, messageId);
      const history = withMedia.map(mapEngineHistoryMessage);
      qc.setQueryData<ChatMessageView[]>(key, old => (old === undefined ? undefined : mergeChatMessages(old, history)));

      // Whether THIS message arrived with bytes. False is a real and common answer rather than a
      // failure: on the live account every download for a month-old file hit the timeout and came
      // back still marked omitted. The caller has to tell that apart from the request going wrong,
      // or the bubble invites the agent to press it again for ever.
      return history.some(m => m.id === messageId && Boolean(m.metadata?.media?.data));
    },
  };
}
