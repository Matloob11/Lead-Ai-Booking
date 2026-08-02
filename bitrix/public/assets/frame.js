/**
 * Sizing the Bitrix placement iframe.
 *
 * Bitrix gives a placement whatever height it decides, and BX24.fitWindow()
 * only grows the frame to fit our *content* — which is backwards for a chat
 * panel: the panel should fill the space it has and scroll internally, never
 * push the portal page into a scrollbar.
 *
 * The SDK exposes no "available height" (getScrollSize reports our own content,
 * not the parent's viewport), and the parent is cross-origin. What the frame
 * *can* read is its own position on the physical screen: window.screenY is the
 * frame viewport's screen coordinate even inside a cross-origin iframe. The
 * space left below it is a good estimate of what the portal can give us.
 */

/**
 * Bitrix puts `min-height: 600px` on the placement iframe itself, so asking for
 * anything smaller is ignored — the portal page simply scrolls on very short
 * viewports. Growing is the only direction we can actually influence.
 */
const MIN_HEIGHT = 600;
const MAX_HEIGHT = 1400;
const BOTTOM_GAP = 16; // breathing room so the panel doesn't touch the edge

/**
 * What sits above the panel when screenY is unreadable: browser chrome plus the
 * portal's own header and page padding. Measured at ~295px on a 720px-tall
 * screen; it barely varies because both parts are fixed-height.
 */
const CHROME_ALLOWANCE = 300;

/** Best estimate of the height the portal can give this frame. */
export function availableHeight() {
  const screenHeight = window.screen?.availHeight || 0;
  if (!screenHeight) return clamp(window.innerHeight || MIN_HEIGHT);

  const offsetTop = (window.screenY || 0) - (window.screen?.availTop || 0);

  // screenY is the frame's position on the physical screen and is the accurate
  // signal — but some environments (automation windows parked off-screen)
  // report nonsense, so it is only trusted when it lands on the screen.
  if (offsetTop >= 0 && offsetTop < screenHeight) {
    return clamp(screenHeight - offsetTop - BOTTOM_GAP);
  }
  return clamp(screenHeight - CHROME_ALLOWANCE);
}

const clamp = (value) => Math.round(Math.max(MIN_HEIGHT, Math.min(MAX_HEIGHT, value)));

/**
 * Asks Bitrix for that height, and keeps asking whenever the window changes.
 * Returns a stop() for teardown.
 */
export function keepFrameSized() {
  let last = 0;

  const apply = () => {
    const height = availableHeight();
    // Sub-pixel churn would ping the parent on every scroll of the outer page.
    if (Math.abs(height - last) < 8) return;
    last = height;

    const width = document.documentElement.clientWidth || window.innerWidth;
    window.BX24?.resizeWindow?.(width, height);
    console.debug("[a7-wa] frame height →", height, {
      screenAvail: window.screen?.availHeight,
      screenY: window.screenY,
      innerHeight: window.innerHeight,
      scrollSize: window.BX24?.getScrollSize?.(),
    });
  };

  apply();
  // The first call lands before Bitrix has finished positioning the frame, so
  // screenY is often still stale; a couple of follow-ups settle it.
  const timers = [setTimeout(apply, 300), setTimeout(apply, 1200)];

  const onResize = debounceFrame(apply);
  window.addEventListener("resize", onResize);

  return () => {
    timers.forEach(clearTimeout);
    window.removeEventListener("resize", onResize);
  };
}

function debounceFrame(fn) {
  let raf = null;
  let timer = null;
  return () => {
    cancelAnimationFrame(raf);
    clearTimeout(timer);
    raf = requestAnimationFrame(() => {
      timer = setTimeout(fn, 150);
    });
  };
}
