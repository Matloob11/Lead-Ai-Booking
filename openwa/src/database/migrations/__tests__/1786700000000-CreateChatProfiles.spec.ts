import { DataSource } from 'typeorm';
import { CreateChatProfiles1786700000000 } from '../1786700000000-CreateChatProfiles';

describe('CreateChatProfiles1786700000000', () => {
  let ds: DataSource;

  beforeEach(async () => {
    ds = new DataSource({ type: 'better-sqlite3', database: ':memory:', entities: [], migrations: [] });
    await ds.initialize();
  });

  afterEach(async () => {
    await ds.destroy();
  });

  it('creates chat_profiles and is idempotent', async () => {
    const m = new CreateChatProfiles1786700000000();
    await m.up(ds.createQueryRunner());
    expect(await ds.createQueryRunner().hasTable('chat_profiles')).toBe(true);
    await m.up(ds.createQueryRunner());
    expect(await ds.createQueryRunner().hasTable('chat_profiles')).toBe(true);
  });
});
