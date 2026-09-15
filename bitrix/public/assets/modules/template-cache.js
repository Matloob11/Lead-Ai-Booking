/**
 * Session cache for Template Center lists.
 * Show last-known templates immediately; refresh from the API in the background
 * so opening the screen does not block on /api/catalog/templates/all/ every time.
 */

const TEMPLATES_KEY = "a7.catalog.templates.all.v1";
const NUMBERS_KEY = "a7.catalog.numbers.v1";
const TTL_MS = 15 * 60 * 1000;

function read(key) {
  try {
    const raw = sessionStorage.getItem(key);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed || !Array.isArray(parsed.rows)) return null;
    const at = Number(parsed.at) || 0;
    return {
      rows: parsed.rows,
      at,
      fresh: at > 0 && Date.now() - at < TTL_MS,
    };
  } catch {
    return null;
  }
}

function write(key, rows) {
  try {
    sessionStorage.setItem(key, JSON.stringify({ at: Date.now(), rows: rows || [] }));
  } catch {
    // Quota / private mode — ignore; live fetch still works.
  }
}

export function readTemplatesCache() {
  return read(TEMPLATES_KEY);
}

export function readNumbersCache() {
  return read(NUMBERS_KEY);
}

export function writeTemplatesCache(rows) {
  write(TEMPLATES_KEY, rows);
}

export function writeNumbersCache(rows) {
  write(NUMBERS_KEY, rows);
}

export function clearTemplateCaches() {
  try {
    sessionStorage.removeItem(TEMPLATES_KEY);
    sessionStorage.removeItem(NUMBERS_KEY);
  } catch {
    /* ignore */
  }
}
