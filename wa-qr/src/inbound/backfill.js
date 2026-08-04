/**
 * Reading a linked phone's own history back into the database.
 *
 * A phone arrives with months of conversation already on it and none of it
 * here. That gap is the point: a company number whose history lives only on the
 * handset can be edited by whoever holds the handset, and a thread deleted
 * before anyone read it leaves nothing behind to notice. Everything on the
 * phone when it is linked is imported, and from then on the live socket keeps
 * up. Deleting a message on the phone afterwards does not delete this copy.
 *
 * Two kinds of run, told apart by `history_status`:
 *
 *   first link — six months back, every chat
 *   reconnect  — only from where the last run finished, which is the stretch
 *                the phone spent away
 *
 * The difference matters more than it looks. Re-reading six months on every
 * reconnect would page the whole history out of the handset again each time,
 * over the phone's own connection, for messages already stored — and WhatsApp
 * notices that kind of load.
 *
 * It runs in the background. The panel is usable throughout, live messages
 * arrive normally the whole time, and progress is written to the session row so
 * the screen can say what is happening rather than looking finished while it
 * works.
 */

import pkg from "whatsapp-web.js";
const { PrivateChat, GroupChat } = pkg;

import { onEvent, getClient } from "../sessions/manager.js";
import * as store from "../sessions/store.js";
import { resolveContactWaId } from "./normalise.js";
import { storeMessage } from "./persist.js";
import { processInboundMedia } from "./media.js";
import { config } from "../config.js";
import { q } from "../db.js";

const DAY_MS = 24 * 60 * 60 * 1000;

/** How far back a first import reaches. */
const FULL_HISTORY_MS = 182 * DAY_MS;

/**
 * How far back attachments are actually downloaded.
 *
 * Six months of photographs, voice notes and forwarded video is tens of
 * gigabytes and hours of transfer, and almost none of it is ever opened. Thirty
 * days covers the deal being argued about now — which is what anyone goes
 * looking for — and older messages are still stored, just as a record of what
 * was sent rather than a copy of it.
 */
const MEDIA_WINDOW_MS = 30 * DAY_MS;

/**
 * Overlap on a reconnect run, in case the phone and this server disagree about
 * the clock. Cheap: anything already stored is refused by the unique index on
 * wamid, so the only cost of reading a day twice is reading it twice.
 */
const RECONNECT_OVERLAP_MS = DAY_MS;

/** Messages asked for per round, doubling until the cutoff is reached. */
const PAGE_START = 100;

/**
 * Stop paging one chat after this many messages however old they are.
 *
 * A group nobody has muted since 2019 can hold a hundred thousand messages, and
 * paging through all of them blocks every other chat behind it. The cap is a
 * limit on the worst chat, not on the import.
 */
const PAGE_CAP = 8000;

/** A breath between chats, so the phone is not paged flat out. */
const CHAT_PAUSE_MS = 1200;

/** And a longer one before starting, so WhatsApp Web finishes its own sync. */
const SETTLE_MS = 20_000;

const running = new Set();

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/** Starts importing whenever a phone becomes ready, and never twice at once. */
export function startHistoryImport() {
  onEvent((type, payload) => {
    if (type !== "status" || payload?.status !== "ready") return;
    const sessionId = Number(payload.sessionId);

    // Not awaited: `ready` is emitted from the session manager's own event
    // handler, and an import takes minutes. Anything that waited on this would
    // be holding up the socket that delivers live messages.
    runBackfill(sessionId).catch((error) =>
      console.error(`[wa-qr] history import for #${sessionId} failed:`, error)
    );
  });
  console.info("[wa-qr] history import armed");
}

/**
 * Imports one session's history.
 *
 * Safe to call again at any time — a run already in flight is left alone, and
 * everything it writes is refused by the unique index the second time round, so
 * an interrupted run simply resumes by repeating itself.
 */
