import { MigrationInterface, QueryRunner, TableColumn } from 'typeorm';

/** Additive identity/history state only. Existing rows and values are never rewritten. */
export class AddLosslessHistorySyncState1786300000000 implements MigrationInterface {
  name = 'AddLosslessHistorySyncState1786300000000';

  public async up(queryRunner: QueryRunner): Promise<void> {
    const dateType = queryRunner.connection.options.type === 'postgres' ? 'timestamp' : 'datetime';
    const columns = [
      new TableColumn({ name: 'historyFirstLinkedAt', type: dateType, isNullable: true }),
      new TableColumn({ name: 'historySyncToken', type: 'varchar', length: '100', isNullable: true }),
      new TableColumn({ name: 'historySyncError', type: 'varchar', length: '255', isNullable: true }),
    ];
    for (const column of columns) {
      if (!(await queryRunner.hasColumn('sessions', column.name))) {
        await queryRunner.addColumn('sessions', column);
      }
    }
  }

  public async down(queryRunner: QueryRunner): Promise<void> {
    for (const name of ['historySyncError', 'historySyncToken', 'historyFirstLinkedAt']) {
      if (await queryRunner.hasColumn('sessions', name)) await queryRunner.dropColumn('sessions', name);
    }
  }
}
