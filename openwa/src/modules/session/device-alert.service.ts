import { Injectable } from '@nestjs/common';
import { createLogger } from '../../common/services/logger.service';

/**
 * Report a linked handset that has stopped being linked.
 *
 * When a phone is unlinked the inbox simply stops receiving on that number. No
 * screen says so, no status changes that anybody is watching, and the first sign
 * is a customer complaining that nobody answered. This tells the backend, which
 * sends the WhatsApp alert — the sending lives there because the WABA templates,
 * the numbers and the gateway credentials all already do.
 *
 * Deliberately NOT built on the per-session webhook table. A webhook is a row
 * somebody has to remember to create, per session; the next number an agent
 * links would silently have no alert on it, and nothing would look wrong. This
 * is configuration on the process, so it covers every session including ones
 * that do not exist yet.
 *
 * Two kinds of "gone", told apart because they deserve different treatment:
 *
 *   unlinked  — the agent removed the device, or WhatsApp did. It is not coming
 *               back on its own, so the alert goes at once.
 *   dropped   — the connection fell over. Most of these recover in seconds
 *               through the reconnect backoff, and alerting on each one would
 *               send a message every time a phone loses signal in a lift. Held
 *               for {@link DROPPED_GRACE_MS} and cancelled if it comes back.
 */
@Injectable()
export class DeviceAlertService {
  private readonly logger = createLogger('DeviceAlert');

  /** Pending "it dropped" alerts, by session id, cancelled when the session returns. */
  private readonly pending = new Map<string, NodeJS.Timeout>();

  /**
   * How long a dropped connection is given to come back before anybody is told.
   *
   * Long enough that an ordinary reconnect never raises an alert, short enough
   * that a phone genuinely off is reported while the day can still be salvaged.
   */
  static readonly DROPPED_GRACE_MS = 10 * 60 * 1000;

  /** The handset is gone and is not coming back by itself. Tell them now. */
  reportUnlinked(sessionId: string, phone: string | null | undefined, sessionName: string): void {
    this.cancel(sessionId); // an unlink supersedes any pending "it dropped"
    void this.post(phone, sessionName, 'logged out');
  }

  /**
   * The connection fell over. Start the clock; {@link reportBack} cancels it.
   *
   * Re-arming on a second drop while one is already pending is deliberately a
   * no-op: a session flapping every thirty seconds would otherwise keep pushing
   * its own deadline back and never report at all.
   */
  reportDropped(sessionId: string, phone: string | null | undefined, sessionName: string, reason: string): void {
    if (this.pending.has(sessionId)) return;

    const timer = setTimeout(() => {
      this.pending.delete(sessionId);
      void this.post(phone, sessionName, `disconnected (${reason})`);
    }, DeviceAlertService.DROPPED_GRACE_MS);

    // Node keeps the process alive for a pending timer; a ten-minute one would
    // hold a shutdown open for ten minutes. An alert is not worth that.
    timer.unref?.();
    this.pending.set(sessionId, timer);

    this.logger.log(`Connection lost; alerting in ${DeviceAlertService.DROPPED_GRACE_MS / 60000} minutes if it stays down`, {
      sessionId,
      reason,
      action: 'device_alert_armed',
    });
  }

  /** The session is live again — whatever was waiting to be reported never happened. */
  reportBack(sessionId: string): void {
    if (this.cancel(sessionId)) {
      this.logger.log('Session recovered before the alert was due; nobody was told', {
        sessionId,
        action: 'device_alert_cancelled',
      });
    }
  }

  private cancel(sessionId: string): boolean {
    const timer = this.pending.get(sessionId);
    if (!timer) return false;
    clearTimeout(timer);
    this.pending.delete(sessionId);
    return true;
  }

  /**
   * Hand it to the backend. Never throws: this is called from lifecycle paths
   * that have already done their real work, and a failure to *tell* somebody
   * must not be reported as a failure to notice.
   */
  private async post(phone: string | null | undefined, sessionName: string, reason: string): Promise<void> {
    const url = process.env.DEVICE_ALERT_URL;
    const secret = process.env.DEVICE_ALERT_SECRET;
    if (!url || !secret) {
      this.logger.warn('A linked device went away but alerting is not configured', {
        sessionName,
        reason,
        action: 'device_alert_unconfigured',
      });
      return;
    }

    try {
      // Bounded: the backend is a container away, and an alert that hangs holds
      // nothing useful open. Ten seconds is generous for one HTTP hop.
      const abort = AbortSignal.timeout(10_000);
      const response = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Alert-Secret': secret },
        body: JSON.stringify({ phone: phone ?? null, sessionName, reason }),
        signal: abort,
      });
      if (!response.ok) {
        this.logger.warn(`The alert was refused: HTTP ${response.status}`, {
          sessionName,
          reason,
          action: 'device_alert_refused',
        });
        return;
      }
      this.logger.log('A linked device went away and the alert was accepted', {
        sessionName,
        reason,
        action: 'device_alert_sent',
      });
    } catch (error) {
      this.logger.warn('Could not deliver the device alert', {
        sessionName,
        reason,
        error: error instanceof Error ? error.message : String(error),
        action: 'device_alert_failed',
      });
    }
  }
}
