import {
  formatChatLine,
  formatThreadForBitrixField,
  sanitizeChatBody,
  softWrapLine,
  takeThreadTail,
} from './conversation-health.format';

describe('conversation-health.format', () => {
  it('flattens multiline bodies and truncates long ones', () => {
    expect(sanitizeChatBody('hello\nworld')).toBe('hello world');
    expect(sanitizeChatBody('x'.repeat(300)).endsWith('…')).toBe(true);
  });

  it('replaces vCards with a short label', () => {
    const body = 'BEGIN:VCARD\nVERSION:3.0\nFN:Aftab\nEND:VCARD';
    expect(sanitizeChatBody(body)).toBe('[contact card]');
  });

  it('formats AGENT/CLIENT lines', () => {
    expect(formatChatLine('AGENT', '  hi  ')).toBe('AGENT: hi');
    expect(formatChatLine('CLIENT', '')).toBe('CLIENT: [message]');
  });

  it('soft-wraps long lines for Bitrix SIZE≈20 textareas', () => {
    const wrapped = softWrapLine('AGENT: please send the documents today thanks', 20);
    expect(wrapped).toContain('\n');
    expect(wrapped.split('\n').every(l => l.length <= 20)).toBe(true);
  });

  it('takes thread tail on a newline boundary', () => {
    const thread = 'AGENT: one\nCLIENT: two\nAGENT: three';
    expect(takeThreadTail(thread, 20)).toBe('AGENT: three');
    expect(takeThreadTail('short', 100)).toBe('short');
  });

  it('formats a thread for the UF field', () => {
    const out = formatThreadForBitrixField(
      'AGENT: short\nCLIENT: BEGIN:VCARD\nVERSION:3.0\nEND:VCARD please call',
      500,
    );
    expect(out).toContain('AGENT: short');
    expect(out.replace(/\n/g, ' ')).toContain('[contact card]');
    expect(out).not.toContain('BEGIN:VCARD');
  });
});
