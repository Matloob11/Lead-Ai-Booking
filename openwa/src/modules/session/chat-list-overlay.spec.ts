import {
  chatsFromStoredMessages,
  displayNameForStoredChat,
  isLidPlaceholderName,
  newestPerChat,
  overlayStoredMessages,
  previewOf,
  withoutEmptyShells,
} from './chat-list-overlay';
import type { Message } from '../message/entities/message.entity';
import type { ChatSummary } from '../../engine/interfaces/whatsapp-engine.interface';

const row = (over: Partial<Message>): Message =>
  ({ chatId: 'a@lid', type: 'text', body: 'hi', timestamp: 100, ...over }) as Message;

const chat = (over: Partial<ChatSummary>): ChatSummary => ({
  id: 'a@lid',
  name: 'A',
  isGroup: false,
  kind: 'individual',
  unreadCount: 0,
  timestamp: 50,
  ...over,
});

describe('isLidPlaceholderName / displayNameForStoredChat', () => {
  it('treats the bare LID user part as a placeholder', () => {
    expect(isLidPlaceholderName('220671762296928@lid', '220671762296928')).toBe(true);
    expect(isLidPlaceholderName('220671762296928@lid', 'Shahid')).toBe(false);
    expect(isLidPlaceholderName('971501234567@c.us', '971501234567')).toBe(false);
  });

  it('prefers a human name, then senderPhone, then the LID digits', () => {
    expect(
      displayNameForStoredChat('220671762296928@lid', {
        chatName: 'Shahid',
        metadata: { senderPhone: '97150111222' },
      }),
    ).toBe('Shahid');
    expect(
      displayNameForStoredChat('220671762296928@lid', {
        chatName: '220671762296928',
        metadata: { senderPhone: '97150111222' },
      }),
    ).toBe('97150111222');
    expect(
      displayNameForStoredChat('220671762296928@lid', { chatName: '220671762296928', metadata: {} }),
    ).toBe('220671762296928');
  });
});

describe('previewOf', () => {
  it('prefers what was actually said', () => {
    expect(previewOf(row({ type: 'image', body: 'look at this' }))).toBe('look at this');
  });

  // The reason the live list read "No messages yet" on chats that plainly had messages: most media
  // carries no caption, so the body is empty and the row had nothing to show.
  it('describes a message that carries no text', () => {
    expect(previewOf(row({ type: 'image', body: '' }))).toBe('Photo');
    expect(previewOf(row({ type: 'voice', body: undefined as unknown as string }))).toBe('Voice message');
  });

  it('says nothing rather than something invented', () => {
    expect(previewOf(row({ type: 'unknown', body: '' }))).toBe('');
  });
});

describe('newestPerChat', () => {
  it('takes the first row per chat, which is the newest because the caller sorted', () => {
    const map = newestPerChat([
      row({ chatId: 'a@lid', body: 'newest', timestamp: 300 }),
      row({ chatId: 'a@lid', body: 'older', timestamp: 200 }),
      row({ chatId: 'b@lid', body: 'b', timestamp: 250 }),
    ]);
    expect(map.get('a@lid')?.body).toBe('newest');
    expect(map.get('b@lid')?.body).toBe('b');
  });

  // Nobody wrote these and they carry no body. Letting one become a preview replaces a real
  // sentence with a blank and lifts the chat on a timestamp no human produced.
  it('ignores system messages entirely', () => {
    const map = newestPerChat([
      row({ chatId: 'a@lid', type: 'system', body: '', timestamp: 900 }),
      row({ chatId: 'a@lid', body: 'real', timestamp: 100 }),
    ]);
    expect(map.get('a@lid')?.body).toBe('real');
  });

  // 17 chats on the live number were headed by one of these: an old encryption notice, stored back
  // when everything unmapped became `unknown`. Stopping there defines the row by the one message
  // that says nothing, and the real sentence below it is never seen.
  it('steps over a bodiless row it cannot describe', () => {
    const map = newestPerChat([
      row({ chatId: 'a@lid', type: 'unknown', body: '', timestamp: 900 }),
      row({ chatId: 'a@lid', body: 'real', timestamp: 100 }),
    ]);
    expect(map.get('a@lid')?.body).toBe('real');
  });

  it('still takes an unmapped row that does carry text', () => {
    const map = newestPerChat([row({ chatId: 'a@lid', type: 'unknown', body: 'said something', timestamp: 900 })]);
    expect(map.get('a@lid')?.body).toBe('said something');
  });
});

