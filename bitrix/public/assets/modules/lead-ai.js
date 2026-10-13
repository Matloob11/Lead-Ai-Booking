/**
 * Moved. Lead AI lives in modules/lead-ai/ and index.html loads it as its own
 * entry, so nothing imports this file any more.
 *
 * It is kept, and kept tiny, because an inbox.js from before the move imports
 * openLeadAi from here; if one were ever deployed again, a missing file would
 * stop the whole inbox loading. This opens the new screen instead.
 */
export function openLeadAi() {
  window.a7wa?.openLeadAi?.();
}
