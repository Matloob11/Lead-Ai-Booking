import { Inject, Injectable, Optional } from '@nestjs/common';

export type AcceptanceBufferOverflow = 'EVENT_LIMIT' | 'BYTE_LIMIT' | 'TIME_LIMIT';
export type AcceptanceBufferPhase = 'PENDING' | 'DRAINING' | 'CLOSED' | 'REJECTED';

interface DeferredEvent {
  run: () => void | Promise<void>;
  bytes: number;
}

interface BufferState {
  token: string;
  phase: AcceptanceBufferPhase;
  events: DeferredEvent[];
  bytes: number;
  /** Armed only when the first event is deferred — not at begin. */
  timer: NodeJS.Timeout | null;
  reject: (reason: AcceptanceBufferOverflow) => void | Promise<void>;
}

@Injectable()
export class SessionEngineAcceptanceBuffer {
  private readonly buffers = new Map<string, BufferState>();
  private readonly maxEvents: number;
  private readonly maxBytes: number;
  private readonly maxAgeMs: number;

  constructor(
    @Optional()
    @Inject('SESSION_ENGINE_ACCEPTANCE_BUFFER_OPTIONS')
    options: { maxEvents?: number; maxBytes?: number; maxAgeMs?: number } = {},
  ) {
    this.maxEvents = options.maxEvents ?? 500;
    this.maxBytes = options.maxBytes ?? 16 * 1024 * 1024;
    this.maxAgeMs = options.maxAgeMs ?? 30_000;
  }

  begin(sessionId: string, token: string, reject: BufferState['reject']): void {
    const previous = this.buffers.get(sessionId);
    if (previous?.timer) clearTimeout(previous.timer);
    // No TIME_LIMIT clock yet. Pairing/QR can sit for minutes with zero buffered events;
    // starting the 30s timer at engine wrap was killing asma mid pairing-code entry
    // (IDENTITY_BUFFER_TIME_LIMIT) before WhatsApp ever authenticated.
    this.buffers.set(sessionId, { token, phase: 'PENDING', events: [], bytes: 0, timer: null, reject });
  }

  defer(sessionId: string, token: string, serializedPayload: unknown, run: DeferredEvent['run']): boolean {
    const state = this.match(sessionId, token);
    if (!state || (state.phase !== 'PENDING' && state.phase !== 'DRAINING')) return false;
    const bytes = this.serializedBytes(serializedPayload);
    if (state.events.length + 1 > this.maxEvents) {
      this.overflow(sessionId, token, 'EVENT_LIMIT');
      return false;
    }
    if (state.bytes + bytes > this.maxBytes) {
      this.overflow(sessionId, token, 'BYTE_LIMIT');
      return false;
    }
    if (!state.timer && state.phase === 'PENDING') {
      state.timer = setTimeout(() => this.overflow(sessionId, token, 'TIME_LIMIT'), this.maxAgeMs);
      state.timer.unref?.();
    }
    state.events.push({ run, bytes });
    state.bytes += bytes;
    return true;
  }

  async drain(sessionId: string, token: string): Promise<boolean> {
    const state = this.match(sessionId, token);
    if (!state || state.phase !== 'PENDING') return false;
    state.phase = 'DRAINING';
    while (state.phase === 'DRAINING') {
      const event = state.events.shift();
      if (!event) {
        state.phase = 'CLOSED';
        if (state.timer) clearTimeout(state.timer);
        state.timer = null;
        return true;
      }
      state.bytes -= event.bytes;
      await event.run();
    }
    return false;
  }

  reject(sessionId: string, token: string): boolean {
    const state = this.match(sessionId, token);
    if (!state || state.phase === 'REJECTED' || state.phase === 'CLOSED') return false;
    state.phase = 'REJECTED';
    state.events.length = 0;
    state.bytes = 0;
    if (state.timer) clearTimeout(state.timer);
    state.timer = null;
    return true;
  }

  phase(sessionId: string, token: string): AcceptanceBufferPhase | undefined {
    return this.match(sessionId, token)?.phase;
  }

  private overflow(sessionId: string, token: string, reason: AcceptanceBufferOverflow): void {
    const state = this.match(sessionId, token);
    if (!state || !this.reject(sessionId, token)) return;
    void Promise.resolve(state.reject(reason)).catch(() => undefined);
  }

  private match(sessionId: string, token: string): BufferState | undefined {
    const state = this.buffers.get(sessionId);
    return state?.token === token ? state : undefined;
  }

  private serializedBytes(value: unknown): number {
    try {
      return Buffer.byteLength(JSON.stringify(value) ?? 'null', 'utf8');
    } catch {
      return this.maxBytes + 1;
    }
  }
}
