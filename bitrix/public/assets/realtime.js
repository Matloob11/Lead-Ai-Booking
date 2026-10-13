/**
 * Live inbox feed over /ws/inbox/.
 *
 * The socket rides the same session cookie as the REST calls, so there is no
 * token to pass. On every (re)connect the caller is told to refetch, because a
 * dropped socket means missed events and the REST state is the source of truth.
 */

const WS_PATH = "/ws/inbox/";
const RETRY_MIN_MS = 1000;
const RETRY_MAX_MS = 30000;

/** The server closes an unauthenticated socket with this code. */
export const CLOSE_UNAUTHENTICATED = 4401;

export class InboxSocket {
  constructor({ onEvent, onStatus, onAuthLost }) {
    this.onEvent = onEvent;
    this.onStatus = onStatus || (() => {});
    this.onAuthLost = onAuthLost || null;
    this.socket = null;
    this.retryMs = RETRY_MIN_MS;
    this.timer = null;
    this.closedByUs = false;
    this.hasConnectedBefore = false;
  }

  get url() {
    const scheme = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${scheme}//${window.location.host}${WS_PATH}`;
  }

  connect() {
    this.closedByUs = false;
    clearTimeout(this.timer);

    let socket;
    try {
      socket = new WebSocket(this.url);
    } catch (error) {
      console.warn("[a7-wa] websocket construct failed:", error);
      this.scheduleRetry();
      return;
    }
    this.socket = socket;

    socket.addEventListener("open", () => {
      this.retryMs = RETRY_MIN_MS;
      // A reconnect means we were deaf for a while — the caller must resync.
      this.onStatus({ state: "open", resync: this.hasConnectedBefore });
      this.hasConnectedBefore = true;
    });

    socket.addEventListener("message", (event) => {
      let payload;
      try {
        payload = JSON.parse(event.data);
      } catch {
        console.warn("[a7-wa] unparseable ws frame:", event.data);
        return;
      }
      // Channels usually wraps the body; accept both shapes.
      const type = payload.type || payload.event;
      const data = payload.data ?? payload.payload ?? payload;
      if (!type) return;

      this.onEvent(type, data);

      // Re-broadcast on the window so the companion modules can listen without
      // being wired into the inbox. Dispatched for every event, including the
      // ones the inbox itself ignores.
      window.dispatchEvent(new CustomEvent("wa:event", { detail: { event: type, data } }));
    });

    socket.addEventListener("close", (event) => {
      if (this.closedByUs) return;

      // Retrying an unauthenticated socket just loops forever — the session has
      // to be re-established first, so hand that back to the caller.
      if (event.code === CLOSE_UNAUTHENTICATED) {
        this.onStatus({ state: "unauthenticated" });
        if (this.onAuthLost) {
          this.onAuthLost();
          return;
        }
      }

      this.onStatus({ state: "closed" });
      this.scheduleRetry();
    });

    socket.addEventListener("error", () => socket.close());
  }

  scheduleRetry() {
    clearTimeout(this.timer);
    this.onStatus({ state: "reconnecting", inMs: this.retryMs });
    this.timer = setTimeout(() => this.connect(), this.retryMs);
    this.retryMs = Math.min(this.retryMs * 2, RETRY_MAX_MS);
  }

  close() {
    this.closedByUs = true;
    clearTimeout(this.timer);
    this.socket?.close();
  }
}
