import { Body, Controller, Get, Param, Patch } from '@nestjs/common';
import { ApiOperation, ApiTags } from '@nestjs/swagger';
import { IsBoolean, IsOptional, IsString, MaxLength } from 'class-validator';
import { ChatProfileService } from './chat-profile.service';

class PatchChatProfileDto {
  @IsOptional()
  @IsString()
  @MaxLength(255)
  displayName?: string | null;

  @IsOptional()
  @IsString()
  @MaxLength(20000)
  notes?: string | null;

  @IsOptional()
  @IsBoolean()
  pinned?: boolean;
}

@ApiTags('chat-profile')
@Controller('sessions/:sessionId')
export class ChatProfileController {
  constructor(private readonly profiles: ChatProfileService) {}

  @Get('chat-profiles')
  @ApiOperation({ summary: 'Team display names + pinned chat ids for this session (sidebar overlay)' })
  async listNames(
    @Param('sessionId') sessionId: string,
  ): Promise<{ names: Record<string, string>; pinned: string[] }> {
    return this.profiles.listDisplayNames(sessionId);
  }

  @Get('chats/:chatId/profile')
  @ApiOperation({ summary: 'Contact profile side panel payload (name, notes, lead, stats, media)' })
  async get(
    @Param('sessionId') sessionId: string,
    @Param('chatId') chatId: string,
  ) {
    return this.profiles.getProfile(sessionId, decodeURIComponent(chatId));
  }

  @Patch('chats/:chatId/profile')
  @ApiOperation({ summary: 'Save team-local display name and/or notes for a chat' })
  async patch(
    @Param('sessionId') sessionId: string,
    @Param('chatId') chatId: string,
    @Body() body: PatchChatProfileDto,
  ) {
    return this.profiles.patchProfile(sessionId, decodeURIComponent(chatId), body);
  }
}
