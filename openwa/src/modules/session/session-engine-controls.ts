import {
  BadGatewayException,
  BadRequestException,
  ConflictException,
  HttpStatus,
  NotFoundException,
} from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Repository, DataSource } from 'typeorm';
import { Session, SessionStatus } from './entities/session.entity';
import { Message } from '../message/entities/message.entity';
import { EngineFactory } from '../../engine/engine.factory';
import { EngineRegistry } from '../../engine/engine-registry.service';
import { SessionErrorStore } from './session-error-store.service';
import { SessionRestrictionStore } from './session-restriction-store.service';
import { DeviceAlertService } from './device-alert.service';
import { PresenceStore } from './presence-store.service';
import { type createLogger } from '../../common/services/logger.service';
import { HookManager } from '../../core/hooks';
import { SessionLifecycleFences } from './session-lifecycle-fences';
import { SessionStatusBroadcaster } from './session-status-broadcaster';
import { requireManualStart } from './session-profile-reset';
// The two pure config resolvers stay exported from the lifecycle module (its export surface is
// unchanged — session.service re-exports them from there), so this unit imports them back. The
// resulting import cycle is deferred-usage only — the bindings are read inside method bodies,
// never at module-eval time — which the CommonJS loader resolves safely.
import {
  resolveMaxConcurrentSessions,
  resolveReconnectConfig,
  type ReconnectState,
} from './session-engine-lifecycle.service';

/**
 * The deps + core call-ins SessionEngineControls needs from the lifecycle. Built ONCE in the
 * lifecycle's constructor. The dependency VALUES (sessionRepository … broadcaster) are captured at
 * construction — the same reads the pre-extraction code made of the lifecycle's readonly
 * constructor fields — while the shared state containers (stoppingSessions, reconnectStates,
 * stuckAuthRecoveryUsed, initializingSessions) are handed over BY REFERENCE, so this unit, the
 * lifecycle core, and every spec poking them through the lifecycle always observe the same
 * instances. The core call-ins (cancelReconnect … updateStatus) are deliberately NON-async
 * passthrough closures onto the lifecycle's live methods (the Task-1 delegate rule: an `async`
 * wrapper would adopt the inner promise and add settlement hops the retirement-race specs assert
 * against). `dataSource` is a LIVE closure — never a captured value — because specs replace the
 * lifecycle's dataSource on the instance after construction (logout-teardown-race.spec) and
 * delete()'s transaction must observe the current one at call time.
 */
export interface SessionEngineControlsHost {
  sessionRepository: Repository<Session>;
  engineFactory: EngineFactory;
  engines: EngineRegistry;
  sessionErrors: SessionErrorStore;
  sessionRestrictions: SessionRestrictionStore;
  deviceAlerts: DeviceAlertService;
  presence: PresenceStore;
  hookManager: HookManager;
  configService?: ConfigService;
  logger: ReturnType<typeof createLogger>;
  /** LIVE closure — read at call time, never captured (specs replace lifecycle.dataSource at runtime). */
  dataSource(): DataSource;
  fences: SessionLifecycleFences;
  broadcaster: SessionStatusBroadcaster;
  cancelReconnect(id: string): void;
  initializeEngine(id: string, session: Session): Promise<void>;
  isSessionRetired(id: string): Promise<boolean>;
  purgeAuthDirsIfDeleted(id: string, name: string): Promise<void>;
  updateStatus(id: string, status: SessionStatus): Promise<void>;
  stoppingSessions: Set<string>;
  reconnectStates: Map<string, ReconnectState>;
  stuckAuthRecoveryUsed: Set<string>;
  initializingSessions: Set<string>;
}

/**
 * Public control verbs extracted from SessionEngineLifecycle: start/stop/resetProfile/logout/
 * forceKill/delete/shutdown/stopOrphanEngines, plus private findOne-or-404 requireSession. Plain class
 * (NOT a NestJS provider — the lifecycle's constructor signature is frozen by specs), built inside
 * the lifecycle's constructor; the lifecycle keeps all 7 verbs as one-line NON-async delegates, so
 * SessionService's public API path and every spec calling the verbs on the lifecycle stay
 * byte-identical. The dependency values and shared state containers are assigned to same-named
 * fields (by reference), so the method bodies below read like the inline originals; every former
 * core call-in (`this.cancelReconnect`, `this.initializeEngine`, `this.isSessionRetired`,
 * `this.purgeAuthDirsIfDeleted`, `this.updateStatus`) goes through `host`, the fences through the
 * `fences` unit, and delete()'s transaction reads `this.host.dataSource()` — the LIVE closure — at
 * call time. Method bodies and their comments/docstrings moved verbatim.
 */
