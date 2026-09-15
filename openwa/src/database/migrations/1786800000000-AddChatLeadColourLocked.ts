import { MigrationInterface, QueryRunner, TableColumn } from 'typeorm';

/** Admin Allow-as-green locks colour so AI will not flip it back to red. */
export class AddChatLeadColourLocked1786800000000 implements MigrationInterface {
  name = 'AddChatLeadColourLocked1786800000000';

  public async up(queryRunner: QueryRunner): Promise<void> {
    if (!(await queryRunner.hasTable('chat_leads'))) return;
    const table = await queryRunner.getTable('chat_leads');
    if (table?.findColumnByName('colourLocked')) return;
    await queryRunner.addColumn(
      'chat_leads',
      new TableColumn({
        name: 'colourLocked',
        type: 'boolean',
        isNullable: false,
        default: false,
      }),
    );
  }

  public async down(queryRunner: QueryRunner): Promise<void> {
    if (!(await queryRunner.hasTable('chat_leads'))) return;
    const table = await queryRunner.getTable('chat_leads');
    if (!table?.findColumnByName('colourLocked')) return;
    await queryRunner.dropColumn('chat_leads', 'colourLocked');
  }
}
