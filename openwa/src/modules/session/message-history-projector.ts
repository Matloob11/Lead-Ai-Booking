import { ConfigService } from '@nestjs/config';
import { Repository, In } from 'typeorm';
import { QueryDeepPartialEntity } from 'typeorm';
import { Message, MessageDirection, MessageStatus } from '../message/entities/message.entity';
import { buildMessageMetadata } from './message-row.mapper';
import { ackStatusTransitionFrom, deliveryStatusToMessageStatus } from '../message/message-status.util';
import { resolveFeatureFlags } from '../../config/feature-flags';
import { IncomingMessage } from '../../engine/interfaces/whatsapp-engine.interface';
import { LoggerService } from '../../common/services/logger.service';

/**
 * Persist pre-connection history into the `messages` table for the chat view, without webhook/hook/ws
 * dispatch (it predates the live session). De-duplicated by `waMessageId` so re-syncs never duplicate.
 */
export async function persistHistoryMessages(
  messageRepository: Repository<Message>,
  configService: ConfigService | undefined,
  id: string,
  messages: IncomingMessage[],
  logger: LoggerService,
): Promise<void> {
  const storeEphemeralMessages = resolveFeatureFlags(configService).storeEphemeralMessages;
  const byId = new Map<string, IncomingMessage>();
  for (const m of messages) {
    // Need an id to de-dup; chatId/from/to are NOT NULL; status/story posts aren't chats.
    if (!m.id || m.isStatusBroadcast || !m.chatId || !m.from || !m.to) {
      continue;
    }
    // A7: group history is not imported. These are personal handsets and their
    // groups are the owner's own — family, neighbours, trade chatter — none of
    // it the company's work, and an import that pulls it puts other people's
    // conversations in front of an agent and in our database. Dropped here
    // rather than only hidden in the list, because "do not fetch it" was the
    // ask: what is never written cannot leak later through a search, an export,
    // or a screen nobody thought to filter.
    if (m.chatId.endsWith('@g.us')) {
      continue;
    }
    // A7: nor WhatsApp's own notices about the conversation — encryption changes, "X was added",
    // protocol housekeeping. The live path refuses the same thing in message-projector; an import
    // that took them anyway would fill a fresh chat list with entries nobody ever wrote to.
    if (m.type === 'system') {
      continue;
    }
    // Mirror the live onMessage guard: skip disappearing messages when the operator opted out, so a
    // history backfill can't bypass STORE_EPHEMERAL_MESSAGES=false. No-op when the flag is at its
    // default (true); only a message with a positive timer is dropped, never a regular one.
    if (!storeEphemeralMessages && (m.ephemeralDuration ?? 0) > 0) {
      continue;
    }
    byId.set(m.id, m);
  }
  if (byId.size === 0) {
    return;
  }
  // Chunk the dedup query: a batch can be thousands, past SQLite's bound-variable limit for IN (...).
  const ids = [...byId.keys()];
  const CHUNK = 400;
  let inserted = 0;
  for (let i = 0; i < ids.length; i += CHUNK) {
    const chunkIds = ids.slice(i, i + CHUNK);
    const existing = await messageRepository.find({
      where: { sessionId: id, waMessageId: In(chunkIds) },
      select: { waMessageId: true },
    });
    const seen = new Set(existing.map(r => r.waMessageId));

    // A row we already hold is not left alone: its tick may have moved while nobody was listening.
    // `message_ack` fires once, when it happens, and is never replayed — so an ack that landed while
    // the gateway was down, or before the row was ever written, is lost for good unless it is read
    // back off the handset like this. The insert below uses orIgnore and would skip these entirely.
    await advanceSeenDeliveryStatus(
      chunkIds.filter(x => seen.has(x)).map(x => byId.get(x)!),
      id,
      messageRepository,
      logger,
    );

    const rows = chunkIds
      .filter(x => !seen.has(x))
      .map(x => {
        const m = byId.get(x)!;
        const metadata = buildMessageMetadata(m, true);
        const row = messageRepository.create({
          sessionId: id,
          waMessageId: m.id,
          chatId: m.chatId,
          // Group poster for inbound rows only — the account's own backfilled group messages must
          // not carry author (the column's contract is "null on outgoing echoes").
          author: m.fromMe ? undefined : m.author,
          from: m.from,
          to: m.to,
          body: m.body,
          type: m.type,
          direction: m.fromMe ? MessageDirection.OUTGOING : MessageDirection.INCOMING,
          timestamp: m.timestamp,
          // The state WhatsApp itself is holding, where it gave us one. `SENT` was written for every
          // row regardless, so an imported message the customer had read two weeks ago still showed
          // one tick — 506 of 520 outbound rows on the live account, against two blue ticks on the
          // handset. A live `message_ack` never fixes them: the event fires once, when it happens,
          // and is not replayed for anything already sent.
          //
          // Inbound rows keep SENT: an inbound message's ack describes the *sender's* copy, and the
          // column on our side means "what happened to the thing we sent".
          status: (m.fromMe && m.deliveryStatus && deliveryStatusToMessageStatus(m.deliveryStatus)) || MessageStatus.SENT,
          metadata,
        });
        // The chat panel orders by createdAt; stamp the real time so history sorts correctly.
        if (m.timestamp) {
          row.createdAt = new Date(m.timestamp * 1000);
        }
        return row;
      });
    if (rows.length) {
      // Insert-or-ignore: a live onMessage insert can land between the `seen` SELECT above and this
      // write, colliding on UNIQUE(sessionId, waMessageId). orIgnore skips the collision instead of
      // throwing and aborting the whole batch (history is best-effort, persist-never-dispatch).
      await messageRepository
        .createQueryBuilder()
        .insert()
        .values(rows as unknown as QueryDeepPartialEntity<Message>[])
        .orIgnore()
        .execute();
      inserted += rows.length;
    }
  }
  if (inserted) {
    logger.log(`Persisted ${inserted} history message(s)`, {
      sessionId: id,
      inserted,
      action: 'history_messages_persisted',
    });
  }
}

