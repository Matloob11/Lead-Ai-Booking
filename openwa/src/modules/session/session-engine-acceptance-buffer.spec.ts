import { SessionEngineAcceptanceBuffer } from './session-engine-acceptance-buffer';
import { Test } from '@nestjs/testing';

describe('SessionEngineAcceptanceBuffer', () => {
  afterEach(() => jest.useRealTimers());

  it('constructs through Nest without a custom limits provider', async () => {
    const module = await Test.createTestingModule({ providers: [SessionEngineAcceptanceBuffer] }).compile();
    expect(module.get(SessionEngineAcceptanceBuffer)).toBeInstanceOf(SessionEngineAcceptanceBuffer);
  });

  it('replays in order and includes events arriving while drain is awaiting', async () => {
    const buffer = new SessionEngineAcceptanceBuffer();
    const seen: number[] = [];
    let release!: () => void;
    const held = new Promise<void>(resolve => (release = resolve));
    buffer.begin('s1', 'g1', jest.fn());
    buffer.defer('s1', 'g1', [1], async () => {
      seen.push(1);
      await held;
    });
    buffer.defer('s1', 'g1', [2], () => seen.push(2));

    const draining = buffer.drain('s1', 'g1');
    await Promise.resolve();
    buffer.defer('s1', 'g1', [3], () => seen.push(3));
    release();

    await expect(draining).resolves.toBe(true);
    expect(seen).toEqual([1, 2, 3]);
    expect(buffer.phase('s1', 'g1')).toBe('CLOSED');
  });

  it('releases drained bytes before accepting events produced during replay', async () => {
    const buffer = new SessionEngineAcceptanceBuffer({ maxBytes: 20 });
    const seen: string[] = [];
    buffer.begin('s1', 'g1', jest.fn());
    buffer.defer('s1', 'g1', '1234567890', () => {
      seen.push('raw');
      buffer.defer('s1', 'g1', 'abcdefghij', () => seen.push('mapped'));
    });

    await expect(buffer.drain('s1', 'g1')).resolves.toBe(true);
    expect(seen).toEqual(['raw', 'mapped']);
  });

  it('rejects the 501st event, clears queued data, and can never replay it', async () => {
    const rejected = jest.fn();
    const replay = jest.fn();
    const buffer = new SessionEngineAcceptanceBuffer();
    buffer.begin('s1', 'g1', rejected);
    for (let index = 0; index < 501; index += 1) {
      buffer.defer('s1', 'g1', [index], replay);
    }

    expect(rejected).toHaveBeenCalledWith('EVENT_LIMIT');
    await expect(buffer.drain('s1', 'g1')).resolves.toBe(false);
    expect(replay).not.toHaveBeenCalled();
  });

  it('rejects a serialized payload above 16 MiB without replay', async () => {
    const rejected = jest.fn();
    const replay = jest.fn();
    const buffer = new SessionEngineAcceptanceBuffer();
    buffer.begin('s1', 'g1', rejected);
    buffer.defer('s1', 'g1', ['x'.repeat(16 * 1024 * 1024)], replay);

    expect(rejected).toHaveBeenCalledWith('BYTE_LIMIT');
    await expect(buffer.drain('s1', 'g1')).resolves.toBe(false);
    expect(replay).not.toHaveBeenCalled();
  });

  it('rejects after 30 seconds once an event is buffered, even when no later event arrives', () => {
    jest.useFakeTimers();
    const rejected = jest.fn();
    const replay = jest.fn();
    const buffer = new SessionEngineAcceptanceBuffer();
    buffer.begin('s1', 'g1', rejected);
    buffer.defer('s1', 'g1', ['held'], replay);

    jest.advanceTimersByTime(30_001);

    expect(rejected).toHaveBeenCalledWith('TIME_LIMIT');
    expect(buffer.phase('s1', 'g1')).toBe('REJECTED');
    expect(replay).not.toHaveBeenCalled();
  });

  it('does not TIME_LIMIT while waiting on QR/pairing with an empty buffer', () => {
    // Pairing-code entry routinely takes longer than 30s. The clock must not start at begin().
    jest.useFakeTimers();
    const rejected = jest.fn();
    const buffer = new SessionEngineAcceptanceBuffer();
    buffer.begin('s1', 'g1', rejected);

    jest.advanceTimersByTime(120_000);

    expect(rejected).not.toHaveBeenCalled();
    expect(buffer.phase('s1', 'g1')).toBe('PENDING');
  });

  it('stale token cannot reject or drain a replacement generation', async () => {
    const replay = jest.fn();
    const buffer = new SessionEngineAcceptanceBuffer();
    buffer.begin('s1', 'g1', jest.fn());
    buffer.begin('s1', 'g2', jest.fn());
    buffer.defer('s1', 'g2', ['fresh'], replay);

    buffer.reject('s1', 'g1');
    await expect(buffer.drain('s1', 'g1')).resolves.toBe(false);
    await expect(buffer.drain('s1', 'g2')).resolves.toBe(true);
    expect(replay).toHaveBeenCalledTimes(1);
  });
});
