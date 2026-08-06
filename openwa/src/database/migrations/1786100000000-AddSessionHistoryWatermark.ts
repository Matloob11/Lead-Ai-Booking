import { MigrationInterface, QueryRunner } from 'typeorm';

/**
 * Adds `sessions.historyImportedAt` — how far back the history importer has read, or NULL when it
 * never has. NULL means a first link (fixed window); a date means a reconnect (read the whole gap
 * from there to now). Hand-authored because `synchronize` is off on the `data` connection for
 * Postgres.
 */
export class AddSessionHistoryWatermark1786100000000 implements MigrationInterface {
  name = 'AddSessionHistoryWatermark1786100000000';

  public async up(queryRunner: QueryRunner): Promise<void> {
    if (await queryRunner.hasColumn('sessions', 'historyImportedAt')) return;
    // datetime, not timestamptz: matches dateColumnType() on both SQLite and Postgres, which is
    // what every other date column on this table already uses.
    const isPostgres = queryRunner.connection.options.type === 'postgres';
    await queryRunner.query(
      `ALTER TABLE "sessions" ADD COLUMN "historyImportedAt" ${isPostgres ? 'TIMESTAMP' : 'datetime'}`,
    );
  }

  public async down(queryRunner: QueryRunner): Promise<void> {
    if (!(await queryRunner.hasColumn('sessions', 'historyImportedAt'))) return;
    await queryRunner.query(`ALTER TABLE "sessions" DROP COLUMN "historyImportedAt"`);
  }
}
