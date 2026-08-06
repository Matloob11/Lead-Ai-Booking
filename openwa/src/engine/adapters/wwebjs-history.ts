import type { Client } from 'whatsapp-web.js';
import { IncomingMessage } from '../interfaces/whatsapp-engine.interface';
import { buildIncomingMessageBase, RawMessageFields } from './message-mapper';

/**
 * Reading a linked phone's own history back off whatsapp-web.js.
 *
 * Baileys is handed a `messaging-history.set` the moment it connects, so it needs nothing like
 * this. whatsapp-web.js is handed nothing: it reports messages that arrive while it is connected
 * and never mentions the months already sitting on the handset. Without this a number linked today
 * shows an empty chat list beside a phone that has years in it, and a number that spent a fortnight
 * disconnected has a fortnight-shaped hole nobody can see.
 *
 * It asks chat by chat, oldest-bound by `since`, and hands what it finds to a callback in batches.
 * It stores nothing itself — the projector owns that, and the unique index on
 * (sessionId, waMessageId) is what makes reading the same stretch twice cost only the reading.
 */

/** Messages asked for per round, doubling until the cutoff is reached. */
const PAGE_START = 100;

/**
 * Stop paging one chat after this many messages however old they are.
 *
 * A group nobody has muted since 2019 holds a hundred thousand messages, and paging all of them
 * blocks every other chat behind it. This caps the worst chat, not the import.
 */
const PAGE_CAP = 4000;

/** Handed over in batches rather than one list, so a long import is not one huge write at the end. */
const BATCH = 200;

/** A breath between chats, so the handset is not paged flat out. */
const CHAT_PAUSE_MS = 900;

/** And a longer one before starting, so WhatsApp Web finishes its own sync first. */
const SETTLE_MS = 15_000;

/**
 * How long any one call gets before the import gives up on it and moves on.
 *
 * Everything here is a page evaluation and puppeteer puts no time limit on those. When WhatsApp's
 * own code fails to answer — which it does — the await never settles and the loop never reaches its
 * next iteration, so the import stops for ever with no error, no log line and no change of state.
 */
const CHAT_TIMEOUT_MS = 120_000;
const LIST_TIMEOUT_MS = 90_000;

const sleep = (ms: number): Promise<void> => new Promise(resolve => setTimeout(resolve, ms));

/**
 * The promise, or a rejection once the deadline passes.
 *
 * The original is abandoned rather than cancelled — a page evaluation cannot be cancelled — so a
 * hung call still holds its own memory. That is the lesser problem: one leaked evaluation costs a
 * little, one that blocks the loop costs everything behind it.
 */
async function withTimeout<T>(work: Promise<T>, ms: number, what: string): Promise<T> {
  let timer: NodeJS.Timeout | undefined;
  try {
    return await Promise.race([
      work,
      new Promise<never>((_, reject) => {
        timer = setTimeout(() => reject(new Error(`${what} did not answer within ${ms / 1000}s`)), ms);
      }),
    ]);
  } finally {
    if (timer) clearTimeout(timer);
  }
}

/**
 * Whether a chat belongs in the company's record at all.
 *
 * Status posts and newsletters are not conversations, and broadcast lists are one-way. The live
 * path already drops them; applying the same rule here stops the import quietly bringing in what
 * the socket is filtering out.
 */
function wanted(jid: string): boolean {
  if (!jid) return false;
  if (jid === 'status@broadcast' || jid.endsWith('@newsletter') || jid.endsWith('@broadcast')) {
    return false;
  }
  return true;
}

/**
 * Every chat the phone knows about, as bare JIDs.
 *
 * Deliberately not `client.getChats()`. That builds a full model for every chat in one page
 * evaluation — group metadata, contacts, the lot — and a single chat it cannot describe throws,
 * taking the whole list with it. Ids are the one thing a chat always has, so reading only those
 * cannot fail on the contents of any one chat, and the unreadable ones then fail alone, by name,
 * further down.
 *
 * The collection is reached through WhatsApp's own module loader, the way the library reaches it.
 * There is no `window.Store` on current builds.
 */
async function listChatJids(client: Client): Promise<string[]> {
  const page = (client as unknown as { pupPage?: { evaluate: <T>(fn: () => T) => Promise<T> } }).pupPage;
  if (!page) return [];

  return page.evaluate(() => {
    const out: string[] = [];
    const req = (window as unknown as { require?: (m: string) => { Chat: { getModelsArray: () => unknown[] } } }).require;
    if (!req) return out;
    for (const chat of req('WAWebCollections').Chat.getModelsArray()) {
      try {
        const id = (chat as { id?: unknown }).id as
          | string
          | { _serialized?: string; user?: string; server?: string }
          | undefined;
        const jid =
          typeof id === 'string' ? id : id?._serialized || (id?.user && id?.server ? `${id.user}@${id.server}` : '');
        if (jid) out.push(jid);
      } catch {
        // One chat that cannot say what it is called is not the list.
      }
    }
    return out;
  });
}

