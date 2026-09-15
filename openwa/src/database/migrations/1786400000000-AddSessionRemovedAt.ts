import { MigrationInterface, QueryRunner, TableColumn } from 'typeorm';

/** Soft-remove marker so session delete keeps messages for All chats / later reconnect. */
export class AddSessionRemovedAt1786400000000 implements MigrationInterface {
  name = 'AddSessionRemovedAt1786400000000';

  public async up(queryRunner: QueryRunner): Promise<void> {
    const dateType = queryRunner.connection.options.type === 'postgres' ? 'timestamp' : 'datetime';
    if (!(await queryRunner.hasColumn('sessions', 'removedAt'))) {
      await queryRunner.addColumn(
        'sessions',
        new TableColumn({ name: 'removedAt', type: dateType, isNullable: true }),
      );
    }
  }

  public async down(queryRunner: QueryRunner): Promise<void> {
    if (await queryRunner.hasColumn('sessions', 'removedAt')) {
      await queryRunner.dropColumn('sessions', 'removedAt');
    }
  }
}
