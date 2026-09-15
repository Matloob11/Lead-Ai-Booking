import { BadRequestException, ForbiddenException, Injectable, NotFoundException, Optional } from '@nestjs/common';
import { InjectRepository } from '@nestjs/typeorm';
import { createHash, timingSafeEqual } from 'crypto';
import { In, Repository } from 'typeorm';
import { createLogger } from '../../common/services/logger.service';
import { LidMapping } from '../../engine/identity/lid-mapping.entity';
import { LidMappingStoreService } from '../../engine/identity/lid-mapping-store.service';
import { Message, MessageDirection } from '../message/entities/message.entity';
import { Session } from '../session/entities/session.entity';
import { BitrixLeadClient } from './bitrix-lead.client';
import { OpenAiHealthClient } from './openai-health.client';
import { ChatLead, ConversationColour } from './entities/chat-lead.entity';
import {
  CHAT_FIELD_CHARS,
  CLASSIFY_MSG_CHARS,
  COLOUR_LIGHT,
  HISTORY_COMMENT_BATCH,
  RECLASSIFY_EVERY_N,
  type HealthJobData,
} from './conversation-health.constants';
import { formatChatLine, formatThreadForBitrixField } from './conversation-health.format';
import { digitsOnly, isGroupOrNewsletterChat, resolveChatPhone } from './conversation-health.phone';

export interface HealthSummary {
  red: number;
  pink: number;
  yellow: number;
  white: number;
  green: number;
  unclassified: number;
  total: number;
}

export interface HealthListRow {
  sessionId: string;
  sessionName: string;
  chatId: string;
  phone: string | null;
  name: string | null;
  colour: ConversationColour | null;
  bitrixLeadId: string;
  leadUrl: string;
}

@Injectable()
export class ConversationHealthService {
  private readonly logger = createLogger('ConversationHealth');

  constructor(
    @InjectRepository(ChatLead, 'data')
    private readonly chatLeadRepo: Repository<ChatLead>,
    @InjectRepository(Message, 'data')
    private readonly messageRepo: Repository<Message>,
    @InjectRepository(Session, 'data')
    private readonly sessionRepo: Repository<Session>,
    @InjectRepository(LidMapping, 'data')
    private readonly lidRepo: Repository<LidMapping>,
    private readonly bitrix: BitrixLeadClient,
    private readonly openai: OpenAiHealthClient,
    @Optional() private readonly lidStore?: LidMappingStoreService,
  ) {}

  private scopedWhere(allowedSessions: string[] | null | undefined): Record<string, unknown> {
    if (allowedSessions == null || allowedSessions.length === 0) return {};
    return { sessionId: In(allowedSessions) };
  }

  async summary(allowedSessions: string[] | null | undefined): Promise<HealthSummary> {
    const where = this.scopedWhere(allowedSessions);
    const rows = await this.chatLeadRepo.find({ where, select: { colour: true } });
    const out: HealthSummary = { red: 0, pink: 0, yellow: 0, white: 0, green: 0, unclassified: 0, total: rows.length };
    for (const row of rows) {
      switch (row.colour) {
        case 'red':
        case 'pink':
        case 'yellow':
        case 'white':
        case 'green':
          out[row.colour] += 1;
          break;
        default:
          out.unclassified += 1;
      }
    }
    return out;
  }

  async listByColour(
    colour: ConversationColour,
    allowedSessions: string[] | null | undefined,
  ): Promise<HealthListRow[]> {
    const where = { ...this.scopedWhere(allowedSessions), colour };
    const leads = await this.chatLeadRepo.find({ where, order: { updatedAt: 'DESC' }, take: 200 });
    const sessionIds = [...new Set(leads.map(l => l.sessionId))];
    const sessions = sessionIds.length
      ? await this.sessionRepo.find({ where: { id: In(sessionIds) }, select: { id: true, name: true } })
      : [];
    const nameById = new Map(sessions.map(s => [s.id, s.name]));
    return leads.map(l => ({
      sessionId: l.sessionId,
      sessionName: nameById.get(l.sessionId) || l.sessionId.slice(0, 8),
      chatId: l.chatId,
      phone: l.phone ?? null,
      name: l.chatName ?? null,
      colour: l.colour ?? null,
      bitrixLeadId: l.bitrixLeadId,
      leadUrl: this.bitrix.entityUrl(l.bitrixLeadId, l.bitrixEntityType || 'lead'),
    }));
  }

