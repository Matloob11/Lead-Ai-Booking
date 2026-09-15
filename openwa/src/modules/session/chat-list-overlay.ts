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

/**
 * True when the list title is only the @lid identity (no push-name / contact name).
 * Long digit strings that match the LID user part are placeholders, not phones.
 */
export function isLidPlaceholderName(chatId: string, name: string | undefined | null): boolean {
  if (!chatId.endsWith('@lid')) return false;
  const lidUser = chatId.split('@')[0] ?? '';
  const trimmed = (name ?? '').trim();
  if (!trimmed) return true;
  if (trimmed === lidUser) return true;
  return /^\d+$/.test(trimmed) && trimmed === lidUser;
}

/** Prefer a human name, then a resolved phone from metadata, then the JID user part. */
export function displayNameForStoredChat(chatId: string, message: Pick<Message, 'chatName' | 'metadata'>): string {
  const chatName = message.chatName?.trim() || '';
  if (chatName && !isLidPlaceholderName(chatId, chatName)) return chatName;
  const phone = message.metadata?.['senderPhone'];
  if (typeof phone === 'string' && phone.trim()) return phone.trim();
  return chatName || chatId.split('@')[0] || chatId;
}

/** One line describing a message, for a list row. Empty when there is nothing honest to say. */
export function previewOf(message: Pick<Message, 'type' | 'body' | 'metadata'>): string {
  // Agent soft-delete keeps the real body for admin — the list must still say "deleted".
  if (message.metadata && message.metadata['agentDeleted'] === true) {
    return TYPE_LABEL.revoked;
  }
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
    const resolvedName = displayNameForStoredChat(chat.id, stored);
    const takeName = isLidPlaceholderName(chat.id, chat.name) && resolvedName !== chat.name;
    if (!takeTimestamp && !takePreview && !takeName) return chat;

    return {
      ...chat,
      name: takeName ? resolvedName : chat.name,
      timestamp: takeTimestamp ? storedAt : chat.timestamp,
      lastMessage: takePreview ? preview : chat.lastMessage,
    };
  });
}

/**
 * Drop the chats that are not conversations — the empty shells WhatsApp Web reports.
 *
 * A linked phone's `getChats()` returns rows for chats that hold nothing at all: no name, no last
 * message, and `timestamp: 0`. They come from address-book entries and from chats opened once and
 * never used. WhatsApp Web labels them **"Unknown user"** — that string is its own, not ours — and
 * they accumulate: 99 of 110 on one number, 63 of 222 on another that had been linked for days.
 * An agent reading a list where nine rows in ten say "Unknown user / No messages yet" cannot find
 * the one that matters, and reasonably concludes the panel is broken.
 *
 * The test is the emptiness, never the name. Checked against two live numbers before writing this:
 * every row named "Unknown user" also had `timestamp: 0`, **no** such row had a real date, and no
 * dated row lacked a name. So the two describe one population, and keying on the emptiness is both
 * exact here and safe against WhatsApp changing its wording or translating it.
 *
 * A conversation older than the history window keeps its real timestamp — the ones that read
 * "Mar 10 · No messages yet" are genuine chats whose messages fall outside the ten days we import,
 * and they survive this. Only rows with nothing whatsoever are removed.
 *
 * Run AFTER {@link overlayStoredMessages}, never before: the overlay is what gives a chat its date
 * and preview back from our own rows, and filtering first would drop chats we hold messages for.
 *
 * An agent who needs to reach one of these people uses New contact, which takes a number.
 */
export function withoutEmptyShells(chats: ChatSummary[]): ChatSummary[] {
  return chats.filter(chat => Boolean(chat.timestamp) || Boolean(chat.lastMessage));
}

/**
 * A chat list built from stored messages alone, for when no engine is loaded.
 *
 * The phone is normally the authority on which chats exist, and
 * {@link overlayStoredMessages} deliberately refuses to invent a chat the engine
 * did not list. That rule is right while a phone is connected and wrong the
 * moment it is not: a number that has disconnected still has months of
 * conversation in our own tables, and answering "no chats" because nobody is
 * holding the handset loses the reason the messages were stored in the first
 * place.
 *
 * `unreadCount` is 0 rather than a guess. Unread is a fact about the handset,
 * and this list is drawn without one; showing a stale badge would be worse than
 * showing none.
 */
export function chatsFromStoredMessages(newest: Map<string, Message>): ChatSummary[] {
  const chats: ChatSummary[] = [];
  for (const [chatId, message] of newest) {
    const isGroup = chatId.endsWith('@g.us');
    chats.push({
      id: chatId,
      // Human name, else resolved phone from metadata, else the JID user part — never blank.
      name: displayNameForStoredChat(chatId, message),
      isGroup,
      kind: isGroup ? 'group' : 'individual',
      unreadCount: 0,
      timestamp: message.timestamp ?? 0,
      lastMessage: previewOf(message),
    });
  }
  return chats.sort((a, b) => (b.timestamp || 0) - (a.timestamp || 0));
}
