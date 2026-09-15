/** Format helpers for Bitrix UF_CRM_WA_CHAT / timeline snippets (unit-tested). */

const VCARD_RE = /BEGIN:VCARD[\s\S]*?END:VCARD/gi;

/**
 * Bitrix CRM string fields on this portal render with SIZE≈20 (cols=20) and the
 * legacy crm.*.userfield.* REST methods cannot raise SIZE. Soft-wrapping here
 * keeps the lead-card textarea readable as a single vertical column.
 */
export const BITRIX_UF_WRAP_WIDTH = 20;

/** Collapse a single message body for the lead card field. */
export function sanitizeChatBody(body: string): string {
  let text = (body || '').replace(/\r\n/g, '\n').replace(/\r/g, '\n').trim();
  if (!text) return '';
  // Reset lastIndex — global regex is stateful across calls.
  VCARD_RE.lastIndex = 0;
  if (VCARD_RE.test(text)) {
    VCARD_RE.lastIndex = 0;
    text = text.replace(VCARD_RE, '[contact card]').trim();
  }
  // One logical message per line — Bitrix narrow cells shred wrapped blocks.
  text = text.replace(/\n+/g, ' ').replace(/\s+/g, ' ').trim();
  if (text.length > 220) text = `${text.slice(0, 217)}…`;
  return text;
}

/** Word-wrap a single line so Bitrix cols≈20 textareas don't look shredded. */
export function softWrapLine(line: string, width = BITRIX_UF_WRAP_WIDTH): string {
  const raw = (line || '').replace(/\s+/g, ' ').trim();
  if (!raw || raw.length <= width) return raw;
  const parts: string[] = [];
  let rest = raw;
  while (rest.length > width) {
    let cut = rest.lastIndexOf(' ', width);
    if (cut < Math.floor(width / 2)) cut = width;
    parts.push(rest.slice(0, cut).trimEnd());
    rest = rest.slice(cut).trimStart();
  }
  if (rest) parts.push(rest);
  return parts.join('\n');
}

export function formatChatLine(who: 'AGENT' | 'CLIENT', body: string): string {
  const clean = sanitizeChatBody(body) || '[message]';
  return softWrapLine(`${who}: ${clean}`);
}

/**
 * Keep the tail of a thread without cutting mid-line (slice(-N) was starting
 * chats mid-word — "uilding …" — on the lead card).
 */
export function takeThreadTail(thread: string, maxChars: number): string {
  const text = (thread || '').replace(/\r\n/g, '\n').replace(/\r/g, '\n');
  if (text.length <= maxChars) return text;
  const cut = text.slice(-maxChars);
  const nl = cut.indexOf('\n');
  if (nl >= 0 && nl < cut.length - 1) return cut.slice(nl + 1);
  return cut;
}

/** Final pass before writing UF_CRM_WA_CHAT — wrap every line for narrow SIZE. */
export function formatThreadForBitrixField(thread: string, maxChars: number): string {
  let text = (thread || '').replace(/\r\n/g, '\n').replace(/\r/g, '\n');
  VCARD_RE.lastIndex = 0;
  text = text.replace(VCARD_RE, '[contact card]');
  const tail = takeThreadTail(text, maxChars);
  return tail
    .split('\n')
    .map(line => softWrapLine(line))
    .filter(Boolean)
    .join('\n');
}
