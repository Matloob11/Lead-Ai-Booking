import { MigrationInterface, QueryRunner } from 'typeorm';

/**
 * Adds `sessions.syncProgress` — 0 to 100 percentage indicator of history import / sync.
 * Default 100 so existing sessions count as 100% ready.
 */
export class AddSessionSyncProgress1786200000000 implements MigrationInterface {
  name = 'AddSessionSyncProgress1786200000000';

  public async up(queryRunner: QueryRunner): Promise<void> {
    if (await queryRunner.hasColumn('sessions', 'syncProgress')) return;
    await queryRunner.query(
      `ALTER TABLE "sessions" ADD COLUMN "syncProgress" INTEGER NOT NULL DEFAULT 100`,
    );
  }

  public async down(queryRunner: QueryRunner): Promise<void> {
    if (!(await queryRunner.hasColumn('sessions', 'syncProgress'))) return;
    await queryRunner.query(`ALTER TABLE "sessions" DROP COLUMN "syncProgress"`);
  }
}