  async getLeadForChat(
    sessionId: string,
    chatId: string,
  ): Promise<{ bitrixLeadId: string; leadUrl: string; colour: ConversationColour | null } | null> {
    const row = await this.chatLeadRepo.findOne({ where: { sessionId, chatId } });
    if (!row) return null;
    return {
      bitrixLeadId: row.bitrixLeadId,
      leadUrl: this.bitrix.entityUrl(row.bitrixLeadId, row.bitrixEntityType || 'lead'),
      colour: row.colour ?? null,
    };
  }

  private entityTypeOf(lead: ChatLead): string {
    return lead.bitrixEntityType || 'lead';
  }

  async processJob(job: HealthJobData): Promise<void> {
    if (!this.bitrix.enabled()) return;
    if (isGroupOrNewsletterChat(job.chatId)) return;

    if (job.kind === 'backfill_chat') {
      await this.backfillChat(job.sessionId, job.chatId, job.chatName);
      return;
    }

    if (job.kind === 'reclassify_chat') {
      await this.reclassifyChat(job.sessionId, job.chatId);
      return;
    }

    await this.mirrorLiveMessage(job);
  }

  private async ensureChatLead(
    sessionId: string,
    chatId: string,
    chatName?: string | null,
    phoneHint?: string | null,
  ): Promise<ChatLead | null> {
    const existing = await this.chatLeadRepo.findOne({ where: { sessionId, chatId } });
    if (existing) {
      if (chatName && chatName !== existing.chatName) {
        existing.chatName = chatName;
        await this.chatLeadRepo.save(existing);
      }
      return existing;
    }

    const phone = await this.resolvePhone(chatId, chatName, phoneHint);
    if (!phone) {
      this.logger.warn(`skip lead — no phone for ${chatId}`);
      return null;
    }

    const target = await this.bitrix.findOrCreateLead(phone, chatName || phone);
    const now = new Date();
    const row = this.chatLeadRepo.create({
      sessionId,
      chatId,
      phone,
      chatName: chatName || null,
      bitrixLeadId: target.id,
      bitrixEntityType: target.entityType,
      colour: null,
      messageCountSinceClassify: 0,
      createdAt: now,
      updatedAt: now,
    });
    try {
      const saved = await this.chatLeadRepo.save(row);
      this.logger.log(
        `chat_lead saved session=${sessionId} chat=${chatId} bitrix=${target.id} type=${target.entityType} kind=${target.kind}`,
      );
      return saved;
    } catch (err) {
      this.logger.warn(`chat_lead save failed: ${String(err)}`);
      // Unique race — reload
      return this.chatLeadRepo.findOne({ where: { sessionId, chatId } });
    }
  }

