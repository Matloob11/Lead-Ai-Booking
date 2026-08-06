import { Entity, Column, PrimaryGeneratedColumn, CreateDateColumn, UpdateDateColumn } from 'typeorm';
import { DateTransformer } from '../../../common/transformers/date.transformer';
import { jsonColumnType, dateColumnType } from '../../../common/utils/column-types';
import type { AccountRestriction } from '../../../engine/interfaces/whatsapp-engine.interface';

export enum SessionStatus {
  CREATED = 'created',
  INITIALIZING = 'initializing',
  QR_READY = 'qr_ready',
  AUTHENTICATING = 'authenticating',
  READY = 'ready',
  DISCONNECTED = 'disconnected',
  ACTION_REQUIRED = 'action_required',
  FAILED = 'failed',
}

@Entity('sessions')
export class Session {
  @PrimaryGeneratedColumn('uuid')
  id!: string;

  @Column({ type: 'varchar', length: 100, unique: true })
  name!: string;

  @Column({
    type: 'varchar',
    length: 50,
    default: SessionStatus.CREATED,
  })
  status!: SessionStatus;

  @Column({ type: 'varchar', length: 20, nullable: true })
  phone!: string | null;

  @Column({ type: 'varchar', length: 100, nullable: true })
  pushName!: string | null;

  @Column({ type: jsonColumnType(), default: '{}' })
  config!: Record<string, unknown>;

  // Phase 3: Proxy per session
  @Column({ type: 'varchar', length: 255, nullable: true })
  proxyUrl!: string | null;

  @Column({ type: 'varchar', length: 10, nullable: true })
  proxyType!: 'http' | 'https' | 'socks4' | 'socks5' | null;

  @Column({ type: dateColumnType(), nullable: true, transformer: DateTransformer })
  connectedAt!: Date | null;

  @Column({ type: dateColumnType(), nullable: true, transformer: DateTransformer })
  lastActiveAt!: Date | null;

  /**
   * Which process currently hosts this session's engine, or NULL when nobody does.
   *
   * A session's engine lives in exactly one process. Recording the owner is what lets a booting
   * process tell "my own leftovers, which really are dead" from "another process's live session",
   * which it previously could not and so reset both.
   */
  @Column({ type: 'varchar', length: 190, nullable: true })
  nodeId!: string | null;

  @Column({ type: dateColumnType(), nullable: true, transformer: DateTransformer })
  claimedAt!: Date | null;

  /**
   * Where the owning node answers HTTP, so a peer can forward a request it cannot serve (the
   * engine lives with the owner). Written at claim time from NODE_URL; null when the operator has
   * not configured routing — a peer then answers 409 instead of forwarding.
   */
  @Column({ type: 'varchar', length: 2048, nullable: true })
  nodeUrl!: string | null;

  /**
   * When the claim above stops being honoured. A process that dies without releasing leaves a row
   * pointing at an owner that is gone, so the claim expires rather than requiring a clean shutdown
   * to recover; a running owner keeps extending it.
   */
  @Column({ type: dateColumnType(), nullable: true, transformer: DateTransformer })
  leaseExpiresAt!: Date | null;

  /**
   * How far this session's history has been read back, or NULL when it never has.
   *
   * The watermark decides what the next import asks for, and the two cases are different on
   * purpose. NULL is a first link: reach back a fixed window, because everything before it is
   * older than anyone is going to scroll to. A date is a reconnect: read from there to now,
   * however long that is — a phone away for sixty days brings back sixty days, so nothing said
   * while it was gone is missing.
   *
   * Only ever moved forward on a run that finished. A run that stopped half way leaves it where
   * it was, so the next one covers the same stretch again rather than skipping past what it did
   * not manage to read; the unique index on (sessionId, waMessageId) makes repeating a stretch
   * cost only the reading.
   */
  @Column({ type: dateColumnType(), nullable: true, transformer: DateTransformer })
  historyImportedAt!: Date | null;

  @CreateDateColumn()
  createdAt!: Date;

  @UpdateDateColumn()
  updatedAt!: Date;

  /**
   * Transient (non-persisted) human-readable reason for the most recent terminal
   * engine failure. Populated at read time from the in-memory error map so the
   * dashboard can explain a FAILED status; intentionally not a column because it
   * is runtime state that resets when the engine re-initializes.
   */
  lastError?: string;

  /**
   * Transient (non-persisted) restriction WhatsApp currently has in force on this session's account,
   * or null when there is none. Populated at read time from SessionRestrictionStore, which explains
   * why it is runtime state rather than a column.
   */
  restriction?: AccountRestriction | null;
}
