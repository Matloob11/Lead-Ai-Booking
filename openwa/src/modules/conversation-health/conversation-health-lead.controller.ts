import { Controller, Get, Param } from '@nestjs/common';
import { ApiOperation, ApiTags } from '@nestjs/swagger';
import { ConversationHealthService } from './conversation-health.service';
import type { ConversationColour } from './entities/chat-lead.entity';

@ApiTags('conversation-health')
@Controller('sessions/:sessionId/chats')
export class ConversationHealthLeadController {
  constructor(private readonly health: ConversationHealthService) {}

  @Get(':chatId/lead')
  @ApiOperation({ summary: 'Bitrix lead link for a chat (if synced)' })
  async getLead(
    @Param('sessionId') sessionId: string,
    @Param('chatId') chatId: string,
  ): Promise<{ bitrixLeadId: string; leadUrl: string; colour: ConversationColour | null } | { found: false }> {
    const row = await this.health.getLeadForChat(sessionId, decodeURIComponent(chatId));
    if (!row) return { found: false };
    return row;
  }
}