export class SessionEngineControls {
  private readonly sessionRepository: Repository<Session>;
  private readonly engineFactory: EngineFactory;
  private readonly engines: EngineRegistry;
  private readonly sessionErrors: SessionErrorStore;
  private readonly sessionRestrictions: SessionRestrictionStore;
  private readonly deviceAlerts: DeviceAlertService;
  private readonly presence: PresenceStore;
  private readonly hookManager: HookManager;
  private readonly configService?: ConfigService;
  private readonly logger: ReturnType<typeof createLogger>;
  private readonly fences: SessionLifecycleFences;
  private readonly broadcaster: SessionStatusBroadcaster;
  private readonly stoppingSessions: Set<string>;
  private readonly reconnectStates: Map<string, ReconnectState>;
  private readonly stuckAuthRecoveryUsed: Set<string>;
  private readonly initializingSessions: Set<string>;

  constructor(private readonly host: SessionEngineControlsHost) {
    this.sessionRepository = host.sessionRepository;
    this.engineFactory = host.engineFactory;
    this.engines = host.engines;
    this.sessionErrors = host.sessionErrors;
    this.sessionRestrictions = host.sessionRestrictions;
    this.deviceAlerts = host.deviceAlerts;
    this.presence = host.presence;
    this.hookManager = host.hookManager;
    this.configService = host.configService;
    this.logger = host.logger;
    this.fences = host.fences;
    this.broadcaster = host.broadcaster;
    this.stoppingSessions = host.stoppingSessions;
    this.reconnectStates = host.reconnectStates;
    this.stuckAuthRecoveryUsed = host.stuckAuthRecoveryUsed;
    this.initializingSessions = host.initializingSessions;
  }

  /** findOne-or-404 with the runtime-state projection, mirroring SessionService.findOne. */
  private async requireSession(id: string): Promise<Session> {
    const session = await this.sessionRepository.findOne({ where: { id } });
    if (!session) {
      throw new NotFoundException(`Session with id '${id}' not found`);
    }
    return this.sessionRestrictions.attachTo(this.sessionErrors.attachTo(session));
  }

