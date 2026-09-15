import { MigrationInterface, QueryRunner, Table, TableIndex } from 'typeorm';

export class CreateChatLeads1786500000000 implements MigrationInterface {
  name = 'CreateChatLeads1786500000000';

  public async up(queryRunner: QueryRunner): Promise<void> {
    if (await queryRunner.hasTable('chat_leads')) return;
    const isPg = queryRunner.connection.options.type === 'postgres';
    const ts = isPg ? 'timestamp' : 'datetime';
    const idType = isPg ? 'uuid' : 'varchar';
    await queryRunner.createTable(
      new Table({
        name: 'chat_leads',
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
          { name: 'phone', type: 'varchar', isNullable: true },
          { name: 'chatName', type: 'varchar', isNullable: true },
          { name: 'bitrixLeadId', type: 'varchar', isNullable: false },
          { name: 'colour', type: 'varchar', isNullable: true },
          { name: 'messageCountSinceClassify', type: 'integer', default: 0, isNullable: false },
          { name: 'lastClassifiedAt', type: ts, isNullable: true },
          { name: 'lastSyncedMessageId', type: 'varchar', isNullable: true },
          { name: 'createdAt', type: ts, default: isPg ? 'now()' : 'CURRENT_TIMESTAMP' },
          { name: 'updatedAt', type: ts, default: isPg ? 'now()' : 'CURRENT_TIMESTAMP' },
        ],
      }),
      true,
    );
    await queryRunner.createIndex(
      'chat_leads',
      new TableIndex({ name: 'UQ_chat_leads_session_chat', columnNames: ['sessionId', 'chatId'], isUnique: true }),
    );
    await queryRunner.createIndex(
      'chat_leads',
      new TableIndex({ name: 'IDX_chat_leads_colour', columnNames: ['colour'] }),
    );
    await queryRunner.createIndex(
      'chat_leads',
      new TableIndex({ name: 'IDX_chat_leads_sessionId', columnNames: ['sessionId'] }),
    );
  }

  public async down(queryRunner: QueryRunner): Promise<void> {
    if (await queryRunner.hasTable('chat_leads')) {
      await queryRunner.dropTable('chat_leads');
    }
  }
}
