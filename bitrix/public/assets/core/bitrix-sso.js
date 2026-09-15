/**
 * A7 WhatsApp Inbox — Bitrix24 SSO bridge.
 *
 * The panel runs inside a Bitrix24 LEFT_MENU placement iframe. Bitrix POSTs the
 * placement params (AUTH_ID / member_id / DOMAIN) to the handler URL, but the
 * handler here is a static file, so we read the same values client-side through
 * the JS SDK instead: BX24.getAuth() returns { access_token, member_id, domain }.
 *
 * Those three are handed to POST /api/auth/bitrix/, which verifies them against
 * the portal and sets the Django session cookie. Every later call rides that
 * cookie (SameSite=None; Secure), so the agent never sees a login form.
 */

const API_BASE = window.location.origin;
const BX24_SDK = "https://api.bitrix24.com/api/v1/";
const SDK_TIMEOUT_MS = 15000;

export class SsoError extends Error {
  constructor(code, message, detail) {
    super(message);
    this.name = "SsoError";
    this.code = code;
    this.detail = detail;
  }
}

/* ------------------------------------------------------------------ Bitrix */

let sdkPromise = null;

function asSsoError(error) {
  if (error instanceof SsoError) return error;
  return new SsoError(
    error?.code || "sdk_timeout",
    error?.message || "The Bitrix JS SDK did not load.",
    error?.detail ?? error
  );
}

/** Loads //api.bitrix24.com/api/v1/ and resolves once BX24.init() has fired. */
export function loadBX24() {
  if (sdkPromise) return sdkPromise;

  // Placement pages start BX24.init from bx24-early.js so Bitrix can drop the
  // "Loading WhatsApp" overlay before inbox.js has even downloaded. Calling
  // init a second time is how that overlay comes back and stays: some portal
  // builds never fire the later callback.
  if (window.__a7Bx24Ready) {
    sdkPromise = Promise.resolve(window.__a7Bx24Ready).then((bx) => {
      if (!bx) throw new SsoError("sdk_missing", "The BX24 object is still missing after the SDK loaded.");
      return bx;
    }, (error) => {
      throw asSsoError(error);
    });
    return sdkPromise;
  }

  sdkPromise = new Promise((resolve, reject) => {
    if (window.top === window.self) {
      reject(
        new SsoError(
          "not_in_frame",
          "The panel was opened outside Bitrix.",
          "This page only opens from the Bitrix24 left menu. Opening the URL directly leaves it with no way to authenticate."
        )
      );
      return;
    }

    const timer = setTimeout(() => {
      reject(
        new SsoError(
          "sdk_timeout",
          "The Bitrix JS SDK did not load.",
          `${BX24_SDK} did not respond within ${SDK_TIMEOUT_MS / 1000}s. The portal's internet access or its CSP may be blocking it.`
        )
      );
    }, SDK_TIMEOUT_MS);

    const done = () => {
      clearTimeout(timer);
      resolve(window.BX24);
    };

    if (window.BX24) {
      window.BX24.init(done);
      return;
    }

    const script = document.createElement("script");
    script.src = BX24_SDK;
    script.onload = () => {
      if (!window.BX24) {
        clearTimeout(timer);
        reject(new SsoError("sdk_missing", "The BX24 object is still missing after the SDK loaded."));
        return;
      }
      window.BX24.init(done);
    };
    script.onerror = () => {
      clearTimeout(timer);
      reject(new SsoError("sdk_unreachable", "The Bitrix JS SDK could not be downloaded.", BX24_SDK));
    };
    document.head.appendChild(script);
  });

  return sdkPromise;
}

/**
 * Placement params as the backend wants them. BX24.getAuth() returns `false`
 * when the token has expired, so we ask the portal to refresh it once.
 */
