/* eslint-disable @typescript-eslint/require-await */
import type {
  EngineEventCallbacks,
  IWhatsAppEngine,
  IncomingMessage,
} from '../../engine/interfaces/whatsapp-engine.interface';
import { EngineRegistry } from '../../engine/engine-registry.service';
import { SessionEngineAcceptanceBuffer } from './session-engine-acceptance-buffer';
import { SessionEngineIdentityGate } from './session-engine-identity-gate';

const engine = (): IWhatsAppEngine =>
  ({
    logout: jest.fn(async () => undefined),
    forceDestroy: jest.fn(async () => undefined),
  }) as unknown as IWhatsAppEngine;

const message = { id: 'm1', body: 'held' } as unknown as IncomingMessage;

describe('SessionEngineIdentityGate', () => {
  afterEach(() => jest.useRealTimers());
  it('buffers data, validates identity, drains in order, then publishes READY/authenticated', async () => {
    const registry = new EngineRegistry();
    const buffer = new SessionEngineAcceptanceBuffer();
    const guard = { validateAndBind: jest.fn(async () => ({ kind: 'SAME_PHONE', phone: '923166753715' })) };
    const onMessage = jest.fn();
    const onReady = jest.fn();
    const current = engine();
    const token = registry.beginGeneration('s1', current);
    const gate = new SessionEngineIdentityGate(registry, buffer, guard as never);
    const callbacks = gate.wrap('s1', token, current, { onMessage, onReady }, jest.fn());

    callbacks.onMessage?.(message);
    expect(onMessage).not.toHaveBeenCalled();
    expect(() => registry.require('s1')).toThrow('not started');

    await callbacks.onReady?.('+92 316 6753715', 'Agent');

    expect(onMessage).toHaveBeenCalledWith(message);
    expect(onReady).toHaveBeenCalledWith('923166753715', 'Agent');
    expect(registry.require('s1')).toBe(current);

    callbacks.onMessage?.({ ...message, id: 'm2' });
    expect(onMessage).toHaveBeenCalledTimes(2);
  });

  it('holds adapter-internal data mutations behind the same acceptance buffer', async () => {
    const registry = new EngineRegistry();
    const buffer = new SessionEngineAcceptanceBuffer();
    const guard = { validateAndBind: jest.fn(async () => ({ kind: 'SAME_PHONE', phone: '923166753715' })) };
    const mutation = jest.fn();
    const current = engine();
    const token = registry.beginGeneration('s1', current);
    const callbacks = new SessionEngineIdentityGate(registry, buffer, guard as never).wrap(
      's1',
      token,
      current,
      {},
      jest.fn(),
    );

    callbacks.onEngineData?.({ type: 'contacts.upsert', records: [{ id: 'other-phone' }] }, mutation);
    expect(mutation).not.toHaveBeenCalled();

    await callbacks.onReady?.('923166753715', 'Agent');
    expect(mutation).toHaveBeenCalledTimes(1);
  });

  it.each([
    [{ kind: 'QUARANTINE', reason: 'DIFFERENT_PHONE' }, '923000000000'],
    [{ kind: 'QUARANTINE', reason: 'INVALID_IDENTITY' }, ''],
  ])('never emits or replays on rejected identity %#', async (decision, phone) => {
    const registry = new EngineRegistry();
    const buffer = new SessionEngineAcceptanceBuffer();
    const guard = { validateAndBind: jest.fn(async () => decision) };
    const effects: EngineEventCallbacks = { onMessage: jest.fn(), onReady: jest.fn() };
    const reject = jest.fn(async () => undefined);
    const current = engine();
    const token = registry.beginGeneration('s1', current);
    const gate = new SessionEngineIdentityGate(registry, buffer, guard as never);
    const callbacks = gate.wrap('s1', token, current, effects, reject);

    callbacks.onMessage?.(message);
    await callbacks.onReady?.(phone, 'Agent');

    expect(effects.onMessage).not.toHaveBeenCalled();
    expect(effects.onReady).not.toHaveBeenCalled();
    expect(reject).toHaveBeenCalled();
    expect(() => registry.require('s1')).toThrow('not started');
  });

  it('overflow revokes generation, tears it down once, and later READY cannot replay', async () => {
    const registry = new EngineRegistry();
    const buffer = new SessionEngineAcceptanceBuffer({ maxEvents: 1 });
    const guard = { validateAndBind: jest.fn(async () => ({ kind: 'SAME_PHONE', phone: '923166753715' })) };
    const effects: EngineEventCallbacks = { onMessage: jest.fn(), onReady: jest.fn() };
    const reject = jest.fn(async () => undefined);
    const current = engine();
    const token = registry.beginGeneration('s1', current);
    const gate = new SessionEngineIdentityGate(registry, buffer, guard as never);
    const callbacks = gate.wrap('s1', token, current, effects, reject);

    callbacks.onMessage?.(message);
    callbacks.onMessage?.({ ...message, id: 'm2' });
    await Promise.resolve();
    await callbacks.onReady?.('923166753715', 'Agent');

    expect(reject).toHaveBeenCalledTimes(1);
    expect(effects.onMessage).not.toHaveBeenCalled();
    expect(effects.onReady).not.toHaveBeenCalled();
    expect(registry.isAcceptedToken('s1', token)).toBe(false);
  });

  it('a retired generation timer cannot overwrite the later stop/delete outcome', () => {
    jest.useFakeTimers();
    const registry = new EngineRegistry();
    const buffer = new SessionEngineAcceptanceBuffer({ maxAgeMs: 30_000 });
    const reject = jest.fn();
    const current = engine();
    const token = registry.beginGeneration('s1', current);
    new SessionEngineIdentityGate(registry, buffer, { validateAndBind: jest.fn() } as never).wrap(
      's1',
      token,
      current,
      {},
      reject,
    );

    registry.delete('s1');
    jest.advanceTimersByTime(30_001);

    expect(reject).not.toHaveBeenCalled();
  });
});