  async start(id: string): Promise<Session> {
    // Reserve the slot SYNCHRONOUSLY at entry — before even the requireSession await. Two
    // near-simultaneous start() calls must not both pass the check and orphan an engine (the has()
    // -> engines.set() window spans the awaited hook below), and the infra import pre-flight
    // (getActiveSessionIds) must see an in-flight start during the findOne round-trip too: registered
    // only after the row read, a start would be invisible in that window and a stopOrphans import
    // could DELETE the session row while an engine for it is being created. The finally clears the
    // reservation on success AND failure so a failed start never wedges at "already starting".
    if (this.initializingSessions.has(id)) {
      throw new BadRequestException('Session is already starting');
    }
    this.initializingSessions.add(id);

    try {
      const session = await this.requireSession(id);

      if (this.engines.has(id)) {
        throw new BadRequestException('Session is already started');
      }
      const maxConcurrentSessions = resolveMaxConcurrentSessions(this.configService);
      if (maxConcurrentSessions !== null) {
        // Count each OTHER session once. A session mid-initialization is transiently in BOTH
        // `engines` (set at the start of initializeEngine) and `initializingSessions` (until
        // start()'s finally), so summing the two sizes would double-count it; and `id` itself is
        // already reserved in `initializingSessions` (added at entry), so it must not count
        // against the cap it is being checked against.
        const activeIds = new Set<string>(this.engines.activeIds());
        activeIds.delete(id);
        if (activeIds.size >= maxConcurrentSessions) {
          throw new BadRequestException(`Maximum concurrent sessions reached (${maxConcurrentSessions})`);
        }
      }

      // Credential-teardown fence — runs IMMEDIATELY after the read-only session read + duplicate/cap
      // checks and BEFORE any lifecycle mutation (stop-mark clear, hook, reconnect-state, engine
      // creation, recovery-budget reset) or auth-dir access. A logout teardown that lost its deadline
      // race is still running and ends in an fs.rm of this session's on-disk profile — the same path
      // initializeEngine is about to populate. The fence is keyed by session NAME (the auth-dir key)
      // and FAIL CLOSED: a still-wedged teardown could still rm a fresh profile under this name, so
      // refuse with a retryable 409 instead of proceeding. On a 409, no lifecycle state is touched
      // (the stop mark, reconnect timer, engine, last status/error, and recovery budget are left as
      // they were) — start() simply did not happen. The one transient exception is the
      // initializingSessions reservation added synchronously at start() entry: its finally removes it
      // again, so a refused start does not leave a false "already starting" mark behind (briefly held).
      await this.fences.awaitPendingTeardown(session.name);

      // A fresh start intentionally (re-)creates the engine — clear any stale stop/delete mark.
      this.stoppingSessions.delete(id);

      // Cancel any reconnect timer a prior failed executeReconnect left pending, BEFORE the awaited
      // session:starting hook and engine init — otherwise the stale timer can fire during that I/O
      // and destroy/replace the engine this start() is about to create (or orphan the Chromium
      // process). Idempotent: a no-op when no reconnect state exists (the common fresh-start case).
      this.host.cancelReconnect(id);

      // Execute hook before starting
      await this.hookManager.execute(
        'session:starting',
        { sessionId: id },
        {
          sessionId: id,
          source: 'SessionService',
        },
      );

      // Initialize reconnect state from the (untrusted) opaque session.config — coerced + clamped
      // so a poisoned value can't drive a NaN/immediate-relaunch storm or an unbounded loop.
      const { maxAttempts, baseDelay } = resolveReconnectConfig(session.config);
      this.reconnectStates.set(id, { attempts: 0, timer: null, maxAttempts, baseDelay });

      // An accepted top-level start() re-arms the stuck-auth recovery budget: every fence above
      // (duplicate-start, cap, credential-teardown) passed, so this is a deliberate, operator-initiated
      // (re)start — not an automatic reconnect. The budget is hoisted to the session so an automatic
      // reconnect can't reset it per generation; only a fresh top-level episode may spend it again.
      // Boot auto-start reaches here through this same method, so it re-arms too.
      this.stuckAuthRecoveryUsed.delete(id);

      try {
        await this.host.initializeEngine(id, session);
      } catch (err) {
        // engine.initialize() failed AFTER the engine was registered (initializeEngine sets it before
        // initializing). Evict + tear it down so the session doesn't wedge at "already started" with a
        // leaked Chromium/socket permanently holding a concurrency slot. initializingSessions serializes
        // start(), so the engine in the map here is the one this start just created.
        //
        // Use forceDestroy(), not destroy(): initialize() failing usually means the underlying
        // browser/CDP connection is already broken (e.g. a "Target closed" crash mid-injection), so
        // a graceful destroy() has nothing live to talk to — it can only time out via
        // teardownEngineSafely's race, after which the orphaned Chromium process is never actually
        // killed. forceDestroy() SIGKILLs the OS process directly, the same recovery force-kill uses
        // for a wedged engine, which is exactly the state this catch block is handling.
        const orphan = this.engines.getLifecycle(id);
        if (orphan) {
          this.engines.delete(id);
          this.sessionErrors.set(id, err instanceof Error ? err.message : String(err));
          await this.fences.teardownEngineSafely(id, orphan, e => e.forceDestroy(), 'force-destroy');
          await this.host.updateStatus(id, SessionStatus.FAILED).catch(() => undefined);
        }
        // Drop the reconnect state this start() armed up front: no engine was registered, so
        // nothing will ever fire it, and leaving it behind is dead state a later liveness check
        // would have to reason about. A retry builds its own.
        this.host.cancelReconnect(id);
        throw err;
      }

      // A stop()/delete() may have landed while we awaited engine.initialize() — if so, tear down the
      // engine we just registered so the session isn't resurrected to READY (mirrors the post-init
      // guard in executeReconnect; initialize()'s callbacks can also fire async after this returns).
      // delete() clears its teardown mark before this slow init resolves, so re-check the session row
      // exists, not just the mark; the requireSession below then surfaces a deleted session as NotFound.
      if (await this.host.isSessionRetired(id)) {
        const resurrected = this.engines.getLifecycle(id);
        if (resurrected) {
          await this.fences.teardownEngineSafely(id, resurrected, e => e.destroy(), 'destroy');
          this.engines.deleteIfLive(id, resurrected);
        }
        // A delete() that raced this start purged the on-disk auth dirs BEFORE this init re-created
        // them — purge again so the window leaves no credential residue behind (no-op for a stop()).
        await this.host.purgeAuthDirsIfDeleted(id, session.name);
      }
      return this.requireSession(id);
    } finally {
      this.initializingSessions.delete(id);
    }
  }

