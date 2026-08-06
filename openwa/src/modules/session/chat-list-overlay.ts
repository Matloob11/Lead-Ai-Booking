import type { ChatSummary } from '../../engine/interfaces/whatsapp-engine.interface';
import type { Message } from '../message/entities/message.entity';

/**
 * Correct a chat list against what we actually hold.
 *
 * The engine builds its list from WhatsApp Web's own chat models, and those disagree with the
 * thread in two ways that an agent reads as data loss:
 *
 *   - **No preview.** 63 of 157 chats on the live number came back with no `lastMessage` at all,
 *     so the row said "No messages yet" beside a conversation that plainly had messages in it.
 *     A media message is the common cause: its body is the caption, and most media has none.
 *   - **A stale date.** The chat model's timestamp is whatever WhatsApp Web last recorded for that
 *     chat, which is not moved by everything we store. A chat whose row read "Mar 10" had newer
 *     messages in the thread below it.
 *
 * So the row is rebuilt from our own rows wherever ours are newer, and only the fields that were
 * wrong are touched — name, unread count and kind still belong to the engine, which is the only
 * one that knows them.
 *
 * System messages are excluded from the preview on purpose. They carry no body and nobody wrote
 * them, so letting one become a chat's preview replaces a real sentence with a blank and moves the
 * chat to the top of the list on a timestamp no human produced.
 */

/** What a row shows when the message itself has no text — a caption-less photo, a voice note. */
const TYPE_LABEL: Record<string, string> = {
  image: 'Photo',
  video: 'Video',
  audio: 'Audio',
  voice: 'Voice message',
  document: 'Document',
  sticker: 'Sticker',
  location: 'Location',
  contact: 'Contact',
  poll: 'Poll',
  call: 'Call',
  revoked: 'Message deleted',
  masked: 'Message not available',
};

/** One line describing a message, for a list row. Empty when there is nothing honest to say. */
export function previewOf(message: Pick<Message, 'type' | 'body'>): string {
  const body = message.body?.trim();
  if (body) return body;
  return TYPE_LABEL[message.type] ?? '';
}

/**
 * The newest *describable* stored message per chat, from a slice already ordered newest-first.
 *
 * Takes the first row it sees for each chat, which is the newest one precisely because the caller
 * sorted. A chat whose newest message falls outside the slice simply is not in the map, and the
 * engine's own value stands for it — the behaviour before any of this existed.
 *
 * A row that `previewOf` cannot describe is stepped over rather than taken. Two kinds land here: a
 * system notice, and a bodiless row of a type we never mapped — 17 chats on the live number were
 * headed by exactly that, an old encryption notice stored back when everything unmapped became
 * `unknown`. Stopping at one would define the row by the one message in it that says nothing, and
 * the real sentence a line below would never be seen.
 */
export function newestPerChat(messages: Message[]): Map<string, Message> {
  const newest = new Map<string, Message>();
  for (const message of messages) {
    if (!message.chatId || newest.has(message.chatId)) continue;
    if (message.type === 'system' || previewOf(message) === '') continue;
    newest.set(message.chatId, message);
  }
  return newest;
}

/**
 * Apply the stored rows over an engine chat list.
 *
 * Ours wins only when it is genuinely newer, or when the engine offered no preview at all. The
 * engine is still the authority on which chats exist: a chat we hold messages for but that the
 * engine did not list is not invented here, because the phone is what says a chat is still there.
 */
export function overlayStoredMessages(chats: ChatSummary[], newest: Map<string, Message>): ChatSummary[] {
  return chats.map(chat => {
    const stored = newest.get(chat.id);
    if (!stored) return chat;

    const storedAt = stored.timestamp ?? 0;
    const preview = previewOf(stored);
    // Two separate questions, deliberately: a chat can have a correct date and no preview (media
    // with no caption), and answering only the first would leave the row still reading empty.
    const takeTimestamp = storedAt > (chat.timestamp ?? 0);
    const takePreview = preview !== '' && (takeTimestamp || !chat.lastMessage);
    if (!takeTimestamp && !takePreview) return chat;

    return {
      ...chat,
      timestamp: takeTimestamp ? storedAt : chat.timestamp,
      lastMessage: takePreview ? preview : chat.lastMessage,
    };
  });
}
