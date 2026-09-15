import { auditSessions, exitCodeForDecision, formatAuditReport, type LegacyAuditInput } from './legacy-identity-audit';

function input(overrides: Partial<LegacyAuditInput> = {}): LegacyAuditInput {
  return {
    sessions: [{ id: 'session-1', name: 'marketting', phone: '923001112233' }],
    messages: [],
    lidMappings: [],
    ...overrides,
  };
}

describe('legacy identity audit', () => {
  it('treats @c.us and @s.whatsapp.net as the same account-side phone', () => {
    const report = auditSessions(
      input({
        sessions: [{ id: 'session-1', name: 'marketting', phone: '+92 300 111 2233' }],
        messages: [
          {
            sessionId: 'session-1',
            direction: 'incoming',
            from: '923009999999@c.us',
            to: '923001112233@c.us',
          },
          {
            sessionId: 'session-1',
            direction: 'outgoing',
            from: '923001112233:4@s.whatsapp.net',
            to: '923008888888@c.us',
          },
        ],
      }),
    );

    expect(report.sessions).toEqual([{ label: 'marketting', rows: 2, resolved: 2, unresolved: 0, decision: 'PASS' }]);
    expect(report.overall).toBe('PASS');
  });

  it('resolves only persisted LID mappings and leaves an unmapped LID unresolved', () => {
    const report = auditSessions(
      input({
        messages: [
          {
            sessionId: 'session-1',
            direction: 'incoming',
            from: '900@c.us',
            to: '111:7@lid',
          },
          {
            sessionId: 'session-1',
            direction: 'outgoing',
            from: '222@lid',
            to: '901@c.us',
          },
        ],
        lidMappings: [{ lid: '111', phone: '923001112233' }],
      }),
    );

    expect(report.sessions[0]).toEqual({
      label: 'marketting',
      rows: 2,
      resolved: 1,
      unresolved: 1,
      decision: 'INCONCLUSIVE',
    });
    expect(report.overall).toBe('INCONCLUSIVE');
  });

  it('resolves provider-artifact owner fields only when an ordinary row proves the same LID is customer-side', () => {
    const systemArtifact = {
      sessionId: 'asma',
      direction: 'outgoing',
      from: '777@lid',
      to: '8000000@c.us',
      chatId: '8000000@c.us',
      type: 'system',
    };
    const callArtifact = {
      sessionId: 'marketting',
      direction: 'incoming',
      from: '888@lid',
      to: '888@lid',
      chatId: '888@lid',
      type: 'call',
    };
    const report = auditSessions({
      sessions: [
        { id: 'asma', name: 'asma', phone: '1000000' },
        { id: 'marketting', name: 'marketting', phone: '2000000' },
        { id: 'minahil', name: 'minahil', phone: '3000000' },
      ],
      messages: [
        systemArtifact,
        callArtifact,
        {
          sessionId: 'minahil',
          direction: 'incoming',
          from: '777@lid',
          to: '3000000@c.us',
          type: 'text',
        },
        {
          sessionId: 'marketting',
          direction: 'incoming',
          from: '888@lid',
          to: '2000000@c.us',
          type: 'text',
        },
      ],
      lidMappings: [],
    });

    expect(report.sessions).toEqual([
      { label: 'asma', rows: 1, resolved: 1, unresolved: 0, decision: 'PASS' },
      { label: 'marketting', rows: 2, resolved: 2, unresolved: 0, decision: 'PASS' },
      { label: 'minahil', rows: 1, resolved: 1, unresolved: 0, decision: 'PASS' },
    ]);
    expect(report.overall).toBe('PASS');
  });

  it('keeps a provider artifact unresolved without a separate bound-owner customer witness', () => {
    const systemArtifact = {
      sessionId: 'session-1',
      direction: 'outgoing',
      from: '777@lid',
      to: '9000000@c.us',
      type: 'system',
    };
    const report = auditSessions(input({ messages: [systemArtifact] }));

    expect(report.sessions[0]).toEqual({
      label: 'marketting',
      rows: 1,
      resolved: 0,
      unresolved: 1,
      decision: 'INCONCLUSIVE',
    });
  });

  it('fails when one session proves two different account-side identities', () => {
    const report = auditSessions(
      input({
        sessions: [{ id: 'session-1', name: 'legacy', phone: null }],
        messages: [
          {
            sessionId: 'session-1',
            direction: 'incoming',
            from: '900@c.us',
            to: '923001112233@c.us',
          },
          {
            sessionId: 'session-1',
            direction: 'outgoing',
            from: '971501234567@c.us',
            to: '901@c.us',
          },
        ],
      }),
    );

    expect(report.sessions[0]?.decision).toBe('FAIL');
    expect(report.overall).toBe('FAIL');
  });

  it('fails closed when a session has stored messages but no bound phone', () => {
    const report = auditSessions(
      input({
        sessions: [{ id: 'session-1', name: 'legacy', phone: null }],
        messages: [
          {
            sessionId: 'session-1',
            direction: 'incoming',
            from: '900@c.us',
            to: '923001112233@c.us',
          },
        ],
      }),
    );

    expect(report.sessions[0]).toEqual({
      label: 'legacy',
      rows: 1,
      resolved: 1,
      unresolved: 0,
      decision: 'INCONCLUSIVE',
    });
  });

  it('passes a fully clean session', () => {
    const report = auditSessions(
      input({
        messages: [
          {
            sessionId: 'session-1',
            direction: 'incoming',
            from: '900@c.us',
            to: '923001112233@s.whatsapp.net',
          },
        ],
      }),
    );

    expect(report.sessions[0]).toEqual({
      label: 'marketting',
      rows: 1,
      resolved: 1,
      unresolved: 0,
      decision: 'PASS',
    });
  });

  it('marks missing, malformed, and unsupported owner-side values unresolved', () => {
    const report = auditSessions(
      input({
        messages: [
          { sessionId: 'session-1', direction: 'incoming', from: '900@c.us', to: '' },
          { sessionId: 'session-1', direction: 'outgoing', from: 'abc123@c.us', to: '901@c.us' },
          { sessionId: 'session-1', direction: 'legacy', from: '923001112233@c.us', to: '901@c.us' },
        ],
      }),
    );

    expect(report.sessions[0]).toEqual({
      label: 'marketting',
      rows: 3,
      resolved: 0,
      unresolved: 3,
      decision: 'INCONCLUSIVE',
    });
  });

  it('does not treat an implausibly short digit string as a proven phone identity', () => {
    const report = auditSessions(
      input({
        sessions: [{ id: 'session-1', name: 'legacy', phone: '123' }],
        messages: [{ sessionId: 'session-1', direction: 'incoming', from: '9000000@c.us', to: '123@c.us' }],
      }),
    );

    expect(report.sessions[0]).toEqual({
      label: 'legacy',
      rows: 1,
      resolved: 0,
      unresolved: 1,
      decision: 'INCONCLUSIVE',
    });
  });

  it('prints only safe labels, counts, and decisions', () => {
    const secretPhone = '923001112233';
    const secretLid = '778899@lid';
    const secretBody = 'customer-private-message';
    const secretToken = 'api-token-private';
    const report = auditSessions({
      sessions: [{ id: 'session-private', name: secretPhone, phone: secretPhone, token: secretToken } as never],
      messages: [
        {
          sessionId: 'session-private',
          direction: 'incoming',
          from: '900@c.us',
          to: secretLid,
          body: secretBody,
        } as LegacyAuditInput['messages'][number],
      ],
      lidMappings: [],
    });

    const output = formatAuditReport(report);

    expect(output).toBe('session session-1 rows 1 resolved 0 unresolved 1 INCONCLUSIVE\noverall: INCONCLUSIVE');
    for (const forbidden of [secretPhone, secretLid, secretBody, secretToken, '@', '/', '\\']) {
      expect(output).not.toContain(forbidden);
    }
  });

  it('uses FAIL then INCONCLUSIVE then PASS precedence and exact gate exit codes', () => {
    const report = auditSessions({
      sessions: [
        { id: 'pass', name: 'pass', phone: '1000000' },
        { id: 'unknown', name: 'unknown', phone: null },
        { id: 'conflict', name: 'conflict', phone: '3000000' },
      ],
      messages: [
        { sessionId: 'pass', direction: 'incoming', from: '9000000@c.us', to: '1000000@c.us' },
        { sessionId: 'unknown', direction: 'incoming', from: '9010000@c.us', to: '2000000@c.us' },
        { sessionId: 'conflict', direction: 'incoming', from: '9020000@c.us', to: '3010000@c.us' },
      ],
      lidMappings: [],
    });

    expect(report.overall).toBe('FAIL');
    expect(exitCodeForDecision('PASS')).toBe(0);
    expect(exitCodeForDecision('INCONCLUSIVE')).toBe(1);
    expect(exitCodeForDecision('FAIL')).toBe(2);
  });

  it('fails closed when the database has no sessions or contains orphan message rows', () => {
    expect(auditSessions({ sessions: [], messages: [], lidMappings: [] }).overall).toBe('INCONCLUSIVE');

    const report = auditSessions({
      sessions: [{ id: 'known', name: 'known', phone: '1000000' }],
      messages: [{ sessionId: 'missing', direction: 'incoming', from: '9000000@c.us', to: '1000000@c.us' }],
      lidMappings: [],
    });

    expect(report.sessions[0]).toEqual({
      label: 'known',
      rows: 0,
      resolved: 0,
      unresolved: 0,
      decision: 'PASS',
    });
    expect(report.overall).toBe('INCONCLUSIVE');
  });
});