  async stop(id: string): Promise<Session> {
    const session = await this.requireSession(id);

    // Mark as tearing down BEFORE cleanup so an in-flight reconnect can't resurrect it.
    this.stoppingSessions.add(id);
    // Cancel any reconnection attempts
    this.host.cancelReconnect(id);

    // Disconnect the engine — time-bounded + isolated so a stuck socket can't wedge the stop; the
    // Map is reconciled regardless. (The stop mark is intentionally left set, matching the prior
    // behaviour: a later start() clears it; it guards against a late reconnect resurrecting the id.)
    const engine = this.engines.getLifecycle(id);
    if (engine) {
      // Await THIS engine's in-flight INITIALIZING write before teardown / the final DISCONNECTED
      // write so a delayed pre-initialize status update can never settle after the retirement and
      // become the last persisted status. Identity-checked: only the captured engine's promise.
      await this.fences.awaitInitialStatus(id, engine);
      await this.fences.teardownEngineSafely(id, engine, e => e.disconnect(), 'disconnect');
      this.engines.deleteIfLive(id, engine);
    }

    this.logger.log(`Session stopped: ${session.name}`, {
      sessionId: id,
      action: 'stop',
    });
    await this.sessionRepository.update(id, { historySyncToken: null });
    await this.host.updateStatus(id, SessionStatus.DISCONNECTED);
    return this.requireSession(id);
  }

  /**
   * Remove only engine credentials/profile. Session row, immutable phone identity, and every stored
   * message remain. Final DISCONNECTED + manualStartRequired prevents global auto-start from silently
   * generating a QR on the next process boot; a successful future READY clears that flag.
   */
  async resetProfile(id: string): Promise<Session> {
    const session = await this.requireSession(id);
    await this.fences.awaitPendingTeardown(session.name);
    this.stoppingSessions.add(id);
    this.host.cancelReconnect(id);

    const engine = this.engines.getLifecycle(id);
    if (engine) {
      await this.fences.awaitInitialStatus(id, engine);
      await this.fences.teardownEngineSafely(id, engine, e => e.forceDestroy(), 'force-destroy');
      this.engines.deleteIfLive(id, engine);
    }

    // A logout may have begun after the first fence but before engine eviction. Do not race its rm
    // against this explicit purge; fail closed with the established retryable 409.
    await this.fences.awaitPendingTeardown(session.name);
    await this.engineFactory.purgeSessionDataOrThrow(session.name);
    await this.sessionRepository.update(id, {
      status: SessionStatus.DISCONNECTED,
      config: requireManualStart(session.config) as never,
      historySyncToken: null,
      historySyncError: null,
      nodeId: null,
      claimedAt: null,
      leaseExpiresAt: null,
    });
    this.sessionErrors.clear(id);
    this.presence.clear(id);
    this.broadcaster.publishPersistedStatus(id, SessionStatus.DISCONNECTED);
    this.logger.warn(`Session profile reset: ${session.name}`, {
      sessionId: id,
      action: 'profile_reset',
    });
    return this.requireSession(id);
  }