  private async mirrorLiveMessage(job: HealthJobData): Promise<void> {
    const lead = await this.ensureChatLead(job.sessionId, job.chatId, job.chatName, job.phoneHint);
    if (!lead) return;

    const who = job.fromMe ? 'AGENT' : 'CLIENT';
    let body = (job.body || '').trim();
    if (!body) body = `[${job.type || 'message'}]`;

    // Voice: try Whisper when body is empty/placeholder and we have media in DB metadata
    if ((job.type === 'ptt' || job.type === 'audio') && this.openai.enabled()) {
      const transcript = await this.maybeTranscribeMessage(job.sessionId, job.messageId);
      if (transcript) body = `[voice] ${transcript}`;
    }

    const comment = `[WA] ${who}: ${body}`.slice(0, 65000);
    const entityType = this.entityTypeOf(lead);
    await this.bitrix.addTimelineComment(lead.bitrixLeadId, comment, entityType);

    const thread = await this.buildThreadText(job.sessionId, job.chatId);
    await this.bitrix.updateFields(
      lead.bitrixLeadId,
      { chatText: formatThreadForBitrixField(thread, CHAT_FIELD_CHARS) },
      entityType,
    );

    lead.messageCountSinceClassify = (lead.messageCountSinceClassify || 0) + 1;
    lead.lastSyncedMessageId = job.messageId || lead.lastSyncedMessageId;
    await this.chatLeadRepo.save(lead);

    if (lead.colourLocked) return;

    const needsClassify = !lead.colour || lead.messageCountSinceClassify >= RECLASSIFY_EVERY_N;
    if (needsClassify && this.openai.enabled()) {
      await this.classifyAndWrite(lead, thread);
    }
  }

  /**
   * Admin allow-list: RED → GREEN after override password. Locks colour so AI
   * will not flip it back on the next reclassify window.
   */
  async allowRedAsGreen(
    sessionId: string,
    chatId: string,
    password: string,
    allowedSessions: string[] | null | undefined,
  ): Promise<HealthListRow> {
    this.assertOverridePassword(password);

    if (allowedSessions != null && allowedSessions.length > 0 && !allowedSessions.includes(sessionId)) {
      throw new NotFoundException('Chat lead not found');
    }

    const lead = await this.chatLeadRepo.findOne({ where: { sessionId, chatId } });
    if (!lead) throw new NotFoundException('Chat lead not found');
    if (lead.colour !== 'red') {
      throw new BadRequestException('Only RED chats can be allowed as green');
    }

    const reason = 'Admin allowed this chat (override). Treated as clean / green.';
    const monitor = this.bitrix.buildMonitorText('green', reason, 'admin', '', lead.phone || 'unknown', [
      'admin_override',
    ]);
    const entityType = this.entityTypeOf(lead);
    await this.bitrix.updateFields(
      lead.bitrixLeadId,
      { colour: 'green', monitorText: monitor },
      entityType,
    );
    await this.bitrix.addTimelineComment(
      lead.bitrixLeadId,
      `[AI Monitor] ${COLOUR_LIGHT.green}\nReason: ${reason}\nFlags: admin_override`,
      entityType,
    );

    lead.colour = 'green';
    lead.colourLocked = true;
    lead.messageCountSinceClassify = 0;
    lead.lastClassifiedAt = new Date();
    await this.chatLeadRepo.save(lead);

    const session = await this.sessionRepo.findOne({
      where: { id: lead.sessionId },
      select: { id: true, name: true },
    });
    return {
      sessionId: lead.sessionId,
      sessionName: session?.name || lead.sessionId.slice(0, 8),
      chatId: lead.chatId,
      phone: lead.phone ?? null,
      name: lead.chatName ?? null,
      colour: 'green',
      bitrixLeadId: lead.bitrixLeadId,
      leadUrl: this.bitrix.entityUrl(lead.bitrixLeadId, entityType),
    };
  }

  private assertOverridePassword(password: string): void {
    const expected = process.env.CONVERSATION_HEALTH_OVERRIDE_PASSWORD || '222007';
    const a = createHash('sha256').update(String(password ?? '')).digest();
    const b = createHash('sha256').update(String(expected)).digest();
    // 403 (not 401): dashboard treats 401 as a dead API key and forces logout.
    if (!timingSafeEqual(a, b)) {
      throw new ForbiddenException('Invalid admin password');
    }
  }

