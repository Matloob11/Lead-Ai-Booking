import { Injectable, NotFoundException } from '@nestjs/common';
import { InjectDataSource } from '@nestjs/typeorm';
import { DataSource, EntityManager } from 'typeorm';
import type { QueryDeepPartialEntity } from 'typeorm/query-builder/QueryPartialEntity';
import { normalizePhoneIdentity } from '../../engine/identity/wa-id';
import { LidMapping } from '../../engine/identity/lid-mapping.entity';
import { Message, MessageDirection } from '../message/entities/message.entity';
import { Session, SessionStatus } from './entities/session.entity';

export type IdentityQuarantineReason = 'DIFFERENT_PHONE' | 'INVALID_IDENTITY' | 'LEGACY_AMBIGUOUS' | 'LEGACY_CONFLICT';

export type IdentityDecision =
  | { kind: 'FIRST_LINK'; phone: string; firstLinkedAt: Date }
  | { kind: 'SAME_PHONE'; phone: string; firstLinkedAt: Date }
  | { kind: 'QUARANTINE'; reason: IdentityQuarantineReason };

const durableReason = (reason: IdentityQuarantineReason): string =>
  reason === 'INVALID_IDENTITY' ? 'IDENTITY_INVALID' : `IDENTITY_${reason}`;

@Injectable()
export class SessionIdentityGuard {
  constructor(@InjectDataSource('data') private readonly dataSource: DataSource) {}

  validateAndBind(
    sessionId: string,
    authenticatedIdentity: unknown,
    generationToken: string,
    generationIsCurrent: () => boolean = () => true,
  ): Promise<IdentityDecision> {
    return this.dataSource.transaction(async manager => {
      this.assertGenerationCurrent(generationIsCurrent);
      const session = await manager.findOne(Session, { where: { id: sessionId } });
      this.assertGenerationCurrent(generationIsCurrent);
      if (!session) throw new NotFoundException(`Session with id '${sessionId}' not found`);
      if (session.historySyncToken !== generationToken) {
        throw new Error('Identity check aborted: durable engine generation retired');
      }

      const currentPhone = normalizePhoneIdentity(authenticatedIdentity);
      if (!currentPhone) {
        return this.quarantine(manager, sessionId, 'INVALID_IDENTITY', generationToken, generationIsCurrent);
      }

      const boundPhone = normalizePhoneIdentity(session.phone);
      if (!session.phone) {
        const messageCount = await manager.count(Message, { where: { sessionId } });
        this.assertGenerationCurrent(generationIsCurrent);
        if (session.historyImportedAt || session.historyFirstLinkedAt || messageCount > 0) {
          return this.quarantine(manager, sessionId, 'LEGACY_AMBIGUOUS', generationToken, generationIsCurrent);
        }
        const firstLinkedAt = new Date();
        await this.guardedUpdate(
          manager,
          sessionId,
          generationToken,
          {
            phone: currentPhone,
            historyFirstLinkedAt: firstLinkedAt,
            historySyncError: null,
          },
          generationIsCurrent,
        );
        this.assertGenerationCurrent(generationIsCurrent);
        return { kind: 'FIRST_LINK', phone: currentPhone, firstLinkedAt };
      }

      if (!boundPhone) {
        return this.quarantine(manager, sessionId, 'LEGACY_AMBIGUOUS', generationToken, generationIsCurrent);
      }
      if (boundPhone !== currentPhone) {
        return this.quarantine(manager, sessionId, 'DIFFERENT_PHONE', generationToken, generationIsCurrent);
      }
      if (await this.hasProvenHistoricalConflict(manager, sessionId, boundPhone)) {
        this.assertGenerationCurrent(generationIsCurrent);
        return this.quarantine(manager, sessionId, 'LEGACY_CONFLICT', generationToken, generationIsCurrent);
      }
      this.assertGenerationCurrent(generationIsCurrent);

      const firstLinkedAt = session.historyFirstLinkedAt ?? session.createdAt;
      await this.guardedUpdate(
        manager,
        sessionId,
        generationToken,
        {
          historyFirstLinkedAt: firstLinkedAt,
          ...(this.clearsAfterIdentityAcceptance(session.historySyncError) ? { historySyncError: null } : {}),
        },
        generationIsCurrent,
      );
      this.assertGenerationCurrent(generationIsCurrent);
      return { kind: 'SAME_PHONE', phone: boundPhone, firstLinkedAt };
    });
  }

  private async quarantine(
    manager: EntityManager,
    sessionId: string,
    reason: IdentityQuarantineReason,
    generationToken: string,
    generationIsCurrent: () => boolean,
  ): Promise<IdentityDecision> {
    this.assertGenerationCurrent(generationIsCurrent);
    await this.guardedUpdate(
      manager,
      sessionId,
      generationToken,
      {
        status: SessionStatus.ACTION_REQUIRED,
        historySyncError: durableReason(reason),
      },
      generationIsCurrent,
    );
    this.assertGenerationCurrent(generationIsCurrent);
    return { kind: 'QUARANTINE', reason };
  }

  private assertGenerationCurrent(generationIsCurrent: () => boolean): void {
    if (!generationIsCurrent()) throw new Error('Identity check aborted: engine generation retired');
  }

  private async guardedUpdate(
    manager: EntityManager,
    sessionId: string,
    generationToken: string,
    patch: QueryDeepPartialEntity<Session>,
    generationIsCurrent: () => boolean,
  ): Promise<void> {
    this.assertGenerationCurrent(generationIsCurrent);
    const result = await manager.update(Session, { id: sessionId, historySyncToken: generationToken }, patch);
    this.assertGenerationCurrent(generationIsCurrent);
    if (result.affected !== 1) throw new Error('Identity check aborted: durable engine generation retired');
  }

  private clearsAfterIdentityAcceptance(error: string | null | undefined): boolean {
    return !error || error === 'LOGOUT_INCOMPLETE' || error.startsWith('IDENTITY_');
  }

  /**
   * Existing bound sessions are legacy-safe when every provable owner agrees. Unmapped LIDs stay
   * unresolved rather than being guessed; latest release instruction explicitly keeps those bound,
   * conflict-free live sessions out of quarantine.
   */
  private async hasProvenHistoricalConflict(
    manager: EntityManager,
    sessionId: string,
    boundPhone: string,
  ): Promise<boolean> {
    const [messages, mappings] = await Promise.all([
      manager.find(Message, { where: { sessionId }, select: { direction: true, from: true, to: true } }),
      manager.find(LidMapping, { select: { lid: true, phone: true } }),
    ]);
    const lids = new Map(
      mappings
        .map(row => [String(row.lid), normalizePhoneIdentity(row.phone)] as const)
        .filter((entry): entry is readonly [string, string] => entry[1] !== null),
    );
    for (const row of messages) {
      const owner = row.direction === MessageDirection.INCOMING ? row.to : row.from;
      const phone = this.resolveOwner(owner, lids);
      if (phone && phone !== boundPhone) return true;
    }
    return false;
  }

  private resolveOwner(value: string | null | undefined, lids: ReadonlyMap<string, string>): string | null {
    const phone = normalizePhoneIdentity(value);
    if (phone) return phone;
    const lid = typeof value === 'string' ? /^(\d+)(?::\d+)?@lid$/i.exec(value.trim())?.[1] : undefined;
    return lid ? (lids.get(lid) ?? null) : null;
  }
}
