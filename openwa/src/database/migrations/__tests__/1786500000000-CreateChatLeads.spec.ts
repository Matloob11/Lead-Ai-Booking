import { DataSource } from 'typeorm';
import { CreateChatLeads1786500000000 } from '../1786500000000-CreateChatLeads';

describe('CreateChatLeads1786500000000', () => {
  let ds: DataSource;

  beforeEach(async () => {
    ds = new DataSource({ type: 'better-sqlite3', database: ':memory:', entities: [], migrations: [] });
    await ds.initialize();
  });

  afterEach(async () => {
    await ds.destroy();
  });

  it('creates chat_leads and is idempotent', async () => {
    const m = new CreateChatLeads1786500000000();
    await m.up(ds.createQueryRunner());
    expect(await ds.createQueryRunner().hasTable('chat_leads')).toBe(true);
    await m.up(ds.createQueryRunner());
    expect(await ds.createQueryRunner().hasTable('chat_leads')).toBe(true);
  });
});