  private async backfillChat(sessionId: string, chatId: string, chatName?: string | null): Promise<void> {
    const lead = await this.ensureChatLead(sessionId, chatId, chatName);
    if (!lead) return;

    const messages = await this.messageRepo.find({
      where: { sessionId, chatId },
      order: { timestamp: 'ASC' },
      take: 200,
    });
    if (!messages.length) return;

    // Batch history into timeline comments
    for (let i = 0; i < messages.length; i += HISTORY_COMMENT_BATCH) {
      const batch = messages.slice(i, i + HISTORY_COMMENT_BATCH);
      const lines = batch.map(m => {
        const who = m.direction === MessageDirection.OUTGOING ? 'AGENT' : 'CLIENT';
        const body = (m.body || '').trim() || `[${m.type || 'message'}]`;
        return formatChatLine(who, body);
      });
      await this.bitrix.addTimelineComment(
        lead.bitrixLeadId,
        `[WA history ${i + 1}-${i + batch.length}]\n${lines.join('\n')}`.slice(0, 65000),
        this.entityTypeOf(lead),
      );
    }

    const thread = await this.buildThreadText(sessionId, chatId);
    await this.bitrix.updateFields(
      lead.bitrixLeadId,
      { chatText: formatThreadForBitrixField(thread, CHAT_FIELD_CHARS) },
      this.entityTypeOf(lead),
    );

    if (this.openai.enabled() && !lead.colourLocked) {
      await this.classifyAndWrite(lead, thread);
    } else {
      lead.messageCountSinceClassify = 0;
      await this.chatLeadRepo.save(lead);
    }
  }

  private async classifyAndWrite(lead: ChatLead, thread: string): Promise<void> {
    if (lead.colourLocked) {
      lead.messageCountSinceClassify = 0;
      await this.chatLeadRepo.save(lead);
      return;
    }
    const session = await this.sessionRepo.findOne({ where: { id: lead.sessionId } });
    const agentName = session?.name || 'agent';
    const agentPhone = digitsOnly(session?.phone || '');
    const client = lead.phone || 'unknown';
    const result = await this.openai.classify(agentName, agentPhone, client, thread.slice(-CLASSIFY_MSG_CHARS));
    const monitor = this.bitrix.buildMonitorText(
      result.category,
      result.reason,
      agentName,
      agentPhone,
      client,
      result.flags,
    );
    const entityType = this.entityTypeOf(lead);
    await this.bitrix.updateFields(
      lead.bitrixLeadId,
      {
        colour: result.category,
        monitorText: monitor,
        chatText: formatThreadForBitrixField(thread, CHAT_FIELD_CHARS),
      },
      entityType,
    );
    await this.bitrix.addTimelineComment(
      lead.bitrixLeadId,
      `[AI Monitor] ${COLOUR_LIGHT[result.category]}\nReason: ${result.reason}\nFlags: ${
        result.flags.length ? result.flags.join(', ') : '-'
      }`,
      entityType,
    );
    lead.colour = result.category;
    lead.messageCountSinceClassify = 0;
    lead.lastClassifiedAt = new Date();
    await this.chatLeadRepo.save(lead);
    this.logger.log(`classified lead=${lead.bitrixLeadId} colour=${result.category}`);
  }

  private async buildThreadText(sessionId: string, chatId: string): Promise<string> {
    const messages = await this.messageRepo.find({
      where: { sessionId, chatId },
      order: { timestamp: 'ASC' },
      take: 120,
    });
    const lines: string[] = [];
    for (const m of messages) {
      if (m.type === 'system' || m.type === 'revoked') continue;
      const who = m.direction === MessageDirection.OUTGOING ? 'AGENT' : 'CLIENT';
      const body = (m.body || '').trim() || `[${m.type || 'message'}]`;
      lines.push(formatChatLine(who, body));
    }
    return lines.join('\n');
  }

