import { Processor, WorkerHost } from '@nestjs/bullmq';
import { Job } from 'bullmq';
import { createLogger } from '../../common/services/logger.service';
import { QUEUE_NAMES } from '../queue/queue-names';
import { workerConnectionOptions } from '../queue/redis-connection';
import type { HealthJobData } from './conversation-health.constants';
import { ConversationHealthService } from './conversation-health.service';

function healthWorkerConcurrency(): number {
  const n = parseInt(process.env.CONVERSATION_HEALTH_CONCURRENCY || '2', 10);
  return Number.isFinite(n) && n > 0 ? n : 2;
}

@Processor(QUEUE_NAMES.CONVERSATION_HEALTH, {
  connection: workerConnectionOptions(),
  concurrency: healthWorkerConcurrency(),
})
export class ConversationHealthProcessor extends WorkerHost {
  private readonly logger = createLogger('ConversationHealthProcessor');

  constructor(private readonly health: ConversationHealthService) {
    super();
  }

  async process(job: Job<HealthJobData>): Promise<void> {
    try {
      this.logger.log(`health job ${job.name} ${job.id} chat=${job.data.chatId}`);
      await this.health.processJob(job.data);
    } catch (err) {
      this.logger.error(`health job ${job.id} failed: ${String(err)}`);
      throw err;
    }
  }
}