/** The shape fetchMessages hands back, as much of it as the mapper needs. */
interface RawHistoryMessage extends RawMessageFields {
  timestamp: number;
}

export interface ImportHistoryOptions {
  client: Client;
  /** Read messages sent at or after this instant. */
  since: Date;
  /** Handed each batch. Rejections are logged and the import carries on. */
  emit: (messages: IncomingMessage[]) => void | Promise<void>;
  /** Optional sync progress callback (0..100%). */
  onProgress?: (percent: number) => void | Promise<void>;
  /** False once this engine is no longer the live one, which stops the run where it stands. */
  isLive: () => boolean;
  log?: (message: string) => void;
}

/**
 * Reads `since`..now out of every chat and hands it to `emit` in batches.
 *
 * @returns how many messages were handed over — not how many were stored, which the projector
 *          decides.
 */
export async function importWwebjsHistory({
  client,
  since,
  emit,
  onProgress,
  isLive,
  log = (): void => {},
}: ImportHistoryOptions): Promise<number> {
  // WhatsApp Web is still pulling its own sync down for the first few seconds after ready, and a
  // chat asked for during that window answers with what it has so far rather than what it has.
  await sleep(SETTLE_MS);
  if (!isLive()) return 0;

  const jids = (await withTimeout(listChatJids(client), LIST_TIMEOUT_MS, 'the chat list')).filter(wanted);
  log(`history: ${jids.length} chat(s) to read back to ${since.toISOString()}`);

  const cutoffMs = since.getTime();
  let handed = 0;

  for (let i = 0; i < jids.length; i++) {
    const jid = jids[i];
    // The phone went away mid-import. What was read is already handed over; the watermark is left
    // where it was, so the next connection covers this stretch again.
    if (!isLive()) {
      log(`history: session no longer live — stopping after ${handed} message(s)`);
      return handed;
    }

    // Chats read out of chats to read — the one denominator that is actually known here. Messages
    // would be the truer measure of work and cannot be counted in advance: nothing says how many a
    // chat holds until it has been paged. Capped at 99 so the last chat does not report finished
    // before it has been read; the 100 below is written once the loop is genuinely over.
    try {
      await onProgress?.(Math.min(99, Math.round(((i + 1) / jids.length) * 100)));
    } catch {
      // Reporting progress is not the job. A caller that cannot record it still gets the import.
    }

    try {
      handed += await withTimeout(readChat(client, jid, cutoffMs, emit), CHAT_TIMEOUT_MS, jid);
    } catch (error) {
      // One unreadable chat is not a reason to abandon the other eighty.
      log(`history: could not read ${jid}: ${error instanceof Error ? error.message : String(error)}`);
    }

    await sleep(CHAT_PAUSE_MS);
  }

  try {
    await onProgress?.(100);
  } catch {
    // As above — the caller's bookkeeping, not the import's.
  }

  log(`history: handed over ${handed} message(s) from ${jids.length} chat(s)`);
  return handed;
}

/** One chat, paged back to the cutoff. @returns how many messages it handed over. */
async function readChat(
  client: Client,
  jid: string,
  cutoffMs: number,
  emit: ImportHistoryOptions['emit'],
): Promise<number> {
  const chat = await client.getChatById(jid);
  if (!chat) return 0;

  // Ask for more until the oldest message in hand predates the cutoff, the chat runs out, or the
  // cap says enough. Each round costs only the messages it adds: what has already been paged in
  // stays in the page's own model store, so asking for 200 after 100 loads the second hundred.
  let limit = PAGE_START;
  let messages: unknown[] = [];
  for (;;) {
    messages = await chat.fetchMessages({ limit });
    if (messages.length < limit) break; // the chat has no more to give
    const oldest = Number((messages[0] as { timestamp?: number })?.timestamp ?? 0) * 1000;
    if (oldest && oldest <= cutoffMs) break;
    if (limit >= PAGE_CAP) break;
    limit = Math.min(PAGE_CAP, limit * 2);
  }

  let handed = 0;
  let batch: IncomingMessage[] = [];

  for (const raw of messages as RawHistoryMessage[]) {
    const at = Number(raw?.timestamp ?? 0) * 1000;
    if (at && at < cutoffMs) continue;

    let mapped: IncomingMessage;
    try {
      mapped = buildIncomingMessageBase(raw);
    } catch {
      // A message whose shape the mapper cannot read is one message, not the chat.
      continue;
    }

    // The projector needs an id to de-duplicate on; without one it would insert a fresh row on
    // every run. Media is deliberately not fetched — this is the record of what was said, and the
    // bytes for anything old enough to be in a backfill are mostly no longer served anyway.
    if (!mapped.id) continue;

    batch.push(mapped);
    if (batch.length >= BATCH) {
      await emit(batch);
      handed += batch.length;
      batch = [];
    }
  }

  if (batch.length) {
    await emit(batch);
    handed += batch.length;
  }

  return handed;
}
