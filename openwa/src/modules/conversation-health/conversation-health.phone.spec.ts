import { isGroupOrNewsletterChat, resolveChatPhone, maskPhone } from './conversation-health.phone';

describe('conversation-health.phone', () => {
  it('skips groups and newsletters', () => {
    expect(isGroupOrNewsletterChat('120363@g.us')).toBe(true);
    expect(isGroupOrNewsletterChat('123@newsletter')).toBe(true);
    expect(isGroupOrNewsletterChat('971501234567@c.us')).toBe(false);
  });

  it('resolves phone from c.us JID', () => {
    expect(resolveChatPhone('971501234567@c.us', 'Ali')).toBe('971501234567');
  });

  it('prefers phone-like name over LID local part', () => {
    expect(resolveChatPhone('169436594094098@lid', '971501112223')).toBe('971501112223');
  });

  it('returns null for LID without phone name', () => {
    expect(resolveChatPhone('169436594094098@lid', 'Some Name')).toBeNull();
  });

  it('masks phones', () => {
    expect(maskPhone('971501234567')).toBe('971…567');
  });
});
