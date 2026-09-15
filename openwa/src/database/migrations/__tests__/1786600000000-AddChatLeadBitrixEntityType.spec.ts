import { DataSource } from 'typeorm';
import { CreateChatLeads1786500000000 } from '../1786500000000-CreateChatLeads';
import { AddChatLeadBitrixEntityType1786600000000 } from '../1786600000000-AddChatLeadBitrixEntityType';

describe('AddChatLeadBitrixEntityType1786600000000', () => {
  let ds: DataSource;

  beforeEach(async () => {
    ds = new DataSource({ type: 'better-sqlite3', database: ':memory:', entities: [], migrations: [] });
    await ds.initialize();
  });

  afterEach(async () => {
    await ds.destroy();
  });

  it('adds bitrixEntityType and is idempotent', async () => {
    const create = new CreateChatLeads1786500000000();
    const alter = new AddChatLeadBitrixEntityType1786600000000();
    const qr = ds.createQueryRunner();
    await create.up(qr);
    await alter.up(qr);
    const table = await qr.getTable('chat_leads');
    expect(table?.findColumnByName('bitrixEntityType')).toBeTruthy();
    await alter.up(qr);
    expect((await qr.getTable('chat_leads'))?.findColumnByName('bitrixEntityType')).toBeTruthy();
  });
});
