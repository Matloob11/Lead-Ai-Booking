/**
 * Call BX24.init before any ES module (especially inbox.js) has downloaded.
 *
 * Bitrix's placement slider shows "Loading WhatsApp" until the iframe posts
 * that handshake. Two things have to be true first:
 *
 * 1. window.name = "DOMAIN|PROTOCOL|APP_SID". The official SDK refuses to
 *    start without it. Bitrix puts those values on the handler URL query
 *    string (and in the POST body, which a static file never sees). If the
 *    iframe's name attribute is missing — SidePanel often leaves it as a
 *    generic frame name — we copy them from the query before loading the SDK.
 *
 * 2. The SDK itself. api.bitrix24.com is blocked in some of this office's
 *    browsers, so we load a local copy first and fall back to the CDN.
 *
 * Resolves window.__a7Bx24Ready; bitrix-sso.js waits on that same promise
 * instead of calling BX24.init a second time (some portal builds never fire
 * the later callback).
 */
(function () {
  var LOCAL_SDK = document.currentScript
    ? new URL("bx24-sdk.js", document.currentScript.src).href
    : "./assets/core/bx24-sdk.js";
  var CDN_SDK = "https://api.bitrix24.com/api/v1/";
  var TIMEOUT_MS = 15000;

  function queryParams() {
    try {
      return new URLSearchParams(window.location.search);
    } catch (e) {
      return new URLSearchParams();
    }
  }

  function hasAppSid(name) {
    return String(name || "").split("|").filter(Boolean).length >= 3;
  }

  function hydrateWindowName() {
    if (hasAppSid(window.name)) return;
    var q = queryParams();
    var domain = q.get("DOMAIN");
    var sid = q.get("APP_SID");
    if (!domain || !sid) return;
    var protocol = q.get("PROTOCOL") === "0" ? "0" : "1";
    window.name = domain + "|" + protocol + "|" + sid;
  }

  hydrateWindowName();

  window.__a7Bx24Ready = new Promise(function (resolve, reject) {
    var inFrame = window.top !== window.self;
    if (!inFrame && !hasAppSid(window.name)) {
      reject({
        code: "not_in_frame",
        message: "The panel was opened outside Bitrix.",
        detail:
          "This page only opens from the Bitrix24 left menu. Opening the URL directly leaves it with no way to authenticate.",
      });
      return;
    }

    var timer = setTimeout(function () {
      reject({
        code: "sdk_timeout",
        message: "The Bitrix JS SDK did not load.",
        detail:
          "Neither the local copy nor " +
          CDN_SDK +
          " finished BX24.init within " +
          TIMEOUT_MS / 1000 +
          "s.",
      });
    }, TIMEOUT_MS);

    var done = function () {
      clearTimeout(timer);
      resolve(window.BX24);
    };

    var start = function () {
      if (!window.BX24 || typeof window.BX24.init !== "function") {
        clearTimeout(timer);
        reject({
          code: "sdk_missing",
          message: "The BX24 object is still missing after the SDK loaded.",
          detail: hasAppSid(window.name)
            ? "window.name is set; the SDK still did not export BX24.init."
            : "window.name has no APP_SID (Bitrix query DOMAIN/APP_SID was empty).",
        });
        return;
      }
      window.BX24.init(done);
    };

    function loadScript(src, onError) {
      var script = document.createElement("script");
      script.src = src;
      script.onload = start;
      script.onerror = onError;
      document.head.appendChild(script);
    }

    if (window.BX24 && typeof window.BX24.init === "function") {
      start();
      return;
    }

    loadScript(LOCAL_SDK, function () {
      loadScript(CDN_SDK, function () {
        clearTimeout(timer);
        reject({
          code: "sdk_unreachable",
          message: "The Bitrix JS SDK could not be downloaded.",
          detail: LOCAL_SDK + " and " + CDN_SDK,
        });
      });
    });
  });
})();
