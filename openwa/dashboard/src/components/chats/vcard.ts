/**
 * Read the contact card WhatsApp sends as a message body.
 *
 * A `vcard`/`multi_vcard` message carries raw vCard text — `BEGIN:VCARD … END:VCARD` — in `body`,
 * and nothing else. Rendered as a text bubble, which is what happened until now, an agent sees
 * fifteen lines of `TEL;type=CELL;waid=971…` instead of a name and a number.
 *
 * Parsed in the browser rather than at the engine boundary on purpose: the text is already stored
 * verbatim on every such row, including every one already in the database, so there is nothing to
 * backfill and no second copy of the same information to keep in step.
 */

export interface ParsedContact {
  name: string;
  phones: string[];
}

/**
 * vCard folds long lines by breaking them and starting the continuation with a space or tab. The
 * break and that whitespace are both part of the fold rather than the value (RFC 6350 §3.2), so
 * removing all three characters is what rejoins the original. Unfolded first, or a long `TEL`
 * splits across two lines and the number arrives truncated at the break.
 *
 * `\r?` because a producer that folds with a bare LF is not unusual, and a continuation left on its
 * own line reads as a property with no colon and is dropped — losing the tail of the number
 * silently, which is the failure mode worth spending a character on.
 */
function unfold(text: string): string[] {
  return text.replace(/\r?\n[ \t]/g, '').replace(/\r/g, '').split('\n');
}

/** Strip the escaping vCard applies to values: `\,` `\;` `\n` `\\`. */
function unescapeValue(value: string): string {
  return value.replace(/\\n/gi, ' ').replace(/\\([,;\\])/g, '$1').trim();
}

/**
 * Every contact in the body. `multi_vcard` holds several, one BEGIN/END block each; a plain
 * `vcard` holds one and comes back as a single-element list.
 *
 * Returns an empty list for anything that is not a vCard, so a caller can fall back to rendering
 * the body as text rather than showing an empty card.
 */
export function parseVCards(body: string | undefined | null): ParsedContact[] {
  if (!body || !body.includes('BEGIN:VCARD')) return [];

  const contacts: ParsedContact[] = [];
  let current: ParsedContact | null = null;

  for (const line of unfold(body)) {
    const trimmed = line.trim();
    if (trimmed === 'BEGIN:VCARD') {
      current = { name: '', phones: [] };
      continue;
    }
    if (trimmed === 'END:VCARD') {
      if (current && (current.name || current.phones.length)) contacts.push(current);
      current = null;
      continue;
    }
    if (!current) continue;

    // `PROPERTY;param=value:the value` — the first colon ends the property, and the parameters
    // before it are where `waid=` and `type=CELL` live.
    const colon = trimmed.indexOf(':');
    if (colon === -1) continue;
    const property = trimmed.slice(0, colon).toUpperCase();
    const value = unescapeValue(trimmed.slice(colon + 1));
    if (!value) continue;

    // FN is the display name. N is the structured fallback (`Surname;First;;;`) for a card that
    // carries no FN — its semicolons are field separators, not part of anybody's name.
    if (property === 'FN' || property.startsWith('FN;')) {
      current.name = value;
    } else if (!current.name && (property === 'N' || property.startsWith('N;'))) {
      current.name = value.split(';').filter(Boolean).reverse().join(' ').trim();
    } else if (property === 'TEL' || property.startsWith('TEL;')) {
      if (!current.phones.includes(value)) current.phones.push(value);
    }
  }

  return contacts;
}