  private async maybeTranscribeMessage(sessionId: string, messageId?: string): Promise<string> {
    if (!messageId) return '';
    const msg = await this.messageRepo.findOne({ where: { id: messageId, sessionId } });
    if (!msg?.metadata) return '';
    const media = msg.metadata.media as { data?: string; mimetype?: string } | undefined;
    const b64 = media?.data;
    if (!b64 || typeof b64 !== 'string') return '';
    try {
      const buf = Buffer.from(b64, 'base64');
      const ext = (media?.mimetype || '').includes('mpeg') ? 'mp3' : 'ogg';
      return this.openai.transcribe(buf, `voice.${ext}`);
    } catch {
      return '';
    }
  }

  /** Resolve E.164-ish digits from JID, name, LID map cache, then lid_mappings table. */
  private async resolvePhone(
    chatId: string,
    chatName?: string | null,
    phoneHint?: string | null,
  ): Promise<string | null> {
    const hint = phoneHint ? digitsOnly(phoneHint) : '';
    if (hint.length >= 8 && hint.length <= 15) return hint;

    const fromJid = resolveChatPhone(chatId, chatName);
    if (fromJid) return fromJid;

    if (!chatId.toLowerCase().includes('@lid')) return null;
    // WA sometimes uses `lid:device@lid` — mapping table stores the bare lid.
    const local = (chatId.split('@')[0] || '').trim();
    const lidKeys = [local];
    if (local.includes(':')) lidKeys.push(local.split(':')[0]!);

    for (const key of lidKeys) {
      if (!key) continue;
      const cached = this.lidStore?.getCached(key);
      if (typeof cached === 'string' && cached) {
        const d = digitsOnly(cached);
        if (d.length >= 8 && d.length <= 15) return d;
      }
      try {
        const row = await this.lidRepo.findOne({ where: { lid: key } });
        if (row?.phone) {
          const d = digitsOnly(row.phone);
          if (d.length >= 8 && d.length <= 15) return d;
        }
      } catch {
        /* table missing / unread — skip */
      }
    }
    return null;
  }

  /** Collect individual chats from DB messages for backfill enqueue. */
  async listBackfillTargets(sessionIds?: string[]): Promise<HealthJobData[]> {
    const qb = this.messageRepo
      .createQueryBuilder('m')
      .select('m.sessionId', 'sessionId')
      .addSelect('m.chatId', 'chatId')
      .addSelect('MAX(m.chatName)', 'chatName')
      .groupBy('m.sessionId')
      .addGroupBy('m.chatId');
    if (sessionIds?.length) {
      qb.andWhere('m.sessionId IN (:...sessionIds)', { sessionIds });
    }
    const rows = await qb.getRawMany<{ sessionId: string; chatId: string; chatName: string | null }>();
    return rows
      .filter(r => !isGroupOrNewsletterChat(r.chatId))
      .map(r => ({
        kind: 'backfill_chat' as const,
        sessionId: r.sessionId,
        chatId: r.chatId,
        chatName: r.chatName,
      }));
  }

  /** Unlocked RED rows — candidates for false-RED cleanup via AI reclassify. */
  async listFalseRedTargets(sessionIds?: string[]): Promise<HealthJobData[]> {
    const where = {
      colour: 'red' as const,
      colourLocked: false,
      ...(sessionIds?.length ? { sessionId: In(sessionIds) } : {}),
    };
    const leads = await this.chatLeadRepo.find({
      where,
      select: { sessionId: true, chatId: true, chatName: true },
      take: 500,
    });
    return leads
      .filter(l => !isGroupOrNewsletterChat(l.chatId))
      .map(l => ({
        kind: 'reclassify_chat' as const,
        sessionId: l.sessionId,
        chatId: l.chatId,
        chatName: l.chatName,
      }));
  }

  private async reclassifyChat(sessionId: string, chatId: string): Promise<void> {
    const lead = await this.chatLeadRepo.findOne({ where: { sessionId, chatId } });
    if (!lead || lead.colourLocked) return;
    if (!this.openai.enabled()) return;
    const thread = await this.buildThreadText(sessionId, chatId);
    if (!thread.trim()) return;
    await this.classifyAndWrite(lead, thread);
  }
}
