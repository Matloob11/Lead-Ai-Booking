import { DataSource } from 'typeorm';
import { AddLosslessHistorySyncState1786300000000 } from '../1786300000000-AddLosslessHistorySyncState';

describe('AddLosslessHistorySyncState1786300000000', () => {
  let ds: DataSource;

  beforeEach(async () => {
    ds = new DataSource({ type: 'better-sqlite3', database: ':memory:', entities: [], migrations: [] });
    await ds.initialize();
    await ds.query(
      'CREATE TABLE sessions (id varchar PRIMARY KEY, phone varchar, historyImportedAt datetime, createdAt datetime)',
    );
    await ds.query(
      "INSERT INTO sessions (id, phone, historyImportedAt, createdAt) VALUES ('s1', '923166753715', '2026-08-01', '2025-01-01')",
    );
  });

  afterEach(async () => ds.destroy());

  it('adds only nullable durable identity/sync columns and preserves every existing value', async () => {
    await new AddLosslessHistorySyncState1786300000000().up(ds.createQueryRunner());

    const columns = await ds.query<Array<{ name: string; notnull: number }>>('PRAGMA table_info(sessions)');
    expect(
      columns.filter(column => column.name.startsWith('history')).map(column => [column.name, column.notnull]),
    ).toEqual(
      expect.arrayContaining([
        ['historyImportedAt', 0],
        ['historyFirstLinkedAt', 0],
        ['historySyncToken', 0],
        ['historySyncError', 0],
      ]),
    );
    await expect(ds.query('SELECT id, phone, historyImportedAt FROM sessions')).resolves.toEqual([
      expect.objectContaining({ id: 's1', phone: '923166753715' }),
    ]);
  });
});