/**
 * Move an already-stored message's delivery status forward to what the handset now says.
 *
 * `message_ack` is a live event: it fires once, when the tick moves, and WhatsApp never replays it.
 * So every ack that landed while this gateway was restarting, or before the row existed at all, is
 * simply gone — and the row sits at `sent` for ever while the phone shows two blue ticks. Reading
 * the state back off the message during a history import is the only second chance there is.
 *
 * **Forward only**, through the same guard the live ack path uses: `ackStatusTransitionFrom` names
 * the statuses a transition may advance from, so a stale copy of a message can never pull a `read`
 * row back to `delivered`. That guard is in the WHERE clause rather than in a read-then-write, so a
 * live ack arriving mid-import cannot be overwritten by a slower one from here.
 *
 * Grouped by target status so a batch costs one UPDATE per distinct status — three at most — instead
 * of one per message. Best-effort throughout: a tick that failed to move is not a reason to abandon
 * an import that is otherwise storing conversations.
 */
async function advanceSeenDeliveryStatus(
  seen: IncomingMessage[],
  id: string,
  messageRepository: Repository<Message>,
  logger: LoggerService,
): Promise<void> {
  // Only our own messages carry a delivery state that means anything on this side: an inbound
  // message's ack describes the sender's copy of it, not ours.
  const byTarget = new Map<MessageStatus, string[]>();
  for (const m of seen) {
    if (!m.fromMe || !m.id || !m.deliveryStatus) continue;
    const target = deliveryStatusToMessageStatus(m.deliveryStatus);
    // null for pending/sent — already at or below where the row starts, so there is nothing to move.
    if (!target) continue;
    const ids = byTarget.get(target);
    if (ids) ids.push(m.id);
    else byTarget.set(target, [m.id]);
  }
  if (byTarget.size === 0) return;

  let advanced = 0;
  for (const [target, ids] of byTarget) {
    try {
      const result = await messageRepository
        .createQueryBuilder()
        .update(Message)
        .set({ status: target })
        .where('sessionId = :id', { id })
        .andWhere('waMessageId IN (:...ids)', { ids })
        .andWhere('status IN (:...from)', { from: ackStatusTransitionFrom(target) })
        .execute();
      advanced += result.affected ?? 0;
    } catch (error) {
      logger.warn('Could not advance history delivery statuses', {
        sessionId: id,
        target,
        error: error instanceof Error ? error.message : String(error),
        action: 'history_ack_reconcile_failed',
      });
    }
  }

  if (advanced) {
    logger.log(`Advanced ${advanced} message tick(s) to what the handset reports`, {
      sessionId: id,
      advanced,
      action: 'history_ack_reconciled',
    });
  }
}
