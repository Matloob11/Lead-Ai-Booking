/* eslint-disable @typescript-eslint/require-await, @typescript-eslint/unbound-method, @typescript-eslint/no-unsafe-member-access */
import type { Repository } from 'typeorm';
import { EngineRegistry } from '../../engine/engine-registry.service';
import type {
  EngineEventCallbacks,
  IWhatsAppEngine,
  IncomingMessage,
} from '../../engine/interfaces/whatsapp-engine.interface';
import { SessionEngineLifecycle } from './session-engine-lifecycle.service';
import { SessionEngineAcceptanceBuffer } from './session-engine-acceptance-buffer';
import { SessionEngineIdentityGate } from './session-engine-identity-gate';
import { SessionErrorStore } from './session-error-store.service';
import { SessionStatus, type Session } from './entities/session.entity';

describe('SessionEngineLifecycle identity admission', () => {
  const build = (
    unlinkSucceeds: boolean,
    options: {
      session?: Partial<Session>;
      decision?:
        | { kind: 'QUARANTINE'; reason: 'DIFFERENT_PHONE' }
        | { kind: 'SAME_PHONE'; phone: string }
        | { kind: 'FIRST_LINK'; phone: string; firstLinkedAt: Date };
    } = {},
  ) => {
    const session = {
      id: 's1',
      name: 'marketting',
      phone: '923166753715',
      status: SessionStatus.DISCONNECTED,
      config: {},
      proxyUrl: null,
      proxyType: null,
      historyImportedAt: new Date('2026-08-01T00:00:00.000Z'),
      historyFirstLinkedAt: new Date('2026-01-01T00:00:00.000Z'),
      ...options.session,
    } as Session;
    const repository = {
      findOne: jest.fn(async () => session),
      update: jest.fn(async () => ({ affected: 1 })),
    } as unknown as Repository<Session>;
    let callbacks!: EngineEventCallbacks;
    const engine = {
      initialize: jest.fn(async (wired: EngineEventCallbacks) => {
        callbacks = wired;
      }),
      logout: unlinkSucceeds
        ? jest.fn(async () => undefined)
        : jest.fn(async () => Promise.reject(new Error('unlink unavailable'))),
      forceDestroy: jest.fn(async () => undefined),
      purgeLocalCredentials: jest.fn(async () => undefined),
      importHistorySince: jest.fn(async () => 0),
    } as unknown as IWhatsAppEngine;
    const registry = new EngineRegistry();
    const messages = { handleInboundMessage: jest.fn() };
    const events = {
      emitSessionStatus: jest.fn(),
      emitSessionAuthenticated: jest.fn(),
    };
    const webhooks = { dispatch: jest.fn(async () => undefined) };
    const hooks = { execute: jest.fn(async () => ({ continue: true, data: {} })) };
    const identityGuard = {
      validateAndBind: jest.fn(async () => options.decision ?? { kind: 'QUARANTINE', reason: 'DIFFERENT_PHONE' }),
    };
    const gate = new SessionEngineIdentityGate(registry, new SessionEngineAcceptanceBuffer(), identityGuard as never);
    const lifecycle = new SessionEngineLifecycle(
      repository,
      {} as never,
      { create: jest.fn(() => engine) } as never,
      registry,
      { clear: jest.fn() } as never,
      messages as never,
      new SessionErrorStore(),
      { attachTo: (value: Session) => value, clearIfDisprovedByReady: jest.fn() } as never,
      { reportBack: jest.fn() } as never,
      { clear: jest.fn() } as never,
      events as never,
      webhooks as never,
      hooks as never,
      { ingest: jest.fn() } as never,
      undefined,
      undefined,
      undefined,
      gate,
    );
    return {
      lifecycle,
      repository,
      engine,
      registry,
      messages,
      events,
      webhooks,
      hooks,
      getCallbacks: () => callbacks,
    };
  };

  it('rejects a second phone before message/history/READY side effects and preserves old ownership', async () => {
    const h = build(true);
    await h.lifecycle.start('s1');
    const callbacks = h.getCallbacks();
    callbacks.onMessage?.({ id: 'held' } as IncomingMessage);

    await callbacks.onReady?.('971502938395', 'Other');

    expect(h.messages.handleInboundMessage).not.toHaveBeenCalled();
    expect(h.engine.importHistorySince).not.toHaveBeenCalled();
    expect(h.events.emitSessionAuthenticated).not.toHaveBeenCalled();
    expect(h.webhooks.dispatch).not.toHaveBeenCalledWith('s1', 'session.authenticated', expect.anything());
    expect(h.hooks.execute).not.toHaveBeenCalledWith('session:ready', expect.anything(), expect.anything());
    expect(h.engine.logout).toHaveBeenCalledTimes(1);
    expect(h.registry.getLifecycle('s1')).toBeUndefined();
    const mutations = (h.repository.update as jest.Mock).mock.calls.map(call => call[1] as Record<string, unknown>);
    expect(mutations).toEqual(
      expect.arrayContaining([expect.objectContaining({ status: SessionStatus.ACTION_REQUIRED })]),
    );
    expect(mutations.every(update => !('phone' in update) && !('historyImportedAt' in update))).toBe(true);
  });

  it('force-stops and purges only current adapter credentials when controlled unlink fails', async () => {
    const h = build(false);
    await h.lifecycle.start('s1');

    await h.getCallbacks().onReady?.('971502938395', 'Other');

    expect(h.engine.forceDestroy).toHaveBeenCalledTimes(1);
    expect(h.engine.purgeLocalCredentials).toHaveBeenCalledTimes(1);
    expect(h.registry.getLifecycle('s1')).toBeUndefined();
  });

  it('rolls a provisional first-link identity back when buffered replay fails', async () => {
    const firstLinkedAt = new Date('2026-08-08T00:00:00.000Z');
    const h = build(true, {
      session: { phone: null, historyImportedAt: null, historyFirstLinkedAt: null },
      decision: { kind: 'FIRST_LINK', phone: '923166753715', firstLinkedAt },
    });
    await h.lifecycle.start('s1');
    const callbacks = h.getCallbacks();
    callbacks.onEngineData?.(['will-fail'], () => {
      throw new Error('replay failed');
    });

    await callbacks.onReady?.('923166753715', 'Agent');

    const updateMock = h.repository.update as jest.MockedFunction<Repository<Session>['update']>;
    const rollbackCall = updateMock.mock.calls.find(
      call => (call[1] as Record<string, unknown>).status === SessionStatus.ACTION_REQUIRED,
    );
    expect(rollbackCall).toBeDefined();
    const rollbackCriteria = rollbackCall?.[0] as Record<string, unknown>;
    const rollbackMutation = rollbackCall?.[1] as Record<string, unknown>;
    expect(rollbackCriteria.id).toBe('s1');
    expect(typeof rollbackCriteria.historySyncToken).toBe('string');
    expect(rollbackMutation).toMatchObject({
      phone: null,
      historyFirstLinkedAt: null,
      historySyncToken: null,
      status: SessionStatus.ACTION_REQUIRED,
    });
  });

  it('uses immutable first-link anchor for the exact ten-day history cutoff', async () => {
    const anchor = new Date('2026-07-20T12:00:00.000Z');
    const h = build(true, {
      session: { historyImportedAt: null, historyFirstLinkedAt: anchor },
      decision: { kind: 'SAME_PHONE', phone: '923166753715' },
    });
    await h.lifecycle.start('s1');
    await h.getCallbacks().onReady?.('923166753715', 'Agent');
    await new Promise(resolve => setImmediate(resolve));
    await new Promise(resolve => setImmediate(resolve));

    expect(h.engine.importHistorySince).toHaveBeenCalledWith(
      new Date('2026-07-10T12:00:00.000Z'),
      expect.any(Function),
    );
  });

  it('projects durable rejection codes as actionable text after a fresh process restart', () => {
    const restartedStore = new SessionErrorStore();
    const projected = restartedStore.attachTo({
      ...({} as Session),
      id: 's1',
      status: SessionStatus.ACTION_REQUIRED,
      historySyncError: 'IDENTITY_DIFFERENT_PHONE',
    });

    expect(projected.lastError).toBe(
      'This session is permanently bound to another WhatsApp number. Create a new session for this number.',
    );
  });
});
