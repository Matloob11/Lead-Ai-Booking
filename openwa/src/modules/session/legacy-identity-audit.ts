import { DatabaseSync } from 'node:sqlite';

export type LegacyAuditDecision = 'PASS' | 'FAIL' | 'INCONCLUSIVE';

export interface LegacySessionRow {
  id: string;
  name: string;
  phone: string | null;
}

export interface LegacyMessageIdentityRow {
  sessionId: string;
  direction: string;
  from: string | null;
  to: string | null;
  chatId?: string | null;
  type?: string;
}

export interface LegacyLidMappingRow {
  lid: string;
  phone: string | null;
}

export interface LegacyAuditInput {
  sessions: LegacySessionRow[];
  messages: LegacyMessageIdentityRow[];
  lidMappings: LegacyLidMappingRow[];
}

export interface LegacySessionAudit {
  label: string;
  rows: number;
  resolved: number;
  unresolved: number;
  decision: LegacyAuditDecision;
}

export interface LegacyAuditReport {
  sessions: LegacySessionAudit[];
  overall: LegacyAuditDecision;
}

const SAFE_SESSION_NAME = /^[A-Za-z][A-Za-z._-]{0,99}$/;
const FORMATTED_PHONE = /^\+?[0-9](?:[0-9 ()-]*[0-9])?$/;
const DIRECT_USER_JID = /^([1-9][0-9]{6,14})(?::[0-9]+)?@(c\.us|s\.whatsapp\.net)$/i;
const LID_JID = /^([0-9]+)(?::[0-9]+)?@lid$/i;
const BARE_LID = /^[0-9]+$/;

function normalizePhone(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const trimmed = value.trim();
  const jid = DIRECT_USER_JID.exec(trimmed);
  if (jid) return jid[1];
  if (!FORMATTED_PHONE.test(trimmed)) return null;
  const digits = trimmed.replace(/[^0-9]/g, '');
  return /^[1-9][0-9]{6,14}$/.test(digits) ? digits : null;
}

function normalizeLidKey(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const trimmed = value.trim();
  if (BARE_LID.test(trimmed)) return trimmed;
  return LID_JID.exec(trimmed)?.[1] ?? null;
}

function buildLidMap(rows: LegacyLidMappingRow[]): Map<string, string> {
  const mappings = new Map<string, string>();
  for (const row of rows) {
    const lid = normalizeLidKey(row.lid);
    const phone = normalizePhone(row.phone);
    if (lid && phone) mappings.set(lid, phone);
  }
  return mappings;
}

export function normalizeAccountIdentity(value: unknown, lidMappings: ReadonlyMap<string, string>): string | null {
  const phone = normalizePhone(value);
  if (phone) return phone;
  if (typeof value !== 'string') return null;
  const lid = LID_JID.exec(value.trim())?.[1];
  if (!lid) return null;
  return lidMappings.get(lid) ?? null;
}

function ownerSide(row: LegacyMessageIdentityRow): string | null {
  if (row.direction === 'incoming') return row.to;
  if (row.direction === 'outgoing') return row.from;
  return null;
}

function customerSide(row: LegacyMessageIdentityRow): string | null {
  if (row.direction === 'incoming') return row.from;
  if (row.direction === 'outgoing') return row.to;
  return null;
}

function lidFromJid(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  return LID_JID.exec(value.trim())?.[1] ?? null;
}

/**
 * Old whatsapp-web.js provider artifacts do not obey ordinary message from/to semantics:
 * call_log can repeat the caller in from, to, and chatId, while a fromMe system notice can put an
 * affected contact in from. Treat that field as non-owner evidence only when another ordinary row
 * independently proves the exact LID is customer-side and that row's owner matches its bound session.
 * This is deliberately shape- and evidence-based: a count threshold, type-only exception, or an
 * unwitnessed LID remains unresolved.
 */
function provenCustomerLids(
  sessions: LegacySessionRow[],
  messages: LegacyMessageIdentityRow[],
  lidMappings: ReadonlyMap<string, string>,
): Set<string> {
  const sessionById = new Map(sessions.map(session => [session.id, session]));
  const proven = new Set<string>();
  for (const row of messages) {
    if (row.type === 'call' || row.type === 'system') continue;
    const boundPhone = normalizePhone(sessionById.get(row.sessionId)?.phone);
    const owner = normalizeAccountIdentity(ownerSide(row), lidMappings);
    const customerLid = lidFromJid(customerSide(row));
    if (boundPhone && owner === boundPhone && customerLid) proven.add(customerLid);
  }
  return proven;
}

function isProvenProviderArtifact(row: LegacyMessageIdentityRow, customerLids: ReadonlySet<string>): boolean {
  const allegedOwnerLid = lidFromJid(ownerSide(row));
  if (!allegedOwnerLid || !customerLids.has(allegedOwnerLid)) return false;
  if (row.type === 'call') {
    return row.direction === 'incoming' && row.from === row.to && row.from === row.chatId;
  }
  if (row.type === 'system') {
    return row.direction === 'outgoing' && row.from !== row.to && row.to === row.chatId;
  }
  return false;
}