describe('overlayStoredMessages', () => {
  it('corrects a row whose stored message is newer', () => {
    const [out] = overlayStoredMessages(
      [chat({ timestamp: 50, lastMessage: 'stale' })],
      newestPerChat([row({ timestamp: 300, body: 'fresh' })]),
    );
    expect(out.timestamp).toBe(300);
    expect(out.lastMessage).toBe('fresh');
  });

  // A chat can have the right date and still no preview — caption-less media is exactly that case.
  it('fills a missing preview without moving a date that is already correct', () => {
    const [out] = overlayStoredMessages(
      [chat({ timestamp: 300, lastMessage: undefined })],
      newestPerChat([row({ timestamp: 100, type: 'image', body: '' })]),
    );
    expect(out.timestamp).toBe(300);
    expect(out.lastMessage).toBe('Photo');
  });

  it('leaves the engine alone when it is ahead', () => {
    const [out] = overlayStoredMessages(
      [chat({ timestamp: 900, lastMessage: 'engine knows' })],
      newestPerChat([row({ timestamp: 100, body: 'ours is older' })]),
    );
    expect(out.timestamp).toBe(900);
    expect(out.lastMessage).toBe('engine knows');
  });

  // The phone is what says a chat still exists; a chat we hold rows for but the engine dropped was
  // removed on the handset, and resurrecting it here would put a deleted conversation back.
  it('never invents a chat the engine did not list', () => {
    const out = overlayStoredMessages([], newestPerChat([row({ chatId: 'ghost@lid' })]));
    expect(out).toEqual([]);
  });

  it('leaves a chat with nothing stored exactly as the engine gave it', () => {
    const original = chat({ id: 'z@lid', lastMessage: 'engine' });
    const [out] = overlayStoredMessages([original], newestPerChat([]));
    expect(out).toBe(original);
  });

  it('replaces a LID placeholder title with a stored senderPhone', () => {
    const [out] = overlayStoredMessages(
      [chat({ id: '220671762296928@lid', name: '220671762296928', timestamp: 300, lastMessage: 'ok' })],
      newestPerChat([
        row({
          chatId: '220671762296928@lid',
          chatName: '220671762296928',
          timestamp: 100,
          body: 'older',
          metadata: { senderPhone: '97150111222' },
        }),
      ]),
    );
    expect(out.name).toBe('97150111222');
    expect(out.timestamp).toBe(300);
    expect(out.lastMessage).toBe('ok');
  });
});

describe('chatsFromStoredMessages', () => {
  it('uses senderPhone when the stored chatName is only the LID', () => {
    const [out] = chatsFromStoredMessages(
      newestPerChat([
        row({
          chatId: '220671762296928@lid',
          chatName: '220671762296928',
          metadata: { senderPhone: '97150111222' },
          body: 'hi',
          timestamp: 100,
        }),
      ]),
    );
    expect(out.name).toBe('97150111222');
  });
});

describe('withoutEmptyShells', () => {
  // What WhatsApp Web reports for an address-book entry or a chat opened once and never used: no
  // name it can resolve, no last message, no date. 99 of 110 rows on one live number were these.
  it('drops a row that holds nothing at all', () => {
    const shell = chat({ id: 'a@lid', name: 'Unknown user', timestamp: 0, lastMessage: undefined });
    expect(withoutEmptyShells([shell])).toEqual([]);
  });

  // The discriminator is the emptiness, never the name — so WhatsApp translating or renaming
  // "Unknown user" cannot quietly turn the filter off, and a real chat that happens to carry that
  // name is not thrown away.
  it('keeps a row named "Unknown user" that has a date', () => {
    const real = chat({ id: 'b@lid', name: 'Unknown user', timestamp: 1700000000 });
    expect(withoutEmptyShells([real])).toEqual([real]);
  });

  // The "Mar 10 · No messages yet" rows: genuine conversations whose messages fall outside the
  // ten-day import window. They have a real timestamp and must survive.
  it('keeps a dated chat whose messages are outside the history window', () => {
    const old = chat({ id: 'c@lid', name: '+92 309 4484504', timestamp: 1773146059, lastMessage: undefined });
    expect(withoutEmptyShells([old])).toEqual([old]);
  });

  it('keeps a chat that has a preview but no date', () => {
    const previewOnly = chat({ id: 'd@lid', timestamp: 0, lastMessage: 'hi' });
    expect(withoutEmptyShells([previewOnly])).toEqual([previewOnly]);
  });

  // The ordering that matters: a chat the engine reported empty, which our own stored rows then
  // filled in, must not be dropped. Filtering before the overlay would lose it.
  it('keeps an engine-empty chat that the overlay has already filled in', () => {
    const filled = overlayStoredMessages(
      [chat({ id: 'e@lid', name: 'Unknown user', timestamp: 0, lastMessage: undefined })],
      newestPerChat([row({ chatId: 'e@lid', body: 'we spoke', timestamp: 1700000000 })]),
    );
    expect(withoutEmptyShells(filled)).toHaveLength(1);
    expect(withoutEmptyShells(filled)[0].lastMessage).toBe('we spoke');
  });
});
