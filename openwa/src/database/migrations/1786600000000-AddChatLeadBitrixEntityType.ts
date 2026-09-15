import { MigrationInterface, QueryRunner, TableColumn } from 'typeorm';

export class AddChatLeadBitrixEntityType1786600000000 implements MigrationInterface {
  name = 'AddChatLeadBitrixEntityType1786600000000';

  public async up(queryRunner: QueryRunner): Promise<void> {
    if (!(await queryRunner.hasTable('chat_leads'))) return;
    const table = await queryRunner.getTable('chat_leads');
    if (table?.findColumnByName('bitrixEntityType')) return;
    await queryRunner.addColumn(
      'chat_leads',
      new TableColumn({
        name: 'bitrixEntityType',
        type: 'varchar',
        length: '32',
        isNullable: false,
        default: "'lead'",
      }),
    );
  }

  public async down(queryRunner: QueryRunner): Promise<void> {
    if (!(await queryRunner.hasTable('chat_leads'))) return;
    const table = await queryRunner.getTable('chat_leads');
    if (!table?.findColumnByName('bitrixEntityType')) return;
    await queryRunner.dropColumn('chat_leads', 'bitrixEntityType');
  }
}