function safeSessionLabel(name: unknown, ordinal: number): string {
  return typeof name === 'string' && SAFE_SESSION_NAME.test(name) ? name : `session-${ordinal}`;
}

function overallDecision(decisions: LegacyAuditDecision[], failClosed: boolean): LegacyAuditDecision {
  if (decisions.includes('FAIL')) return 'FAIL';
  if (failClosed || decisions.includes('INCONCLUSIVE')) return 'INCONCLUSIVE';
  return 'PASS';
}

export function auditSessions(input: LegacyAuditInput): LegacyAuditReport {
  const lidMappings = buildLidMap(input.lidMappings);
  const customerLids = provenCustomerLids(input.sessions, input.messages, lidMappings);
  const knownSessionIds = new Set(input.sessions.map(session => session.id));
  const orphanRows = input.messages.some(message => !knownSessionIds.has(message.sessionId));
  const orderedSessions = [...input.sessions].sort(
    (left, right) => left.name.localeCompare(right.name) || left.id.localeCompare(right.id),
  );

  const sessions = orderedSessions.map((session, index): LegacySessionAudit => {
    const boundPhone = normalizePhone(session.phone);
    const rows = input.messages.filter(message => message.sessionId === session.id);
    const identities = new Set<string>();
    let resolved = 0;
    let unresolved = 0;

    for (const row of rows) {
      const identity = isProvenProviderArtifact(row, customerLids)
        ? boundPhone
        : normalizeAccountIdentity(ownerSide(row), lidMappings);
      if (identity) {
        resolved += 1;
        identities.add(identity);
      } else {
        unresolved += 1;
      }
    }

    const conflicts = identities.size > 1 || (boundPhone != null && [...identities].some(id => id !== boundPhone));
    const decision: LegacyAuditDecision = conflicts
      ? 'FAIL'
      : boundPhone == null || unresolved > 0
        ? 'INCONCLUSIVE'
        : 'PASS';

    return {
      label: safeSessionLabel(session.name, index + 1),
      rows: rows.length,
      resolved,
      unresolved,
      decision,
    };
  });

  return {
    sessions,
    overall: overallDecision(
      sessions.map(session => session.decision),
      sessions.length === 0 || orphanRows,
    ),
  };
}

export function formatAuditReport(report: LegacyAuditReport): string {
  const lines = report.sessions.map(
    session =>
      `session ${session.label} rows ${session.rows} resolved ${session.resolved} unresolved ${session.unresolved} ${session.decision}`,
  );
  lines.push(`overall: ${report.overall}`);
  return lines.join('\n');
}

export function exitCodeForDecision(decision: LegacyAuditDecision): 0 | 1 | 2 {
  if (decision === 'PASS') return 0;
  if (decision === 'FAIL') return 2;
  return 1;
}

function objectRows(value: unknown[]): Record<string, unknown>[] {
  return value.filter((row): row is Record<string, unknown> => typeof row === 'object' && row !== null);
}

function readString(row: Record<string, unknown>, key: string): string {
  return typeof row[key] === 'string' ? row[key] : '';
}

function readNullableString(row: Record<string, unknown>, key: string): string | null {
  return typeof row[key] === 'string' ? row[key] : null;
}

export function auditDatabase(databasePath: string): LegacyAuditReport {
  const database = new DatabaseSync(databasePath, { readOnly: true });
  try {
    const sessions = objectRows(database.prepare('SELECT id, name, phone FROM sessions ORDER BY name, id').all()).map(
      (row): LegacySessionRow => ({
        id: readString(row, 'id'),
        name: readString(row, 'name'),
        phone: readNullableString(row, 'phone'),
      }),
    );
    const messages = objectRows(
      database
        .prepare(
          'SELECT "sessionId", direction, "from", "to", "chatId", type FROM messages ORDER BY "sessionId", "createdAt", id',
        )
        .all(),
    ).map((row): LegacyMessageIdentityRow => ({
      sessionId: readString(row, 'sessionId'),
      direction: readString(row, 'direction'),
      from: readNullableString(row, 'from'),
      to: readNullableString(row, 'to'),
      chatId: readNullableString(row, 'chatId'),
      type: readString(row, 'type'),
    }));
    const mappingTable = database
      .prepare("SELECT COUNT(*) AS count FROM sqlite_master WHERE type = 'table' AND name = 'lid_mappings'")
      .get() as Record<string, unknown> | undefined;
    const lidMappings =
      Number(mappingTable?.count) > 0
        ? objectRows(database.prepare('SELECT lid, phone FROM lid_mappings').all()).map((row): LegacyLidMappingRow => ({
            lid: readString(row, 'lid'),
            phone: readNullableString(row, 'phone'),
          }))
        : [];

    return auditSessions({ sessions, messages, lidMappings });
  } finally {
    database.close();
  }
}

export function runCli(databasePath: string): 0 | 1 | 2 {
  try {
    const report = auditDatabase(databasePath);
    process.stdout.write(`${formatAuditReport(report)}\n`);
    return exitCodeForDecision(report.overall);
  } catch {
    process.stdout.write('overall: INCONCLUSIVE\n');
    return 1;
  }
}