export async function getBitrixAuth({ allowRefresh = true } = {}) {
  const BX24 = await loadBX24();
  const auth = BX24.getAuth();

  if (!auth || !auth.access_token) {
    if (!allowRefresh) {
      throw new SsoError(
        "no_auth",
        "Bitrix did not return an authorization token.",
        "BX24.getAuth() is returning false — the app was not opened from its placement, or the token has expired."
      );
    }
    await refreshBitrixAuth();
    return getBitrixAuth({ allowRefresh: false });
  }

  return {
    AUTH_ID: auth.access_token,
    member_id: auth.member_id,
    DOMAIN: auth.domain,
  };
}

function withTimeout(promise, ms, code, message) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new SsoError(code, message)), ms);
    promise.then(
      (value) => {
        clearTimeout(timer);
        resolve(value);
      },
      (error) => {
        clearTimeout(timer);
        reject(error);
      }
    );
  });
}

/** Forces the portal to mint a fresh access token (they expire in ~1 hour). */
export function refreshBitrixAuth() {
  const pending = new Promise((resolve, reject) => {
    if (!window.BX24 || typeof window.BX24.refreshAuth !== "function") {
      reject(new SsoError("no_refresh", "BX24.refreshAuth is not available."));
      return;
    }
    window.BX24.refreshAuth((auth) => {
      if (auth && auth.access_token) resolve(auth);
      else reject(new SsoError("refresh_failed", "The Bitrix token could not be refreshed."));
    });
  });
  return withTimeout(
    pending,
    8000,
    "refresh_timeout",
    "Bitrix did not refresh the placement token. Close the slider and open WhatsApp from the left menu again."
  );
}

/** Promisified BX24.callMethod. */
export function callBitrix(method, params = {}) {
  const pending = new Promise((resolve, reject) => {
    window.BX24.callMethod(method, params, (result) => {
      const error = result.error();
      if (!error) {
        resolve(result.data());
        return;
      }
      // The SDK wraps REST errors differently across versions — sometimes the
      // payload sits on .ex, sometimes on the error object itself.
      const raw = error.ex || error;
      reject(new SsoError(raw.error || "rest_error", raw.error_description || String(error), { method, params }));
    });
  });
  return withTimeout(pending, 15000, "rest_timeout", `Bitrix ${method} did not answer.`);
}

/**
 * Makes sure the portal's main menu carries our "WhatsApp" item.
 *
 * Bitrix only runs the app's install handler when it installs the app itself;
 * an app registered by hand in Developer resources never gets that call, so the
 * placement would silently stay unbound. Checking it on an admin's page load
 * keeps the menu item self-healing — including after someone edits the handler
 * URL, which orphans the old binding.
 *
 * Never throws: a missing menu item must not stop the inbox from loading.
 *
 * `handler` defaults to the directory this page is served from, which is right
 * for LEFT_MENU — the menu item opens the page doing the binding. The CRM tabs
 * are the case that needs it stated: they open `/app/crm/`, a different
 * directory, and deriving the handler would have bound all five placements to
 * whichever page happened to be running.
 */
export async function ensurePlacement({
  placement = "LEFT_MENU",
  title = "WhatsApp",
  handler = new URL(".", window.location.href).href,
} = {}) {
  try {
    const bound = await callBitrix("placement.get");
    const existing = (bound || []).filter((row) => row.placement === placement);

    if (existing.some((row) => row.handler === handler)) return { status: "already-bound" };

    // A handler pointing somewhere else is a leftover from an older URL.
    for (const stale of existing) {
      await callBitrix("placement.unbind", { PLACEMENT: placement, HANDLER: stale.handler });
    }

    await callBitrix("placement.bind", { PLACEMENT: placement, HANDLER: handler, TITLE: title });
    return { status: existing.length ? "rebound" : "bound", handler };
  } catch (error) {
    console.warn("[a7-wa] placement bind skipped:", error);
    return { status: "failed", error };
  }
}

/* -------------------------------------------------------------------- HTTP */

/** Django's CSRF token, once /api/auth/me/ has handed us the cookie. */
export const csrfToken = () => readCookie("csrftoken");

