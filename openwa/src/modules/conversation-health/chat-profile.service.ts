import { Injectable, NotFoundException } from '@nestjs/common';
import { InjectRepository } from '@nestjs/typeorm';
import { In, Repository } from 'typeorm';
import { Message, MessageDirection, MessageStatus } from '../message/entities/message.entity';
import { Session } from '../session/entities/session.entity';
import { ChatProfile } from './entities/chat-profile.entity';
import { ChatLead, type ConversationColour } from './entities/chat-lead.entity';
import { ConversationHealthService } from './conversation-health.service';

const MEDIA_TYPES = ['image', 'video', 'audio', 'voice', 'document', 'sticker'] as const;

export interface ChatProfileMediaItem {
  id: string;
  type: string;
  createdAt: string;
  hasMedia: boolean;
}

export interface ChatProfileView {
  sessionId: string;
  chatId: string;
  displayName: string | null;
  notes: string;
  pinned: boolean;
  waName: string | null;
  phone: string | null;
  session: { id: string; name: string; phone: string | null; status: string };
  lead: {
    bitrixLeadId: string;
    leadUrl: string;
    colour: ConversationColour | null;
  } | null;
  stats: { total: number; inbound: number; outbound: number; failed: number };
  media: ChatProfileMediaItem[];
}

export interface PatchChatProfileInput {
  displayName?: string | null;
  notes?: string | null;
  pinned?: boolean;
}

@Injectable()
export class ChatProfileService {
  constructor(
    @InjectRepository(ChatProfile, 'data')
    private readonly profileRepo: Repository<ChatProfile>,
    @InjectRepository(ChatLead, 'data')
    private readonly chatLeadRepo: Repository<ChatLead>,
    @InjectRepository(Message, 'data')
    private readonly messageRepo: Repository<Message>,
    @InjectRepository(Session, 'data')
    private readonly sessionRepo: Repository<Session>,
    private readonly health: ConversationHealthService,
  ) {}

  async listDisplayNames(sessionId: string): Promise<{
    names: Record<string, string>;
    pinned: string[];
  }> {
    const rows = await this.profileRepo.find({
      where: { sessionId },
      select: { chatId: true, displayName: true, pinned: true },
    });
    const names: Record<string, string> = {};
    const pinned: string[] = [];
    for (const row of rows) {
      const name = row.displayName?.trim();
      if (name) names[row.chatId] = name;
      if (row.pinned) pinned.push(row.chatId);
    }
    return { names, pinned };
  }

  async getProfile(sessionId: string, chatId: string): Promise<ChatProfileView> {
    const session = await this.sessionRepo.findOne({ where: { id: sessionId } });
    if (!session) throw new NotFoundException(`Session ${sessionId} not found`);

    const [profile, lead, leadRow, waName, stats, media, phone] = await Promise.all([
      this.profileRepo.findOne({ where: { sessionId, chatId } }),
      this.health.getLeadForChat(sessionId, chatId),
      this.chatLeadRepo.findOne({ where: { sessionId, chatId }, select: { phone: true } }),
      this.latestWaName(sessionId, chatId),
      this.statsForChat(sessionId, chatId),
      this.recentMedia(sessionId, chatId),
      this.resolvePhoneHint(sessionId, chatId),
    ]);

    return {
      sessionId,
      chatId,
      displayName: profile?.displayName?.trim() || null,
      notes: profile?.notes ?? '',
      pinned: Boolean(profile?.pinned),
      waName,
      phone: leadRow?.phone?.trim() || phone,
      session: {
        id: session.id,
        name: session.name,
        phone: session.phone,
        status: session.status,
      },
      lead,
      stats,
      media,
    };
  }

  async patchProfile(sessionId: string, chatId: string, input: PatchChatProfileInput): Promise<ChatProfileView> {
    const session = await this.sessionRepo.findOne({ where: { id: sessionId } });
    if (!session) throw new NotFoundException(`Session ${sessionId} not found`);

    // CreateDateColumn + DateTransformer writes null on SQLite INSERT unless
    // we set timestamps ourselves (same pattern as chat_leads).
    const now = new Date();
    let profile = await this.profileRepo.findOne({ where: { sessionId, chatId } });
    if (!profile) {
      profile = this.profileRepo.create({
        sessionId,
        chatId,
        displayName: null,
        notes: null,
        pinned: false,
        createdAt: now,
        updatedAt: now,
      });
    }

    if (input.displayName !== undefined) {
      const trimmed = (input.displayName ?? '').trim();
      profile.displayName = trimmed || null;
    }
    if (input.notes !== undefined) {
      profile.notes = input.notes ?? '';
    }
    if (input.pinned !== undefined) {
      profile.pinned = Boolean(input.pinned);
    }
    profile.updatedAt = now;

    await this.profileRepo.save(profile);
    return this.getProfile(sessionId, chatId);
  }

  private async latestWaName(sessionId: string, chatId: string): Promise<string | null> {
    const row = await this.messageRepo.findOne({
      where: { sessionId, chatId },
      order: { timestamp: 'DESC' },
      select: { chatName: true },
    });
    const name = row?.chatName?.trim();
    return name || null;
  }

  private async resolvePhoneHint(sessionId: string, chatId: string): Promise<string | null> {
    const withPhone = await this.messageRepo.find({
      where: { sessionId, chatId },
      order: { timestamp: 'DESC' },
      take: 40,
      select: { metadata: true },
    });
    for (const msg of withPhone) {
      const phone = msg.metadata?.['senderPhone'];
      if (typeof phone === 'string' && phone.trim()) return phone.trim();
    }
    if (chatId.endsWith('@c.us') || chatId.endsWith('@s.whatsapp.net')) {
      const user = chatId.split('@')[0] ?? '';
      if (/^\d{5,}$/.test(user)) return user;
    }
    return null;
  }

  private async statsForChat(
    sessionId: string,
    chatId: string,
  ): Promise<ChatProfileView['stats']> {
    const base = this.messageRepo
      .createQueryBuilder('m')
      .where('m.sessionId = :sessionId', { sessionId })
      .andWhere('m.chatId = :chatId', { chatId });
    const [total, inbound, outbound, failed] = await Promise.all([
      base.clone().getCount(),
      base.clone().andWhere('m.direction = :d', { d: MessageDirection.INCOMING }).getCount(),
      base.clone().andWhere('m.direction = :d', { d: MessageDirection.OUTGOING }).getCount(),
      base.clone().andWhere('m.status = :s', { s: MessageStatus.FAILED }).getCount(),
    ]);
    return { total, inbound, outbound, failed };
  }

  private async recentMedia(sessionId: string, chatId: string): Promise<ChatProfileMediaItem[]> {
    const rows = await this.messageRepo.find({
      where: { sessionId, chatId, type: In([...MEDIA_TYPES]) },
      order: { timestamp: 'DESC' },
      take: 72,
      select: { id: true, type: true, createdAt: true, mediaPath: true, metadata: true },
    });
    return rows.map(row => {
      const metaMedia = row.metadata?.['media'];
      const hasInline =
        Boolean(row.mediaPath) ||
        (metaMedia != null && typeof metaMedia === 'object' && Boolean((metaMedia as { data?: string }).data));
      return {
        id: row.id,
        type: row.type,
        createdAt: row.createdAt instanceof Date ? row.createdAt.toISOString() : String(row.createdAt),
        hasMedia: hasInline,
      };
    });
  }
}
