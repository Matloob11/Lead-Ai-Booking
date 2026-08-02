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

/** Loads //api.bitrix24.com/api/v1/ and resolves once BX24.init() has fired. */
export function loadBX24() {
  if (sdkPromise) return sdkPromise;

  sdkPromise = new Promise((resolve, reject) => {
    if (window.top === window.self) {
      reject(
        new SsoError(
          "not_in_frame",
          "Panel Bitrix ke bahar khula hai.",
          "Ye page sirf Bitrix24 ke left menu se khulta hai — seedha URL open karne par auth nahi milegi."
        )
      );
      return;
    }

    const timer = setTimeout(() => {
      reject(
        new SsoError(
          "sdk_timeout",
          "Bitrix JS SDK load nahi hua.",
          `${BX24_SDK} ${SDK_TIMEOUT_MS / 1000}s mein jawab nahi de saka. Portal ka internet access ya CSP block ho sakta hai.`
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
        reject(new SsoError("sdk_missing", "BX24 object SDK load ke baad bhi nahi mila."));
        return;
      }
      window.BX24.init(done);
    };
    script.onerror = () => {
      clearTimeout(timer);
      reject(new SsoError("sdk_unreachable", "Bitrix JS SDK download nahi ho saka.", BX24_SDK));
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
        "Bitrix ne authorization token nahi diya.",
        "BX24.getAuth() false laut raha hai — app placement se nahi khula ya token expire ho chuka hai."
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

/** Forces the portal to mint a fresh access token (they expire in ~1 hour). */
export function refreshBitrixAuth() {
  return new Promise((resolve, reject) => {
    if (!window.BX24 || typeof window.BX24.refreshAuth !== "function") {
      reject(new SsoError("no_refresh", "BX24.refreshAuth available nahi hai."));
      return;
    }
    window.BX24.refreshAuth((auth) => {
      if (auth && auth.access_token) resolve(auth);
      else reject(new SsoError("refresh_failed", "Bitrix token refresh nahi ho saka."));
    });
  });
}

/** Promisified BX24.callMethod. */
export function callBitrix(method, params = {}) {
  return new Promise((resolve, reject) => {
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
 */
export async function ensurePlacement({ placement = "LEFT_MENU", title = "WhatsApp" } = {}) {
  const handler = new URL(".", window.location.href).href;
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
 * Returns the signed-in agent, logging in through Bitrix first if the session
 * cookie is missing or stale. This is the single entry point for the panel.
 */
export async function ensureSession() {
  const existing = await apiFetch("/api/auth/me/", { raw: true });
  if (existing.ok) return existing.json();

  if (existing.status !== 401 && existing.status !== 403) {
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
    "Session cookie iframe mein save nahi hui.",
    "Bitrix login to ho gaya lekin /api/auth/me/ phir bhi 401 de raha hai. " +
      "Browser third-party cookies block kar raha hai (Safari/Firefox default, ya Chrome mein manually band)."
  );
}