export async function runBackfill(sessionId) {
  const id = Number(sessionId);
  if (running.has(id)) return;
  running.add(id);

  try {
    await sleep(SETTLE_MS);

    const session = await store.getSessionById(id);
    if (!session) return;

    const client = getClient(id);
    if (!client) {
      console.warn(`[wa-qr] no client for #${id} — history import skipped`);
      return;
    }

    const firstRun = session.history_status !== "done";
    const since = firstRun
      ? new Date(Date.now() - FULL_HISTORY_MS)
      : new Date(
          new Date(session.history_finished_at || session.created_at).getTime() -
            RECONNECT_OVERLAP_MS
        );

    console.info(
      `[wa-qr] history import for #${id} starting — ${firstRun ? "first link" : "catching up"}, ` +
        `back to ${since.toISOString()}`
    );

    await store.updateSession(id, {
      history_status: "running",
      history_error: "",
      history_started_at: new Date(),
      history_chats_done: 0,
      history_chats_total: 0,
    });

    const jids = (await listChatJids(client)).filter(wanted);
    await store.updateSession(id, { history_chats_total: jids.length });
    console.info(`[wa-qr] #${id} has ${jids.length} chat(s) worth importing`);

    let done = 0;
    let stored = 0;

    for (const jid of jids) {
      // The phone went away mid-import. Whatever was read is kept and the row
      // is left short of 'done', so the next connection picks the rest up.
      if (getClient(id) !== client) {
        console.warn(`[wa-qr] #${id} disconnected during import — stopping at ${done} chats`);
        await store.updateSession(id, {
          history_status: "pending",
          history_error: "The phone disconnected while its history was being read.",
        });
        return;
      }

      try {
        stored += await importChat({ client, sessionId: id, jid, since });
      } catch (error) {
        // One unreadable chat is not a reason to abandon the other eighty.
        console.warn(`[wa-qr] could not import ${jid}: ${error.message}`);
      }

      done += 1;
      await store.updateSession(id, {
        history_chats_done: done,
        history_messages: Number(session.history_messages || 0) + stored,
      });
      await sleep(CHAT_PAUSE_MS);
    }

    await retryFailedMedia(client, id);

    await store.updateSession(id, {
      history_status: "done",
      history_finished_at: new Date(),
      history_error: "",
    });
    console.info(`[wa-qr] history import for #${id} finished — ${stored} new message(s) from ${done} chat(s)`);
  } catch (error) {
    console.error(`[wa-qr] history import for #${id} failed:`, error);
    await store
      .updateSession(id, { history_status: "failed", history_error: error.message })
      .catch(() => {});
  } finally {
    running.delete(id);
  }
}

/**
 * A second go at attachments that did not come down.
 *
 * A message and its file are stored separately, and a failed download leaves
 * the message perfectly readable with a qr_media row that holds only the reason
 * it is empty. That is the right shape — losing the message because its
 * photograph would not download would be worse — but it means a fault in
 * downloading is invisible in the thread and permanent without this.
 *
 * There was such a fault, and it caught every attachment this account has ever
 * received: downloadMedia looked the message up by a field this build does not
 * set. The messages are already stored and the unique index will not let the
 * import write them again, so nothing short of asking for the files by name
 * would have recovered them.
 *
 * Only within the media window, and only files that failed — a message stored
 * deliberately without its attachment is not a fault to repair.
 */
async function retryFailedMedia(client, sessionId) {
  const broken = await q(
    `SELECT m.id AS message_id, m.wamid, med.id AS media_id
       FROM qr_message m
       JOIN qr_media med ON med.id = m.media_id
       JOIN qr_conversation c ON c.id = m.conversation_id
      WHERE c.session_id = $1
        AND med.downloaded = FALSE
        AND med.download_error <> ''
        AND m.created_at >= now() - ($2::bigint || ' milliseconds')::interval
        AND m.wamid IS NOT NULL
      ORDER BY m.created_at DESC
      LIMIT 2000`,
    [sessionId, MEDIA_WINDOW_MS]
  );

  if (!broken.length) return;
  console.info(`[wa-qr] #${sessionId} retrying ${broken.length} attachment(s) that did not download`);

  let recovered = 0;
  for (const row of broken) {
    try {
      const message = await client.getMessageById(row.wamid);
      if (!message?.hasMedia) continue;

      const media = await processInboundMedia(message);
      if (!media?.downloaded) continue;

      // Pointed at the new row rather than repairing the old one: the failed
      // row is the record that this file once could not be fetched, and that is
      // worth keeping next to the one that says it eventually could.
      await q(`UPDATE qr_message SET media_id = $1 WHERE id = $2`, [media.id, row.message_id]);
      recovered += 1;
    } catch (error) {
      console.warn(`[wa-qr] could not recover media for ${row.wamid}: ${error.message}`);
    }
  }

  console.info(`[wa-qr] #${sessionId} recovered ${recovered} of ${broken.length} attachment(s)`);
}

