import { Session } from './entities/session.entity';

export const MANUAL_START_REQUIRED_CONFIG_KEY = 'manualStartRequired';

export function requiresManualStart(session: Pick<Session, 'config'>): boolean {
  return session.config?.[MANUAL_START_REQUIRED_CONFIG_KEY] === true;
}

export function requireManualStart(config: Record<string, unknown> | null | undefined): Record<string, unknown> {
  return { ...(config ?? {}), [MANUAL_START_REQUIRED_CONFIG_KEY]: true };
}

export function clearManualStartRequirement(
  config: Record<string, unknown> | null | undefined,
): Record<string, unknown> {
  const next = { ...(config ?? {}) };
  delete next[MANUAL_START_REQUIRED_CONFIG_KEY];
  return next;
}