function readCookie(name) {
  const hit = document.cookie
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith(`${name}=`));
  return hit ? decodeURIComponent(hit.slice(name.length + 1)) : null;
}

/**
 * fetch() against the panel API. Always sends the session cookie, attaches the
 * CSRF header when Django has handed us one, and surfaces the JSON error body.
 */
export async function apiFetch(path, { method = "GET", body, headers = {}, raw = false } = {}) {
  const init = {
    method,
    credentials: "include",
    headers: { Accept: "application/json", ...headers },
  };

  if (body instanceof FormData) {
    init.body = body;
  } else if (body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }

  if (method !== "GET" && method !== "HEAD") {
    const csrf = readCookie("csrftoken");
    if (csrf) init.headers["X-CSRFToken"] = csrf;
  }

  const response = await fetch(`${API_BASE}${path}`, init);
  if (raw) return response;

  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    throw new SsoError(
      `http_${response.status}`,
      (payload && (payload.detail || payload.error)) || `${method} ${path} → HTTP ${response.status}`,
      payload
    );
  }
  return payload;
}

/* --------------------------------------------------------------------- SSO */

/** Exchanges the Bitrix placement token for a Django session cookie. */
export async function ssoLogin() {
  const auth = await getBitrixAuth();
  return apiFetch("/api/auth/bitrix/", { method: "POST", body: auth });
}

/**
 * Whether the session we already hold belongs to the person sitting here.
 *
 * The panel used to accept any session that answered 200. Its cookie lives on
 * the panel's own host, not the portal's, so it outlives the Bitrix login that
 * created it — and the next colleague to open the panel in that browser was
 * handed the previous agent's inbox. The login endpoint was never called, so no
 * account was even created for the person actually using it.
 *
 * That is not a theory. One agent opened the panel under her own Bitrix login
 * and was shown a colleague's number and a colleague's customers, and the
 * database had no record of her at all.
 *
 * Unknown counts as "no". A cheap comparison that cannot be made is not a
 * reason to keep serving somebody else's conversations — the cost of being
 * wrong here is one agent reading another's customers, and the cost of a
 * needless re-login is one POST.
 */
async function sessionBelongsToCurrentUser(session) {
  const held = String(session?.bitrix_user_id || "");
  if (!held) return false;

  try {
    const profile = await callBitrix("profile");
    const current = String(profile?.ID ?? profile?.id ?? "");
    return Boolean(current) && current === held;
  } catch (error) {
    console.warn("[a7-wa] could not confirm who this session belongs to:", error);
    return false;
  }
}

/**
 * Returns the signed-in agent, logging in through Bitrix first if the session
 * cookie is missing, stale, or somebody else's. This is the single entry point
 * for the panel.
 */
export async function ensureSession() {
  const existing = await apiFetch("/api/auth/me/", { raw: true });

  if (existing.ok) {
    const session = await existing.json();
    if (await sessionBelongsToCurrentUser(session)) return session;
    // Somebody else's session, still valid. Replaced below rather than
    // reported: a stale cookie is not an error, it is the wrong answer.
  } else if (existing.status !== 401 && existing.status !== 403) {
    throw new SsoError(
      `http_${existing.status}`,
      `GET /api/auth/me/ → HTTP ${existing.status}`,
      await existing.text().catch(() => null)
    );
  }

  await ssoLogin();

  const fresh = await apiFetch("/api/auth/me/", { raw: true });
  if (fresh.ok) return fresh.json();

  // Login reported success but the cookie did not stick — in an iframe that is
  // almost always the browser blocking third-party cookies.
  throw new SsoError(
    "cookie_blocked",
    "The session cookie was not stored inside the iframe.",
    "Bitrix signed you in, but /api/auth/me/ still answers 401. " +
      "The browser is blocking third-party cookies (the default in Safari and Firefox, or switched off manually in Chrome)."
  );
}