  /**
   * Log out of WhatsApp — attempts an engine-native unlink of this device, then tears the session
   * down locally regardless of the unlink outcome.
   *
   * Differs from stop() in the one way that matters to a user: logout() asks WhatsApp to remove the
   * companion device, so a completed unlink eventually makes the entry disappear from the account
   * holder's Linked Devices list. stop() and delete() only release things locally (delete also
   * purges the on-disk auth dirs).
   *
   * Completion (HTTP 200) means the engine-native unlink operation completed AND the required local
   * credential cleanup completed — for Baileys, a valid companion identity, an acknowledged
   * `remove-companion-device` IQ response, and removal of the on-disk auth dir; for whatsapp-web.js,
   * `Client.logout()` including `LocalAuth.logout()` settled. 200 is NOT an independent observation
   * that the handset UI no longer shows the linked device — only the linked-device canary observes
   * that, and the dashboard must not claim otherwise.
   *
   * Must run while the engine is still live — logout is a network round-trip to WhatsApp, so it
   * cannot be performed after destroy()/forceDestroy(). Mirrors stop()'s lifecycle otherwise
   * (stop-mark + cancel-reconnect + bounded, isolated teardown + Map reconciliation).
   *
   * Requires a started session: with no engine loaded there is nothing to send the unlink through,
   * so the request is rejected with 400 rather than reporting an unlink that never happened. A 400
   * does NOT change the row. To just release a stopped session locally, use stop()/delete().
   *
   * Throws a retryable BadGatewayException (502) carrying a stable `code: 'SESSION_LOGOUT_INCOMPLETE'`
   * when an accepted engine-backed attempt stopped locally but the unlink operation did NOT complete
   * — no identity/no send, no IQ acknowledgement, timeout/transport error, OR local credential
   * cleanup failure. After EVERY engine-backed attempt (200 OR 502) the session is torn down locally
   * (map reconciled, status ACTION_REQUIRED) while identity/checkpoint/data remain bound. No success audit is written on
   * the 502 path (the controller audits SESSION_LOGGED_OUT only after the service resolves). The
   * operator can start the session and retry the logout.
   */
  async logout(id: string): Promise<Session> {
    const session = await this.requireSession(id);
    const engine = this.engines.getLifecycle(id);

    if (!engine) {
      throw new BadRequestException('Session is not started. Call POST /sessions/:id/start first.');
    }

    // Mark as tearing down BEFORE cleanup so an in-flight reconnect can't resurrect it.
    this.stoppingSessions.add(id);
    // Cancel any reconnection attempts
    this.host.cancelReconnect(id);

    // Await THIS engine's in-flight INITIALIZING write before teardown / the final DISCONNECTED
    // write so a delayed pre-initialize status update can never settle after the retirement.
    await this.fences.awaitInitialStatus(id, engine);
    // The credential fence is keyed by session NAME (the auth-dir key). Captured immutably here so a
    // raw logout that outlives its deadline race is tracked under the right name even if the row is
    // later deleted/recreated.
    const unlinked = await this.fences.teardownEngineSafely(id, engine, e => e.logout(), 'logout', session.name);
    this.engines.deleteIfLive(id, engine);

    if (!unlinked) {
      this.logger.warn(`Session stopped locally but the logout operation did not complete: ${session.name}`, {
        sessionId: id,
        action: 'logout_incomplete',
      });
      // Preserve immutable identity/history ownership. ACTION_REQUIRED excludes boot auto-start and
      // leaves a durable reason; an operator may explicitly start and retry after reviewing the device.
      this.sessionErrors.set(
        id,
        'Logout did not complete. Bound identity and stored history were preserved; start manually and retry.',
      );
      await this.sessionRepository.update(id, {
        status: SessionStatus.ACTION_REQUIRED,
        historySyncToken: null,
        historySyncError: 'LOGOUT_INCOMPLETE',
      });
      await this.host.updateStatus(id, SessionStatus.ACTION_REQUIRED);
      throw new BadGatewayException({
        statusCode: HttpStatus.BAD_GATEWAY,
        message:
          'Session was stopped locally, but the logout operation is incomplete — the device may ' +
          'still be linked. Start the session and retry the logout.',
        error: 'Bad Gateway',
        code: 'SESSION_LOGOUT_INCOMPLETE',
      });
    }

    // Credentials are gone, but identity/history ownership is permanent. CREATED is manually
    // startable and excluded from boot auto-start; the next QR must validate as the same phone.
    await this.sessionRepository.update(id, {
      status: SessionStatus.CREATED,
      historySyncToken: null,
      historySyncError: null,
    });
    await this.host.updateStatus(id, SessionStatus.CREATED);

    this.logger.log(`Session logged out: ${session.name}`, {
      sessionId: id,
      action: 'logout',
    });
    // Told at once, unlike a dropped connection: an unlink is not coming back on
    // its own, and until somebody scans a QR nothing arrives on that number. The
    // Use the captured phone so alerting is independent of the post-teardown read.
    this.deviceAlerts.reportUnlinked(id, session.phone, session.name);
    return this.requireSession(id);
  }

