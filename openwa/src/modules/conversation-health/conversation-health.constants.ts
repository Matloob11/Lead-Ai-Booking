import type { ConversationColour } from './entities/chat-lead.entity';

/** Bitrix Owner Data smart process (see backend/apps/crmlink/client.py). */
export const OWNER_DATA_TYPE_ID = 1042;
export const OWNER_DATA_PHONE_FIELDS = [
  'ufCrm5_1768317611513',
  'ufCrm5_1769416533028',
] as const;

export const ENUM_IDS: Record<ConversationColour, string> = {
  red: '2307',
  pink: '2308',
  yellow: '2309',
  white: '2310',
  green: '2311',
};

export const COLOUR_LIGHT: Record<ConversationColour, string> = {
  red: '🔴 RED',
  pink: '🩷 PINK',
  yellow: '🟡 YELLOW',
  white: '⚪ WHITE',
  green: '🟢 GREEN',
};

export const RECLASSIFY_EVERY_N = 10;
export const CHAT_FIELD_CHARS = 3500;
export const CLASSIFY_MSG_CHARS = 12000;
export const HISTORY_COMMENT_BATCH = 10;

export const SYSTEM_PROMPT = `You are a compliance and quality monitor for a Dubai real estate agency.
You read one full conversation between a company AGENT and a CLIENT.
The conversation may be a WhatsApp chat or a phone-call transcript.
Language is mostly English, sometimes Roman Urdu (Urdu in English letters) or a mix — understand all of them.
Classify the WHOLE conversation into exactly ONE colour:
- "red"    = Corruption / integrity risk. Clear evidence the agent is moving money or the deal OUTSIDE the company (personal account, off-books commission, "don't tell the office", bypass CRM).
- "pink"   = The CLIENT is unprofessional: abusive, threatening, insulting, or aggressively complaining.
- "yellow" = The AGENT cannot satisfy the client: no matching property, wrong budget/area, capability gap.
- "white"  = Hot, healthy deal: client interested, both sides professional, closing being discussed.
- "green"  = Normal, clean, ongoing conversation with no problems and no closing discussion yet.
Rules:
- Judge by the MEANING of the whole conversation, not single words.
- RED requires clear evidence. Vague suspicion is NOT red — use green and set needs_human_review true if unsure.
- Normal property talk, viewing schedules, pricing within company process, or polite negotiation is green (or white if actively closing).
- Never output category "red" if your reason says the chat is normal, clean, or has no integrity issue — that must be "green".
- category and reason MUST agree. RED takes priority only when evidence is clear.
Respond with ONLY this JSON, nothing else:
{"category":"red|pink|yellow|white|green","confidence":0.0,"reason":"one short sentence","flags":[],"needs_human_review":false}
`;

export type HealthJobKind = 'mirror' | 'backfill_chat' | 'reclassify_chat';

export interface HealthJobData {
  kind: HealthJobKind;
  sessionId: string;
  chatId: string;
  /** For live mirror jobs */
  messageId?: string;
  waMessageId?: string;
  body?: string;
  type?: string;
  fromMe?: boolean;
  chatName?: string | null;
  phoneHint?: string | null;
}
