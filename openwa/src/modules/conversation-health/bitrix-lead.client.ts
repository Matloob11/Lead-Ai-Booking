import { Injectable } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { createLogger } from '../../common/services/logger.service';
import { COLOUR_LIGHT, ENUM_IDS, OWNER_DATA_PHONE_FIELDS, OWNER_DATA_TYPE_ID } from './conversation-health.constants';
import type { ConversationColour } from './entities/chat-lead.entity';

/** Bitrix timeline / update target. Leads use "lead"; Owner Data SPA uses DYNAMIC_{typeId}. */
export type BitrixEntityType = 'lead' | `DYNAMIC_${number}` | string;

export interface BitrixTarget {
  id: string;
  entityType: BitrixEntityType;
  created: boolean;
  kind: 'lead' | 'owner_data';
}

@Injectable()
export class BitrixLeadClient {
  private readonly logger = createLogger('BitrixLeadClient');

  constructor(private readonly config: ConfigService) {}

  enabled(): boolean {
    return Boolean(this.base());
  }

  ownerDataTypeId(): number {
    const raw = process.env.BITRIX_OWNER_DATA_TYPE_ID || String(OWNER_DATA_TYPE_ID);
    const n = Number(raw);
    return Number.isFinite(n) && n > 0 ? n : OWNER_DATA_TYPE_ID;
  }

  ownerDataEntityType(): BitrixEntityType {
    return `DYNAMIC_${this.ownerDataTypeId()}`;
  }

  /** Public URL for a lead or Owner Data item. */
  entityUrl(entityId: string, entityType: BitrixEntityType = 'lead'): string {
    if (typeof entityType === 'string' && entityType.startsWith('DYNAMIC_')) {
      const typeId = entityType.slice('DYNAMIC_'.length) || String(this.ownerDataTypeId());
      const root = (
        this.config.get<string>('BITRIX_OWNER_DATA_URL_BASE') ||
        process.env.BITRIX_OWNER_DATA_URL_BASE ||
        `https://crm.a7grouprealestatedxb.com/crm/type/${typeId}/details`
      ).replace(/\/+$/, '');
      return `${root}/${entityId}/`;
    }
    return this.leadUrl(entityId);
  }

  leadUrl(leadId: string): string {
    const root = (this.config.get<string>('BITRIX_LEAD_URL_BASE') || process.env.BITRIX_LEAD_URL_BASE || '').replace(
      /\/+$/,
      '',
    );
    if (root) return `${root}/${leadId}/`;
    return `https://crm.a7grouprealestatedxb.com/crm/lead/details/${leadId}/`;
  }

  private base(): string {
    return (
      this.config.get<string>('BITRIX_WEBHOOK_BASE') ||
      process.env.BITRIX_WEBHOOK_BASE ||
      ''
    ).replace(/\/+$/, '');
  }

  private healthField(): string {
    return process.env.BITRIX_HEALTH_FIELD || 'UF_CRM_CONVERSATION_HEALTH';
  }

  private reasonField(): string {
    return process.env.BITRIX_AI_MONITOR_FIELD || 'UF_CRM_AI_MONITOR';
  }

  private chatField(): string {
    return process.env.BITRIX_WA_CHAT_FIELD || 'UF_CRM_WA_CHAT';
  }

  /** Optional SPA field names — only used when set (webhook cannot create Owner Data UFs). */
  private ownerHealthField(): string {
    return (process.env.BITRIX_OWNER_HEALTH_FIELD || '').trim();
  }

  private ownerReasonField(): string {
    return (process.env.BITRIX_OWNER_AI_MONITOR_FIELD || '').trim();
  }

  private ownerChatField(): string {
    return (process.env.BITRIX_OWNER_WA_CHAT_FIELD || '').trim();
  }

  private waStatus(): string {
    return process.env.BITRIX_WA_LEAD_STATUS || 'UC_WA_LEADS';
  }

  private phoneFields(): string[] {
    const raw = (process.env.BITRIX_OWNER_DATA_PHONE_FIELDS || '').trim();
    if (raw) {
      return raw
        .split(',')
        .map(s => s.trim())
        .filter(Boolean);
    }
    return [...OWNER_DATA_PHONE_FIELDS];
  }

  private async call(method: string, params?: Record<string, unknown>): Promise<Record<string, unknown>> {
    const base = this.base();
    if (!base) throw new Error('BITRIX_WEBHOOK_BASE missing');
    const url = `${base}/${method}.json`;
    const res = await fetch(url, {
      method: params ? 'POST' : 'GET',
      headers: params ? { 'Content-Type': 'application/json' } : undefined,
      body: params ? JSON.stringify(params) : undefined,
      signal: AbortSignal.timeout(60_000),
    });
    const text = await res.text();
    let data: Record<string, unknown>;
    try {
      data = JSON.parse(text) as Record<string, unknown>;
    } catch {
      throw new Error(`Bitrix ${method} non-JSON HTTP ${res.status}`);
    }
    if (!res.ok || data.error) {
      throw new Error(`Bitrix ${method}: ${String(data.error_description || data.error || res.status)}`);
    }
    return data;
  }

