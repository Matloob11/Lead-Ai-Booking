import { Injectable } from '@nestjs/common';
import { createLogger } from '../../common/services/logger.service';
import { SYSTEM_PROMPT } from './conversation-health.constants';
import type { ConversationColour } from './entities/chat-lead.entity';

export interface ClassifyResult {
  category: ConversationColour;
  confidence: number;
  reason: string;
  flags: string[];
  needs_human_review: boolean;
}

const COLOURS = new Set<ConversationColour>(['red', 'pink', 'yellow', 'white', 'green']);

/** Reasons that clearly say the chat is fine — must not stay RED. */
function looksLikeCleanReason(reason: string): boolean {
  const r = reason.toLowerCase();
  if (!r.trim()) return false;
  const clean =
    /\b(normal|clean|no (integrity|corruption|risk)|nothing (wrong|suspicious)|no problems?)\b/.test(
      r,
    );
  const stillBad =
    /\b(outside (the )?compan|personal account|commission|bypass|off[- ]books|side deal)\b/.test(r);
  return clean && !stillBad;
}

@Injectable()
export class OpenAiHealthClient {
  private readonly logger = createLogger('OpenAiHealthClient');

  enabled(): boolean {
    return Boolean(this.apiKey());
  }

  private apiKey(): string {
    return process.env.OPENAI_API_KEY || '';
  }

  private model(): string {
    return process.env.OPENAI_MODEL || 'gpt-4o-mini';
  }

  async classify(agentName: string, agentPhone: string, clientPhone: string, thread: string): Promise<ClassifyResult> {
    const key = this.apiKey();
    if (!key) throw new Error('OPENAI_API_KEY missing');
    const user = `CHANNEL: whatsapp\nAGENT: ${agentName} (${agentPhone || 'unknown'})\nCLIENT: ${clientPhone}\nCONVERSATION:\n${thread}`;
    const res = await fetch('https://api.openai.com/v1/chat/completions', {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${key}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        model: this.model(),
        temperature: 0.1,
        response_format: { type: 'json_object' },
        messages: [
          { role: 'system', content: SYSTEM_PROMPT },
          { role: 'user', content: user },
        ],
      }),
      signal: AbortSignal.timeout(90_000),
    });
    if (!res.ok) {
      const detail = (await res.text()).slice(0, 300);
      throw new Error(`OpenAI classify HTTP ${res.status}: ${detail}`);
    }
    const data = (await res.json()) as {
      choices?: Array<{ message?: { content?: string } }>;
    };
    const content = data.choices?.[0]?.message?.content || '{}';
    const parsed = JSON.parse(content) as Partial<ClassifyResult>;
    let category = String(parsed.category || 'green').toLowerCase().trim() as ConversationColour;
    if (!COLOURS.has(category)) category = 'green';
    const reason = String(parsed.reason || '');
    // Guard false RED when the model contradicts itself in the reason text.
    if (category === 'red' && looksLikeCleanReason(reason)) {
      category = 'green';
    }
    return {
      category,
      confidence: Number(parsed.confidence) || 0,
      reason,
      flags: Array.isArray(parsed.flags) ? parsed.flags.map(String) : [],
      needs_human_review: Boolean(parsed.needs_human_review),
    };
  }

  /**
   * Transcribe audio via Whisper. `audio` is raw bytes; `filename` hints format (e.g. audio.ogg).
   * Returns empty string on failure (fail-open for classify path).
   */
  async transcribe(audio: Buffer, filename = 'audio.ogg'): Promise<string> {
    const key = this.apiKey();
    if (!key || !audio.length) return '';
    try {
      const form = new FormData();
      form.append('file', new Blob([new Uint8Array(audio)]), filename);
      form.append('model', 'whisper-1');
      const res = await fetch('https://api.openai.com/v1/audio/transcriptions', {
        method: 'POST',
        headers: { Authorization: `Bearer ${key}` },
        body: form,
        signal: AbortSignal.timeout(120_000),
      });
      if (!res.ok) {
        this.logger.warn(`Whisper HTTP ${res.status}`);
        return '';
      }
      const data = (await res.json()) as { text?: string };
      return (data.text || '').trim();
    } catch (err) {
      this.logger.warn(`Whisper failed: ${String(err)}`);
      return '';
    }
  }
}
