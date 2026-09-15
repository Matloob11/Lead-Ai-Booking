import { Entity, PrimaryGeneratedColumn, Column, CreateDateColumn, UpdateDateColumn, Index } from 'typeorm';
import { dateColumnType } from '../../../common/utils/column-types';
import { DateTransformer } from '../../../common/transformers/date.transformer';

export type ConversationColour = 'red' | 'pink' | 'yellow' | 'white' | 'green';

@Entity('chat_leads')
@Index('UQ_chat_leads_session_chat', ['sessionId', 'chatId'], { unique: true })
@Index('IDX_chat_leads_colour', ['colour'])
@Index('IDX_chat_leads_sessionId', ['sessionId'])
export class ChatLead {
  @PrimaryGeneratedColumn('uuid')
  id!: string;

  @Column({ type: 'varchar', length: 36 })
  sessionId!: string;

  @Column({ type: 'varchar', length: 255 })
  chatId!: string;

  @Column({ type: 'varchar', length: 64, nullable: true })
  phone!: string | null;

  @Column({ type: 'varchar', length: 255, nullable: true })
  chatName!: string | null;

  @Column({ type: 'varchar', length: 64 })
  bitrixLeadId!: string;

  /** "lead" or "DYNAMIC_1042" (Owner Data SPA). */
  @Column({ type: 'varchar', length: 32, default: 'lead' })
  bitrixEntityType!: string;

  @Column({ type: 'varchar', length: 16, nullable: true })
  colour!: ConversationColour | null;

  /** When true, AI reclassify will not overwrite colour (admin Allow-as-green). */
  @Column({ type: 'boolean', default: false })
  colourLocked!: boolean;

  @Column({ type: 'integer', default: 0 })
  messageCountSinceClassify!: number;

  @Column({ type: dateColumnType(), nullable: true, transformer: DateTransformer })
  lastClassifiedAt!: Date | null;

  @Column({ type: 'varchar', length: 255, nullable: true })
  lastSyncedMessageId!: string | null;

  // SQLite + dateColumnType: rely on DB defaults (same as Message) so INSERT never omits createdAt.
  @CreateDateColumn({ type: dateColumnType(), transformer: DateTransformer })
  createdAt!: Date;

  @UpdateDateColumn({ type: dateColumnType(), transformer: DateTransformer })
  updatedAt!: Date;
}
