import { Module, DynamicModule, Type } from '@nestjs/common';
import { TypeOrmModule } from '@nestjs/typeorm';
import { LidMapping } from '../../engine/identity/lid-mapping.entity';
import { EngineModule } from '../../engine/engine.module';
import { Message } from '../message/entities/message.entity';
import { Session } from '../session/entities/session.entity';
import { ChatLead } from './entities/chat-lead.entity';
import { ChatProfile } from './entities/chat-profile.entity';
import { BitrixLeadClient } from './bitrix-lead.client';
import { OpenAiHealthClient } from './openai-health.client';
import { ConversationHealthService } from './conversation-health.service';
import { ConversationHealthEnqueueService } from './conversation-health.enqueue.service';
import { ChatProfileService } from './chat-profile.service';
import { ConversationHealthController } from './conversation-health.controller';
import { ConversationHealthLeadController } from './conversation-health-lead.controller';
import { ChatProfileController } from './chat-profile.controller';

const queueModules: Array<Type | DynamicModule> = [];
const queueProviders: Type[] = [];
if (process.env.QUEUE_ENABLED === 'true') {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const queueModule = require('../queue/queue.module') as { QueueModule: Type };
  queueModules.push(queueModule.QueueModule);
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { ConversationHealthProcessor } = require('./conversation-health.processor') as {
    ConversationHealthProcessor: Type;
  };
  queueProviders.push(ConversationHealthProcessor);
}

/**
 * No SessionModule import — MessageProjector pulls EnqueueService the other way
 * (SessionModule imports this module) to avoid a cycle.
 */
@Module({
  imports: [
    EngineModule,
    TypeOrmModule.forFeature([ChatLead, ChatProfile, Message, Session, LidMapping], 'data'),
    ...queueModules,
  ],
  controllers: [ConversationHealthController, ConversationHealthLeadController, ChatProfileController],
  providers: [
    BitrixLeadClient,
    OpenAiHealthClient,
    ConversationHealthService,
    ConversationHealthEnqueueService,
    ChatProfileService,
    ...queueProviders,
  ],
  exports: [ConversationHealthEnqueueService, ConversationHealthService, ChatProfileService],
})
export class ConversationHealthModule {}