/**
 * Every chat the phone knows about, as bare JIDs.
 *
 * Deliberately not client.getChats(). That builds a full model for every chat
 * in one page evaluation — group metadata, contacts, the lot — and one chat it
 * cannot describe throws, taking the whole list with it. On this account it did:
 * the first import died on `r: r`, a minified error from inside WhatsApp's own
 * code, having read nothing at all.
 *
 * Ids are the one thing a chat always has. Reading only those cannot fail on
 * the contents of any single chat, and the ones that turn out to be unreadable
 * then fail alone, by name, further down.
 *
 * The collection is reached the way the library itself reaches it, through
 * WhatsApp's own module loader. There is no `window.Store` on this build —
 * asking for one throws before a single chat has been looked at.
 */
async function listChatJids(client) {
  return client.pupPage.evaluate(() => {
    const out = [];
    for (const chat of window.require("WAWebCollections").Chat.getModelsArray()) {
      try {
        const id = chat.id;
        const jid =
          typeof id === "string" ? id : id._serialized || (id.user && `${id.user}@${id.server}`);
        if (jid) out.push(jid);
      } catch {
        // One chat that cannot even say what it is called is not the list.
      }
    }
    return out;
  });
}

/**
 * Whether a chat belongs in the company's record at all.
 *
 * The same rule the live path applies, for the same reason: the phone belongs
 * to a person and brings their family and neighbourhood threads with it, and
 * none of that is the company's to store. Applying it here as well means the
 * import does not quietly bring in what the socket is filtering out.
 */
function wanted(jid) {
  if (!jid) return false;
  if (jid.includes("status@broadcast") || jid.endsWith("@newsletter") || jid.endsWith("@broadcast")) {
    return false;
  }
  if (config.ignoreGroups && jid.endsWith("@g.us")) return false;
  return true;
}

/**
 * A Chat good enough to read messages out of, without asking WhatsApp to
 * describe it first.
 *
 * getChatById builds a full model, and on this account that fails for every
 * chat addressed by LinkedID — 161 of them in the first run, all with the same
 * one-letter minified error and no chat imported. Which is most of them:
 * WhatsApp now addresses people by LinkedID, and getChatById would leave the
 * import able to read only the older, plainly-addressed half of the book.
 *
 * fetchMessages needs exactly two things off a Chat — the client, and
 * `id._serialized` — so those are what it gets. Everything the full model adds
 * is about presentation, which this file does not do.
 */
function chatFor(client, jid) {
  const [user, server] = jid.split("@");
  const Klass = server === "g.us" ? GroupChat : PrivateChat;
  return new Klass(client, {
    id: { _serialized: jid, user, server },
    formattedTitle: "",
    isGroup: server === "g.us",
  });
}

/** @returns {Promise<number>} how many messages this chat actually added */
async function importChat({ client, sessionId, jid, since }) {
  // The real model when WhatsApp will give one — it carries the chat's title,
  // which is the customer's name — and a bare one when it will not.
  const chat = (await client.getChatById(jid).catch(() => null)) || chatFor(client, jid);

  // fetchMessages reads `chat.id._serialized` directly, and on this build that
  // field can be missing — the id arrives under a minified name. Without this
  // the library asks the page for the chat called `undefined` and gets nothing
  // back, silently, for every chat.
  if (chat.id && typeof chat.id._serialized !== "string") chat.id._serialized = jid;

  const who = await resolveContactWaId({ client, jid });
  if (!who.waId) {
    console.warn(`[wa-qr] skipping ${jid} — no number could be resolved for it`);
    return 0;
  }
  const contact = { waId: who.waId, name: chat.name || "" };

  const cutoffMs = since.getTime();
  const mediaCutoffMs = Date.now() - MEDIA_WINDOW_MS;

  // Ask for more until the oldest message in hand predates the cutoff, the chat
  // runs out, or the cap says enough. Each round costs only the messages it
  // adds: what has already been paged in stays in the page's own model store,
  // so asking for 200 after 100 loads the second hundred, not both.
  let limit = PAGE_START;
  let messages = [];
  while (true) {
    messages = await chat.fetchMessages({ limit });
    if (messages.length < limit) break; // the chat has no more to give
    const oldest = Number(messages[0]?.timestamp || 0) * 1000;
    if (oldest && oldest <= cutoffMs) break;
    if (limit >= PAGE_CAP) {
      console.info(`[wa-qr] ${jid} reached the ${PAGE_CAP}-message cap; older messages left on the phone`);
      break;
    }
    limit = Math.min(PAGE_CAP, limit * 2);
  }

  let stored = 0;
  for (const message of messages) {
    const at = Number(message.timestamp || 0) * 1000;
    if (at && at < cutoffMs) continue;

    const result = await storeMessage(sessionId, message, {
      historical: true,
      withMedia: at >= mediaCutoffMs,
      contact,
    });
    if (result?.stored) stored += 1;
  }

  return stored;
}
