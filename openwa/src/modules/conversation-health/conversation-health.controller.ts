import { Body, Controller, Get, Post, Query, BadRequestException } from '@nestjs/common';
import { ApiOperation, ApiTags } from '@nestjs/swagger';
import { CurrentApiKey, RequireRole, RequireUnscopedKey } from '../auth/decorators/auth.decorators';
import { ApiKey, ApiKeyRole } from '../auth/entities/api-key.entity';
import { ConversationHealthEnqueueService } from './conversation-health.enqueue.service';
import { ConversationHealthService, type HealthListRow, type HealthSummary } from './conversation-health.service';
import type { ConversationColour } from './entities/chat-lead.entity';

const COLOURS = new Set(['red', 'pink', 'yellow', 'white', 'green']);

@ApiTags('conversation-health')
@Controller('conversation-health')
@RequireRole(ApiKeyRole.ADMIN)
export class ConversationHealthController {
  constructor(
    private readonly health: ConversationHealthService,
    private readonly enqueue: ConversationHealthEnqueueService,
  ) {}

  @Get('summary')
  @ApiOperation({ summary: 'Conversation Health colour counts (admin only)' })
  async summary(@CurrentApiKey() apiKey: ApiKey): Promise<HealthSummary> {
    return this.health.summary(apiKey.allowedSessions);
  }

  @Get('list')
  @ApiOperation({ summary: 'List chats by Conversation Health colour (admin only)' })
  async list(
    @CurrentApiKey() apiKey: ApiKey,
    @Query('colour') colour: string,
  ): Promise<HealthListRow[]> {
    const c = String(colour || '').toLowerCase();
    if (!COLOURS.has(c)) {
      throw new BadRequestException('colour must be red|pink|yellow|white|green');
    }
    return this.health.listByColour(c as ConversationColour, apiKey.allowedSessions);
  }

  @Post('allow-green')
  @ApiOperation({ summary: 'Admin: move a RED chat to GREEN after override password' })
  async allowGreen(
    @CurrentApiKey() apiKey: ApiKey,
    @Body() body: { sessionId?: string; chatId?: string; password?: string },
  ): Promise<HealthListRow> {
    const sessionId = String(body?.sessionId || '').trim();
    const chatId = String(body?.chatId || '').trim();
    const password = String(body?.password ?? '');
    if (!sessionId || !chatId) {
      throw new BadRequestException('sessionId and chatId are required');
    }
    return this.health.allowRedAsGreen(sessionId, chatId, password, apiKey.allowedSessions);
  }

  @Post('backfill')
  @RequireUnscopedKey()
  @ApiOperation({ summary: 'Enqueue Bitrix lead backfill for all individual OpenWA chats' })
  async backfill(): Promise<{ enqueued: number; enabled: boolean }> {
    if (!this.enqueue.enabled()) {
      return { enqueued: 0, enabled: false };
    }
    const targets = await this.health.listBackfillTargets();
    const enqueued = await this.enqueue.enqueueBackfill(targets);
    return { enqueued, enabled: true };
  }

  @Post('reclassify-false-red')
  @ApiOperation({
    summary: 'Re-run AI classify on unlocked RED chats (clears false RED when reason is clean)',
  })
  async reclassifyFalseRed(
    @CurrentApiKey() apiKey: ApiKey,
  ): Promise<{ enqueued: number; enabled: boolean; candidates: number }> {
    if (!this.enqueue.enabled()) {
      return { enqueued: 0, enabled: false, candidates: 0 };
    }
    const scoped =
      apiKey.allowedSessions != null && apiKey.allowedSessions.length > 0
        ? apiKey.allowedSessions
        : undefined;
    const targets = await this.health.listFalseRedTargets(scoped);
    const enqueued = await this.enqueue.enqueueReclassify(targets);
    return { enqueued, enabled: true, candidates: targets.length };
  }
}
