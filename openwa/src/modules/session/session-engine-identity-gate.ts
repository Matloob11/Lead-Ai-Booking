import { Injectable } from '@nestjs/common';
import { EngineRegistry } from '../../engine/engine-registry.service';
import { EngineEventCallbacks, EngineStatus, IWhatsAppEngine } from '../../engine/interfaces/whatsapp-engine.interface';
import { SessionEngineAcceptanceBuffer, type AcceptanceBufferOverflow } from './session-engine-acceptance-buffer';
import { SessionIdentityGuard, type IdentityQuarantineReason } from './session-identity-guard';

type RejectGeneration = (reason: string) => void | Promise<void>;

@Injectable()
export class SessionEngineIdentityGate {
  constructor(
    private readonly registry: EngineRegistry,
    private readonly buffer: SessionEngineAcceptanceBuffer,
    private readonly identities: SessionIdentityGuard,
  ) {}

  wrap(
    sessionId: string,
    token: string,
    engine: IWhatsAppEngine,
    accepted: EngineEventCallbacks,
    rejectGeneration: RejectGeneration,
  ): EngineEventCallbacks {
    let rejection: Promise<void> | null = null;
    let readiness: Promise<void> | null = null;
    const rejectOnce = (reason: string): Promise<void> => {
      if (rejection) return rejection;
      this.buffer.reject(sessionId, token);
      if (!this.registry.revokeGeneration(sessionId, token)) {
        rejection = Promise.resolve();
        return rejection;
      }
      rejection = Promise.resolve(rejectGeneration(reason));
      return rejection;
    };
    this.buffer.begin(sessionId, token, overflow => rejectOnce(this.overflowReason(overflow)));

    const defer = (payload: unknown, run: () => void | Promise<void>): void => {
      if (this.buffer.phase(sessionId, token) === 'CLOSED' && this.registry.isAcceptedToken(sessionId, token)) {
        void Promise.resolve(run()).catch(() => undefined);
        return;
      }
      this.buffer.defer(sessionId, token, payload, run);
    };

    return {
      // Pairing control must remain reachable while identity is not known yet.
      onQRCode: accepted.onQRCode,
      onEngineData: (payload, apply) => defer(['engine_data', payload], apply),
      onReady: (phone, pushName): Promise<void> => {
        if (readiness) return readiness;
        readiness = (async () => {
          if (this.registry.tokenFor(sessionId, engine) !== token) return;
          const decision = await this.identities
            .validateAndBind(
              sessionId,
              phone,
              token,
              () => !rejection && this.registry.tokenFor(sessionId, engine) === token,
            )
            .catch(() => ({
              kind: 'QUARANTINE' as const,
              reason: 'INVALID_IDENTITY' as const,
            }));
          if (decision.kind === 'QUARANTINE') {
            await rejectOnce(this.identityReason(decision.reason));
            return;
          }
          if (!this.registry.acceptForDrain(sessionId, token)) return;
          let drained: boolean;
          try {
            drained = await this.buffer.drain(sessionId, token);
          } catch {
            await rejectOnce('IDENTITY_BUFFER_REPLAY_FAILED');
            return;
          }
          if (!drained) return;
          if (!this.registry.publishGeneration(sessionId, token)) return;
          try {
            await accepted.onReady?.(decision.phone, pushName);
          } catch {
            await rejectOnce('IDENTITY_READY_PERSIST_FAILED');
          }
        })();
        return readiness;
      },
      onMessage: message => defer(['message', message], () => accepted.onMessage?.(message)),
      onHistoryMessages: messages => defer(['history', messages], () => accepted.onHistoryMessages?.(messages)),
      onMessageCreate: message => defer(['message_create', message], () => accepted.onMessageCreate?.(message)),
      onMessageAck: (messageId, status) =>
        defer(['message_ack', messageId, status], () => accepted.onMessageAck?.(messageId, status)),
      onMessageRevoked: message => defer(['message_revoked', message], () => accepted.onMessageRevoked?.(message)),
      onMessageReaction: event => defer(['message_reaction', event], () => accepted.onMessageReaction?.(event)),
      onMessageEdited: message => defer(['message_edited', message], () => accepted.onMessageEdited?.(message)),
      onGroupEvent: event => defer(['group', event], () => accepted.onGroupEvent?.(event)),
      onCall: event => defer(['call', event], () => accepted.onCall?.(event)),
      onCallOutcome: event => defer(['call_outcome', event], () => accepted.onCallOutcome?.(event)),
      onPresenceUpdate: event => defer(['presence', event], () => accepted.onPresenceUpdate?.(event)),
      onAccountRestriction: restriction =>
        defer(['restriction', restriction], () => accepted.onAccountRestriction?.(restriction)),
      // Connection/teardown control remains active. READY is published only after validation+drain.
      onStateChanged: state => {
        if (state !== EngineStatus.READY) accepted.onStateChanged?.(state);
      },
      onDisconnected: accepted.onDisconnected,
      onActionRequired: accepted.onActionRequired,
      onError: accepted.onError,
      onCredentialTeardownStarted: accepted.onCredentialTeardownStarted,
      claimStuckAuthRecovery: accepted.claimStuckAuthRecovery,
    };
  }

  private identityReason(reason: IdentityQuarantineReason): string {
    return reason === 'INVALID_IDENTITY' ? 'IDENTITY_INVALID' : `IDENTITY_${reason}`;
  }

  private overflowReason(reason: AcceptanceBufferOverflow): string {
    return `IDENTITY_BUFFER_${reason}`;
  }
}
