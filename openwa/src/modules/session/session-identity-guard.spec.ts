/* eslint-disable @typescript-eslint/require-await */
import { SessionStatus, type Session } from './entities/session.entity';
import { SessionIdentityGuard } from './session-identity-guard';

const baseSession = (overrides: Partial<Session> = {}): Session =>
  ({
    id: 's1',
    name: 'marketting',
    phone: '923166753715',
    status: SessionStatus.DISCONNECTED,
    historyImportedAt: new Date('2026-08-01T00:00:00.000Z'),
    historyFirstLinkedAt: new Date('2026-01-01T00:00:00.000Z'),
    historySyncToken: 'g1',
    historySyncError: null,
    createdAt: new Date('2025-01-01T00:00:00.000Z'),
    ...overrides,
  }) as Session;

const harness = (session: Session, messageCount = 0, ownerSides: string[] = []) => {
  const update = jest.fn(async () => ({ affected: 1 }));
  const manager = {
    findOne: jest.fn(async () => session),
    count: jest.fn(async () => messageCount),
    find: jest.fn(async () => ownerSides.map(owner => ({ direction: 'incoming', to: owner, from: 'customer@c.us' }))),
    update,
  };
  const dataSource = { transaction: jest.fn(async (work: (manager: typeof manager) => unknown) => work(manager)) };
  return { guard: new SessionIdentityGuard(dataSource as never), manager, update };
};

describe('SessionIdentityGuard', () => {
  it('accepts normalized same phone and preserves bound identity/checkpoint', async () => {
    const session = baseSession();
    const { guard, update } = harness(session, 675, ['923166753715@c.us']);

    await expect(guard.validateAndBind('s1', '+92 316 6753715', 'g1')).resolves.toMatchObject({
      kind: 'SAME_PHONE',
      phone: '923166753715',
    });
    expect(update).toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({ id: 's1', historySyncToken: 'g1' }),
      expect.objectContaining({ historySyncError: null }),
    );
    expect(update.mock.calls[0][2]).not.toHaveProperty('phone');
    expect(update.mock.calls[0][2]).not.toHaveProperty('historyImportedAt');
  });

  it('rejects a different phone without changing old phone, checkpoint, or messages', async () => {
    const session = baseSession();
    const { guard, manager, update } = harness(session, 675, ['923166753715@c.us']);

    await expect(guard.validateAndBind('s1', '971502938395', 'g1')).resolves.toEqual({
      kind: 'QUARANTINE',
      reason: 'DIFFERENT_PHONE',
    });
    expect(update).toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({ id: 's1', historySyncToken: 'g1' }),
      expect.objectContaining({
        status: SessionStatus.ACTION_REQUIRED,
        historySyncError: 'IDENTITY_DIFFERENT_PHONE',
      }),
    );
    expect(update.mock.calls[0][2]).not.toHaveProperty('phone');
    expect(update.mock.calls[0][2]).not.toHaveProperty('historyImportedAt');
    expect(manager.update).toHaveBeenCalledTimes(1);
  });

  it('fails closed for a legacy null-phone session that already has messages', async () => {
    const { guard, update } = harness(baseSession({ phone: null, historyImportedAt: null }), 1);

    await expect(guard.validateAndBind('s1', '923166753715', 'g1')).resolves.toEqual({
      kind: 'QUARANTINE',
      reason: 'LEGACY_AMBIGUOUS',
    });
    expect(update).toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({ id: 's1', historySyncToken: 'g1' }),
      expect.objectContaining({ status: SessionStatus.ACTION_REQUIRED, historySyncError: 'IDENTITY_LEGACY_AMBIGUOUS' }),
    );
  });

  it('fails closed for empty/unparseable authenticated identity', async () => {
    const { guard, update } = harness(baseSession());

    await expect(guard.validateAndBind('s1', '123@lid', 'g1')).resolves.toEqual({
      kind: 'QUARANTINE',
      reason: 'INVALID_IDENTITY',
    });
    expect(update).toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({ id: 's1', historySyncToken: 'g1' }),
      expect.objectContaining({ status: SessionStatus.ACTION_REQUIRED, historySyncError: 'IDENTITY_INVALID' }),
    );
  });

  it('accepts a first link only when phone/checkpoint/messages are all empty', async () => {
    const createdAt = new Date('2025-08-01T00:00:00.000Z');
    const beforeLink = new Date();
    const { guard, update } = harness(
      baseSession({ phone: null, historyImportedAt: null, historyFirstLinkedAt: null, createdAt }),
      0,
    );

    const decision = await guard.validateAndBind('s1', '923166753715@s.whatsapp.net', 'g1');
    const afterLink = new Date();
    expect(decision).toMatchObject({ kind: 'FIRST_LINK', phone: '923166753715' });
    if (decision.kind !== 'FIRST_LINK') throw new Error('expected first-link decision');
    expect(decision.firstLinkedAt.getTime()).toBeGreaterThanOrEqual(beforeLink.getTime());
    expect(decision.firstLinkedAt.getTime()).toBeLessThanOrEqual(afterLink.getTime());
    expect(update).toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({ id: 's1', historySyncToken: 'g1' }),
      expect.objectContaining({
        phone: '923166753715',
        historyFirstLinkedAt: decision.firstLinkedAt,
        historySyncError: null,
      }),
    );
  });

  it('aborts its transaction when the engine generation retires during the first-link write', async () => {
    const { guard, update } = harness(
      baseSession({ phone: null, historyImportedAt: null, historyFirstLinkedAt: null }),
      0,
    );
    const generationIsCurrent = jest
      .fn()
      .mockReturnValueOnce(true)
      .mockReturnValueOnce(true)
      .mockReturnValueOnce(true)
      .mockReturnValueOnce(true)
      .mockReturnValue(false);

    await expect(guard.validateAndBind('s1', '923166753715', 'g1', generationIsCurrent)).rejects.toThrow(
      'engine generation retired',
    );
    expect(update).toHaveBeenCalledTimes(1);
  });

  it('keeps a bound legacy session safe when evidence has no proven conflict', async () => {
    const createdAt = new Date('2025-01-01T00:00:00.000Z');
    const { guard, update } = harness(baseSession({ historyFirstLinkedAt: null, createdAt }), 2, [
      '923166753715@c.us',
      '123456789@lid',
    ]);

    await expect(guard.validateAndBind('s1', '923166753715', 'g1')).resolves.toMatchObject({ kind: 'SAME_PHONE' });
    expect(update).toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({ id: 's1', historySyncToken: 'g1' }),
      expect.objectContaining({ historyFirstLinkedAt: createdAt }),
    );
  });

  it('quarantines a bound legacy session when persisted owner evidence conflicts', async () => {
    const { guard } = harness(baseSession(), 1, ['971502938395@c.us']);

    await expect(guard.validateAndBind('s1', '923166753715', 'g1')).resolves.toEqual({
      kind: 'QUARANTINE',
      reason: 'LEGACY_CONFLICT',
    });
  });
});