  /**
   * Force-recover a stuck session: SIGKILL its engine's own resources (a wedged Chromium for the
   * whatsapp-web.js engine) and tear it down, even when a normal stop()/delete() can't because the
   * engine is hung. Mirrors stop()'s lifecycle (stop-mark + cancel-reconnect + bounded, isolated
   * teardown + Map reconciliation) but uses the engine's forceDestroy().
   */
  async forceKill(id: string): Promise<Session> {
    const session = await this.requireSession(id);
    const engine = this.engines.getLifecycle(id);

    // No live engine means there is nothing to SIGKILL. Resolving would let the controller write a
    // SESSION_FORCE_KILLED audit row for a kill that never happened — mirror logout()'s not-started
    // refusal. A wedged engine torn down earlier is reaped by the next start()'s orphan sweep (and
    // by process exit), not by force-kill.
    if (!engine) {
      throw new BadRequestException('Session is not started. Call POST /sessions/:id/start first.');
    }

    // Mark as tearing down BEFORE cleanup so an in-flight reconnect can't resurrect it.
    this.stoppingSessions.add(id);
    this.host.cancelReconnect(id);

    // Await THIS engine's in-flight INITIALIZING write before teardown / the final DISCONNECTED
    // write so a delayed pre-initialize status update can never settle after the retirement.
    await this.fences.awaitInitialStatus(id, engine);
    await this.fences.teardownEngineSafely(id, engine, e => e.forceDestroy(), 'force-destroy');
    this.engines.deleteIfLive(id, engine);

    this.logger.warn(`Session force-killed: ${session.name}`, {
      sessionId: id,
      action: 'force_kill',
    });
    await this.sessionRepository.update(id, { historySyncToken: null });
    await this.host.updateStatus(id, SessionStatus.DISCONNECTED);
    return this.requireSession(id);
  }

