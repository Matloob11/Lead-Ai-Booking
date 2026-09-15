import { Injectable, Optional } from '@nestjs/common';
import { InjectQueue } from '@nestjs/bullmq';
import { Queue } from 'bullmq';
import { createLogger } from '../../common/services/logger.service';
import { QUEUE_NAMES } from '../queue/queue-names';
import type { HealthJobData } from './conversation-health.constants';
import { BitrixLeadClient } from './bitrix-lead.client';
import { isGroupOrNewsletterChat } from './conversation-health.phone';

/** BullMQ custom job ids reject `:`; WA chatIds / lids often contain `@` and `:`. */
export function bullJobId(parts: string[], maxLen = 120): string {
  return parts
    .join('-')
    .replace(/[^A-Za-z0-9_-]+/g, '_')
    .slice(0, maxLen);
}

/**
 * Fire-and-forget enqueue from MessageProjector. Optional InjectQueue so tests / Redis-off
 * builds still construct the projector when the queue is absent.
 */
@Injectable()
export class ConversationHealthEnqueueService {
  private readonly logger = createLogger('ConversationHealthEnqueue');

  constructor(
    private readonly bitrix: BitrixLeadClient,
    @Optional()
    @InjectQueue(QUEUE_NAMES.CONVERSATION_HEALTH)
    private readonly queue?: Queue<HealthJobData>,
  ) {}

  enabled(): boolean {
    const flag = (process.env.CONVERSATION_HEALTH_ENABLED || '').toLowerCase();
    if (flag === 'false' || flag === '0') return false;
    if (flag === 'true' || flag === '1') return Boolean(this.queue && this.bitrix.enabled());
    // Default: on whenever Bitrix webhook is configured and the queue exists.
    return Boolean(this.queue && this.bitrix.enabled());
  }

  enqueueMirror(job: HealthJobData): void {
    if (!this.enabled() || !this.queue) return;
    if (isGroupOrNewsletterChat(job.chatId)) return;
    void this.queue
      .add('mirror', { ...job, kind: 'mirror' }, {
        jobId: job.messageId ? bullJobId(['mirror', job.messageId]) : undefined,
        removeOnComplete: { age: 3600, count: 2000 },
        removeOnFail: { age: 86400, count: 5000 },
        attempts: 3,
        backoff: { type: 'exponential', delay: 2000 },
      })
      .catch(err => this.logger.warn(`enqueue mirror failed: ${String(err)}`));
  }

  async enqueueBackfill(jobs: HealthJobData[]): Promise<number> {
    if (!this.enabled() || !this.queue) return 0;
    // Unique per run: reusing a completed custom jobId makes BullMQ return the old job and skip work.
    const runId = Date.now().toString(36);
    let n = 0;
    for (const job of jobs) {
      if (isGroupOrNewsletterChat(job.chatId)) continue;
      await this.queue.add(
        'backfill',
        { ...job, kind: 'backfill_chat' },
        {
          jobId: bullJobId(['bf', runId, job.sessionId, job.chatId]),
          removeOnComplete: { age: 3600, count: 2000 },
          removeOnFail: { age: 86400, count: 5000 },
          attempts: 3,
          backoff: { type: 'exponential', delay: 5000 },
        },
      );
      n += 1;
    }
    return n;
  }

  async enqueueReclassify(jobs: HealthJobData[]): Promise<number> {
    if (!this.enabled() || !this.queue) return 0;
    const runId = Date.now().toString(36);
    let n = 0;
    for (const job of jobs) {
      if (isGroupOrNewsletterChat(job.chatId)) continue;
      await this.queue.add(
        'reclassify',
        { ...job, kind: 'reclassify_chat' },
        {
          jobId: bullJobId(['rc', runId, job.sessionId, job.chatId]),
          removeOnComplete: { age: 3600, count: 2000 },
          removeOnFail: { age: 86400, count: 5000 },
          attempts: 2,
          backoff: { type: 'exponential', delay: 4000 },
        },
      );
      n += 1;
    }
    return n;
  }
}
