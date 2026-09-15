import { Entity, PrimaryGeneratedColumn, Column, CreateDateColumn, UpdateDateColumn, Index } from 'typeorm';
import { dateColumnType } from '../../../common/utils/column-types';
import { DateTransformer } from '../../../common/transformers/date.transformer';

/**
 * Team-local contact card for one (session, chat) — name and notes the customer never sees.
 * Separate from chat_leads (Bitrix sync) and from the WhatsApp addressbook.
 */
@Entity('chat_profiles')
@Index('UQ_chat_profiles_session_chat', ['sessionId', 'chatId'], { unique: true })
@Index('IDX_chat_profiles_sessionId', ['sessionId'])
export class ChatProfile {
  @PrimaryGeneratedColumn('uuid')
  id!: string;

  @Column({ type: 'varchar', length: 36 })
  sessionId!: string;

  @Column({ type: 'varchar', length: 255 })
  chatId!: string;

  /** Agent-facing display name. Null/empty → fall back to WhatsApp / engine name. */
  @Column({ type: 'varchar', length: 255, nullable: true })
  displayName!: string | null;

  @Column({ type: 'text', nullable: true })
  notes!: string | null;

  /** Team-local pin — keeps the chat at the top of the Linked phones list. */
  @Column({ type: 'boolean', default: false })
  pinned!: boolean;

  @CreateDateColumn({ type: dateColumnType(), transformer: DateTransformer })
  createdAt!: Date;

  @UpdateDateColumn({ type: dateColumnType(), transformer: DateTransformer })
  updatedAt!: Date;
}