  /**
   * Resolve CRM target for a WhatsApp phone:
   * 1) existing Lead (any stage)
   * 2) existing Owner Data SPA item (type 1042)
   * 3) create new Lead in WhatsApp Leads
   */
  async findOrCreateLead(phone: string, titleHint: string): Promise<BitrixTarget> {
    const digits = phone.replace(/\D/g, '');
    if (!digits) throw new Error('phone required');

    const leadId = await this.findLeadByPhone(digits);
    if (leadId) {
      return { id: leadId, entityType: 'lead', created: false, kind: 'lead' };
    }

    const ownerId = await this.findOwnerDataByPhone(digits);
    if (ownerId) {
      this.logger.log(`matched Owner Data id=${ownerId} phone=${digits}`);
      return {
        id: ownerId,
        entityType: this.ownerDataEntityType(),
        created: false,
        kind: 'owner_data',
      };
    }

    const created = await this.call('crm.lead.add', {
      fields: {
        TITLE: `WA · ${(titleHint || digits).slice(0, 40)}`,
        NAME: (titleHint || digits).slice(0, 80),
        OPENED: 'Y',
        STATUS_ID: this.waStatus(),
        SOURCE_DESCRIPTION: 'OpenWA Conversation Health',
        PHONE: [{ VALUE: digits, VALUE_TYPE: 'WORK' }],
      },
    });
    const newId = created.result;
    if (newId == null) throw new Error('crm.lead.add returned no id');
    return { id: String(newId), entityType: 'lead', created: true, kind: 'lead' };
  }

  private async findLeadByPhone(digits: string): Promise<string | null> {
    const found = await this.call('crm.duplicate.findbycomm', {
      entity_type: 'LEAD',
      type: 'PHONE',
      values: [digits, `+${digits}`],
    });
    const result = (found.result as Record<string, unknown>) || {};
    const leadIds = (result.LEAD as Array<string | number>) || [];
    return leadIds.length ? String(leadIds[0]) : null;
  }

  /** Same numeric phone match as backend crmlink — SPA phones are double fields. */
  async findOwnerDataByPhone(digits: string): Promise<string | null> {
    const candidates = new Set<number>();
    const asInt = Number(digits);
    if (Number.isFinite(asInt) && asInt > 0) candidates.add(asInt);
    if (digits.startsWith('971') && digits.length > 9) {
      const local = Number(digits.slice(3));
      if (Number.isFinite(local) && local > 0) candidates.add(local);
    }

    const typeId = this.ownerDataTypeId();
    const seen = new Set<string>();
    for (const field of this.phoneFields()) {
      for (const value of candidates) {
        try {
          const res = await this.call('crm.item.list', {
            entityTypeId: typeId,
            select: ['id'],
            filter: { [field]: value },
          });
          const result = (res.result as { items?: Array<{ id?: string | number }> }) || {};
          for (const item of result.items || []) {
            if (item?.id == null) continue;
            const id = String(item.id);
            if (!seen.has(id)) {
              seen.add(id);
              return id;
            }
          }
        } catch (err) {
          this.logger.warn(`Owner Data search ${field}=${value} failed: ${String(err)}`);
        }
      }
    }
    return null;
  }

  async addTimelineComment(
    entityId: string,
    comment: string,
    entityType: BitrixEntityType = 'lead',
  ): Promise<void> {
    await this.call('crm.timeline.comment.add', {
      fields: {
        ENTITY_ID: Number(entityId),
        ENTITY_TYPE: entityType,
        COMMENT: comment.slice(0, 65000),
      },
    });
  }

  async updateFields(
    entityId: string,
    fields: {
      colour?: ConversationColour;
      monitorText?: string;
      chatText?: string;
    },
    entityType: BitrixEntityType = 'lead',
  ): Promise<void> {
    if (typeof entityType === 'string' && entityType.startsWith('DYNAMIC_')) {
      await this.updateOwnerDataFields(entityId, fields);
      return;
    }

    const payload: Record<string, unknown> = {};
    if (fields.colour) payload[this.healthField()] = ENUM_IDS[fields.colour];
    if (fields.monitorText != null) payload[this.reasonField()] = fields.monitorText.slice(0, 2000);
    if (fields.chatText != null) payload[this.chatField()] = fields.chatText;
    if (!Object.keys(payload).length) return;
    await this.call('crm.lead.update', { id: entityId, fields: payload });
  }

  private async updateOwnerDataFields(
    entityId: string,
    fields: {
      colour?: ConversationColour;
      monitorText?: string;
      chatText?: string;
    },
  ): Promise<void> {
    const payload: Record<string, unknown> = {};
    const health = this.ownerHealthField();
    const reason = this.ownerReasonField();
    const chat = this.ownerChatField();
    // Without SPA UFs configured, colour/chat stay in timeline comments only.
    if (fields.colour && health) payload[health] = ENUM_IDS[fields.colour];
    if (fields.monitorText != null && reason) payload[reason] = fields.monitorText.slice(0, 2000);
    if (fields.chatText != null && chat) payload[chat] = fields.chatText;
    if (!Object.keys(payload).length) {
      this.logger.debug(`Owner Data ${entityId}: no SPA health fields configured — comments only`);
      return;
    }
    try {
      await this.call('crm.item.update', {
        entityTypeId: this.ownerDataTypeId(),
        id: Number(entityId),
        fields: payload,
      });
    } catch (err) {
      this.logger.warn(`Owner Data field update failed id=${entityId}: ${String(err)}`);
    }
  }

  buildMonitorText(
    colour: ConversationColour,
    reason: string,
    agent: string,
    agentPhone: string,
    client: string,
    flags: string[],
  ): string {
    const light = COLOUR_LIGHT[colour];
    return (
      `${light}\n` +
      `Why: ${reason || 'No reason'}\n` +
      `Agent: ${agent} (${agentPhone || '-'})\n` +
      `Client: ${client}\n` +
      `Channel: whatsapp\n` +
      `Flags: ${flags.length ? flags.join(', ') : '-'}`
    );
  }

  logSkip(reason: string): void {
    this.logger.debug(`bitrix skip: ${reason}`);
  }
}