  async delete(id: string, confirmedMessageCount: number): Promise<void> {
    const session = await this.requireSession(id);

    // FENCE #1 — fail-fast on an ALREADY-PENDING credential teardown for this session NAME, BEFORE
    // any lifecycle mutation. A logout teardown that lost its deadline race is still running and ends
    // in an fs.rm of this session's on-disk auth dir (keyed by name). Releasing the name via the DB
    // delete below while that rm is live would let a recreated session under the same name race the
    // stale rm. The fence is keyed by session NAME and fails CLOSED (409). On a 409 NOTHING else runs:
    // no stop mark, no reconnect cancel, no engine teardown, no state cleanup — delete() simply did
    // not happen, and the entry stays reserved.
    await this.fences.awaitPendingTeardown(session.name);

    // Mark as tearing down BEFORE cleanup so an in-flight reconnect can't resurrect it.
    this.stoppingSessions.add(id);
    // Cancel any reconnection attempts
    this.host.cancelReconnect(id);

    // Set only after the transaction actually removes the parent row. lastDispatchedStatus /
    // sessionErrors (and the recovery budget, Task 8) are cleared ONLY on a committed delete; a
    // rejected 409 from fence #2 leaves them intact (the session still exists).
    let parentDeleted = false;

    try {
      // Stop engine if running — time-bounded + isolated so a stuck Chromium can't wedge the delete;
      // the Map is reconciled and the DB removal proceeds regardless of the outcome. Use forceDestroy()
      // (SIGKILL) rather than a graceful destroy(): the session is being removed permanently, so there is
      // no session state worth saving, and a wedged Chromium must be reaped, not left to time out.
      const engine = this.engines.getLifecycle(id);
      if (engine) {
        // Await THIS engine's in-flight INITIALIZING write before teardown and the parent-row
        // deletion below, so a delayed pre-initialize status update can never settle after the row
        // is gone (delete cannot be followed by a late status write). Identity-checked.
        await this.fences.awaitInitialStatus(id, engine);
        await this.fences.teardownEngineSafely(id, engine, e => e.forceDestroy(), 'force-destroy');
        this.engines.deleteIfLive(id, engine);
      }

      // FENCE #2 — immediately after the current engine is evicted, BEFORE the session:deleted hook
      // and the DB transaction. A logout that started concurrently AFTER fence #1 but captured this
      // engine before eviction registers its destructive promise synchronously (via the engine's
      // onCredentialTeardownStarted callback), so this fence sees it and refuses — the row/name stay
      // reserved and the transaction does not run. After eviction a NEW logout can't create a
      // destructive promise (no live engine); one that already captured the engine is observed here.
      //
      // Unlike fence #1, a refusal HERE leaves the row behind with its engine already destroyed, so
      // the persisted status would keep reading whatever it was (READY, authenticating, …) for a
      // session that can no longer answer anything. Reconcile it to DISCONNECTED before propagating
      // the 409 — the retry the message asks for should not have to look past a status that lies.
      // Fence #1 needs none of this: nothing has run there yet, so its status is still accurate.
      // Best-effort: a failed status write must not mask the 409 the caller has to act on.
      try {
        await this.fences.awaitPendingTeardown(session.name);
      } catch (fenceError) {
        if (engine) {
          await this.host.updateStatus(id, SessionStatus.DISCONNECTED).catch(() => undefined);
        }
        throw fenceError;
      }

      // Soft-remove: confirm the operator still sees the same message count, then keep every
      // stored message and the session row. Auth is purged so the handset must re-link; removedAt
      // marks the record for All chats (list-only) until Start + reconnect clears it.
      await this.host.dataSource().transaction(async manager => {
        const messageCount = await manager.count(Message, { where: { sessionId: id } });
        if (messageCount !== confirmedMessageCount) {
          throw new ConflictException({
            statusCode: HttpStatus.CONFLICT,
            code: 'SESSION_DELETE_COUNT_CHANGED',
            message: 'Stored message count changed. Review the new impact and confirm again.',
            confirmedMessageCount,
            messageCount,
          });
        }
        const removedAt = new Date();
        await manager.update(Session, id, {
          status: SessionStatus.DISCONNECTED,
          removedAt,
          config: requireManualStart(session.config) as never,
          historySyncToken: null,
          historySyncError: null,
          nodeId: null,
          claimedAt: null,
          leaseExpiresAt: null,
        });
      });
      parentDeleted = true;

      await this.hookManager.execute(
        'session:deleted',
        {
          id: session.id,
          name: session.name,
          phone: session.phone,
          pushName: session.pushName,
          softRemoved: true,
        },
        {
          sessionId: id,
          source: 'SessionService',
        },
      );

      this.logger.log(`Session soft-removed (messages kept): ${session.name}`, {
        sessionId: id,
        action: 'soft_remove',
      });

      // Purge auth dirs so a later Start under this same name cannot silently reuse a dead link.
      await this.engineFactory.purgeSessionData(session.name);
      this.broadcaster.publishPersistedStatus(id, SessionStatus.DISCONNECTED);
    } finally {
      // Always clear the teardown mark so a later recreate/start with this id isn't suppressed. This
      // stop mark was set after fence #1, so clearing it on a rejected 409 only undoes what THIS
      // delete added — it does NOT touch reconnect timer / engine / last status / error / recovery
      // state (those are gated on parentDeleted below).
      this.stoppingSessions.delete(id);
      if (parentDeleted) {
        // Soft-remove keeps the UUID: clear only runtime maps that describe a live link. Do not
        // broadcaster.clear — the same session will Start again and must keep publishing status.
        this.sessionErrors.clear(id);
        this.sessionRestrictions.clear(id);
        this.presence.clear(id);
        this.stuckAuthRecoveryUsed.delete(id);
      }
      // NOTE: pendingTeardowns is intentionally NOT cleared here. It is keyed by session NAME and
      // its entries self-remove on settlement (identity-checked). A delete that refused at either
      // fence MUST leave the entry in place — the name is still reserved against the live remover —
      // and a delete that succeeded already saw both fences pass, so no live remover exists.
    }
  }

