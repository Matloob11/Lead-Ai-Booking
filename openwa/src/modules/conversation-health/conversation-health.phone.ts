/** Pure helpers for chat → phone / group skip (unit-tested). */

export function digitsOnly(value: string): string {
  return [...value].filter(c => c >= '0' && c <= '9').join('');
}

export function isGroupOrNewsletterChat(chatId: string): boolean {
  const id = chatId.toLowerCase();
  return id.endsWith('@g.us') || id.endsWith('@newsletter') || id.includes('status@broadcast');
}

/**
 * Prefer a phone-like digit run from chat name or JID local-part.
 * Returns null for groups, newsletters, or LID-only ids without a usable phone.
 */
export function resolveChatPhone(chatId: string, chatName?: string | null): string | null {
  if (isGroupOrNewsletterChat(chatId)) return null;
  const local = chatId.split('@')[0] || '';
  // LID local parts are long numeric but not E.164 phones; prefer name when JID is @lid.
  const isLid = chatId.toLowerCase().includes('@lid');
  const candidates = isLid ? [chatName || '', local] : [chatName || '', local];
  for (const candidate of candidates) {
    const d = digitsOnly(candidate);
    if (d.length >= 8 && d.length <= 15) {
      // Reject obvious LID-sized numbers when the JID is @lid and we only have the LID itself.
      if (isLid && candidate === local && d.length > 12) continue;
      return d;
    }
  }
  return null;
}

export function maskPhone(phone: string): string {
  const d = digitsOnly(phone);
  if (d.length < 6) return '***';
  return `${d.slice(0, 3)}…${d.slice(-3)}`;
}
