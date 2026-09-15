import { MigrationInterface, QueryRunner } from 'typeorm';
import { AddChatProfilePinned1786900000000 } from '../1786900000000-AddChatProfilePinned';

describe('AddChatProfilePinned1786900000000', () => {
  it('is named for TypeORM ordering', () => {
    const m = new AddChatProfilePinned1786900000000();
    expect(m.name).toBe('AddChatProfilePinned1786900000000');
  });

  it('no-ops when chat_profiles is missing', async () => {
    const m = new AddChatProfilePinned1786900000000();
    const qr = {
      hasTable: jest.fn().mockResolvedValue(false),
      getTable: jest.fn(),
      addColumn: jest.fn(),
    } as unknown as QueryRunner;
    await m.up(qr);
    expect(qr.addColumn).not.toHaveBeenCalled();
  });
});