  /**
   * The engine half of SessionService.onModuleDestroy: stop reconnect timers FIRST so nothing
   * reschedules mid-teardown (and so this always runs even if an engine.destroy() below hangs or
   * throws), then destroy engines in parallel, each isolated + time-bounded, so one stuck Chromium
   * can neither stall the shutdown nor abort teardown of the other sessions.
   */
  async shutdown(): Promise<void> {
    for (const [, state] of this.reconnectStates) {
      if (state.timer) {
        clearTimeout(state.timer);
      }
    }
    this.reconnectStates.clear();

    await Promise.allSettled(
      [...this.engines].map(([sessionId, engine]) => this.fences.destroyEngineSafely(sessionId, engine)),
    );
    this.engines.clear();
  }

  /**
   * Stop the engines for the given session ids WITHOUT touching the sessions DB row (the caller,
   * the infra import path, is about to DELETE that row as part of a full replace). This is the one
   * stop path that bypasses the session-row-keyed controls — every other path keys through the row,
   * so an engine orphaned by a restore was previously unstoppable until process restart.
   *
   * Each id is handled in isolation and time-bounded: a stuck Chromium/socket on one orphan can
   * neither stall nor abort the others, and the whole call is bounded by teardownEngineSafely's
   * per-engine 10s deadline. The mark + reconnect-cancel happen first so an in-flight reconnect
   * cannot resurrect the id while teardown runs. Engines that are mid-initialization (no entry in
   * `engines` yet) are marked but cannot be torn down here — their start() will see the stop mark
   * via its existing guard and self-abort; the caller learns about them in `notRunning`.
   *
   * Always resolves. Best-effort: a `failed` entry means teardown threw or timed out, and the engine
   * is removed from the Map regardless so it stops holding a concurrency slot.
   */
  async stopOrphanEngines(
    sessionIds: string[],
  ): Promise<{ stopped: string[]; notRunning: string[]; failed: string[] }> {
    const stopped: string[] = [];
    const notRunning: string[] = [];
    const failed: string[] = [];

    if (sessionIds.length === 0) return { stopped, notRunning, failed };

    await Promise.allSettled(
      sessionIds.map(async id => {
        // Mark + cancel BEFORE teardown so a late reconnect cannot resurrect the id mid-teardown.
        this.stoppingSessions.add(id);
        this.host.cancelReconnect(id);

        const engine = this.engines.getLifecycle(id);
        if (!engine) {
          // Either never started, or still inside initializeEngine (no Map entry yet). The stop mark
          // above is what aborts the initializing case via start()'s existing guard.
          notRunning.push(id);
          return;
        }
        try {
          const tornDown = await this.fences.destroyEngineSafely(id, engine);
          // The engine leaves the Map regardless of teardown outcome so it stops holding a
          // concurrency slot — but only a completed teardown counts as `stopped`. A throw/timeout
          // means the Chromium/socket may still be alive and writing, so the id lands in `failed`
          // and the caller (the infra import) can flag restartRequired instead of reporting a
          // clean stop for a wedged engine.
          this.engines.deleteIfLive(id, engine);
          if (tornDown) {
            stopped.push(id);
          } else {
            failed.push(id);
          }
        } catch (err) {
          // destroyEngineSafely never throws today (it isolates via teardownEngineSafely), but defend
          // against a future change so a single orphan cannot abort the batch.
          this.logger.error(`Failed to stop orphan engine for session ${id}`, String(err), {
            sessionId: id,
            action: 'stop_orphan_failed',
          });
          this.engines.deleteIfLive(id, engine);
          failed.push(id);
        }
      }),
    );

    return { stopped, notRunning, failed };
  }
}
