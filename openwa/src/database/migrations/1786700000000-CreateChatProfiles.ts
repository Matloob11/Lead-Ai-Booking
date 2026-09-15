import { MigrationInterface, QueryRunner, Table, TableIndex } from 'typeorm';

export class CreateChatProfiles1786700000000 implements MigrationInterface {
  name = 'CreateChatProfiles1786700000000';

  public async up(queryRunner: QueryRunner): Promise<void> {
    if (await queryRunner.hasTable('chat_profiles')) return;
    const isPg = queryRunner.connection.options.type === 'postgres';
    const ts = isPg ? 'timestamp' : 'datetime';
    const idType = isPg ? 'uuid' : 'varchar';
    await queryRunner.createTable(
      new Table({
        name: 'chat_profiles',
        columns: [
          {
            name: 'id',
            type: idType,
            isPrimary: true,
            generationStrategy: 'uuid',
            default: isPg ? 'uuid_generate_v4()' : undefined,
          },
          { name: 'sessionId', type: 'varchar', isNullable: false },
          { name: 'chatId', type: 'varchar', isNullable: false },
          { name: 'displayName', type: 'varchar', isNullable: true },
          { name: 'notes', type: 'text', isNullable: true },
          { name: 'createdAt', type: ts, default: isPg ? 'now()' : 'CURRENT_TIMESTAMP' },
          { name: 'updatedAt', type: ts, default: isPg ? 'now()' : 'CURRENT_TIMESTAMP' },
        ],
      }),
      true,
    );
    await queryRunner.createIndex(
      'chat_profiles',
      new TableIndex({
        name: 'UQ_chat_profiles_session_chat',
        columnNames: ['sessionId', 'chatId'],
        isUnique: true,
      }),
    );
    await queryRunner.createIndex(
      'chat_profiles',
      new TableIndex({ name: 'IDX_chat_profiles_sessionId', columnNames: ['sessionId'] }),
    );
  }

  public async down(queryRunner: QueryRunner): Promise<void> {
    if (await queryRunner.hasTable('chat_profiles')) {
      await queryRunner.dropTable('chat_profiles');
    }
  }
}
