import { MigrationInterface, QueryRunner, TableColumn } from 'typeorm';

/** Team-local pin for the Linked phones sidebar (WhatsApp pin is engine-side; we keep ours). */
export class AddChatProfilePinned1786900000000 implements MigrationInterface {
  name = 'AddChatProfilePinned1786900000000';

  public async up(queryRunner: QueryRunner): Promise<void> {
    if (!(await queryRunner.hasTable('chat_profiles'))) return;
    const table = await queryRunner.getTable('chat_profiles');
    if (table?.findColumnByName('pinned')) return;
    await queryRunner.addColumn(
      'chat_profiles',
      new TableColumn({
        name: 'pinned',
        type: 'boolean',
        isNullable: false,
        default: false,
      }),
    );
  }

  public async down(queryRunner: QueryRunner): Promise<void> {
    if (!(await queryRunner.hasTable('chat_profiles'))) return;
    const table = await queryRunner.getTable('chat_profiles');
    if (!table?.findColumnByName('pinned')) return;
    await queryRunner.dropColumn('chat_profiles', 'pinned');
  }
}
