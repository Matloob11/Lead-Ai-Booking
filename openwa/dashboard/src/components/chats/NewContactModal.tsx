import { useCallback, useEffect, useRef, useState } from 'react';
import { Loader2, X } from 'lucide-react';
import { contactApi, messageApi, type Chat, type Session } from '../../services/api';

/**
 * A7: starting a conversation with a number nobody has messaged yet.
 *
 * The chat list only ever shows people who already exist in it, so until now an
 * agent could answer a customer and never reach one. This is the only screen in
 * the dashboard that writes to a stranger.
 *
 * The number is checked against WhatsApp *before* the send rather than after.
 * Sending to a number that is not on WhatsApp fails, and a run of failures from
 * one handset is the behaviour these accounts are restricted for — so the
 * question is asked while it is still free to ask.
 */

const CHECK_DEBOUNCE_MS = 500;
const MIN_DIGITS = 8;
const MAX_DIGITS = 15; // E.164 allows no more

/**
 * The dialling codes this business actually deals with, longest first.
 *
 * Deliberately short. It exists for one job — reading a local number typed with
 * a leading zero against the country the linked phone is in — and a full table
 * would be a country database nobody here maintains. A code that is missing
 * costs nothing: the number is simply taken as typed, and the check below is
 * what decides whether it was right.
 */
const COUNTRY_CODES = ['971', '966', '974', '973', '968', '965', '964', '962', '92', '91', '90', '44', '20', '7', '1'];

const digitsOf = (value: string) => value.replace(/\D/g, '');

function countryOf(sessionPhone: string | null | undefined): string {
  const own = digitsOf(sessionPhone ?? '');
  return COUNTRY_CODES.find(code => own.startsWith(code)) ?? '';
}

/**
 * "+971 55 548 4423", "0555484423" and "555484423" are one number to a person
 * and three different strings to a computer. This makes them one again.
 *
 * The rules, in the order they apply:
 *   +…  or 00…  the caller has said which country; take the digits
 *   0…          a local number; the leading 0 stands in for the linked phone's
 *               own country code
 *   anything    already international if it starts with a known code, local if
 *               it does not
 */
export function normalisePhone(typed: string, sessionPhone: string | null | undefined): string {
  const trimmed = typed.trim();
  const digits = digitsOf(trimmed);
  if (!digits) return '';

  const country = countryOf(sessionPhone);

  if (trimmed.startsWith('+')) return digits;
  if (digits.startsWith('00')) return digits.slice(2);
  if (digits.startsWith('0')) return country ? country + digits.slice(1) : digits.slice(1);
  if (country && digits.startsWith(country)) return digits;
  return country ? country + digits : digits;
}

type Verdict =
  | { state: 'idle' }
  | { state: 'checking' }
  | { state: 'on'; whatsappId: string }
  | { state: 'off' }
  | { state: 'unknown'; why: string };

interface NewContactModalProps {
  session: Session;
  onClose: () => void;
  /** Hands the caller a chat to open once the first message has gone. */
  onStarted: (chat: Chat) => void;
}

function NewContactModal({ session, onClose, onStarted }: NewContactModalProps) {
  const [typed, setTyped] = useState('');
  const [body, setBody] = useState('');
  const [verdict, setVerdict] = useState<Verdict>({ state: 'idle' });
  const [sending, setSending] = useState(false);
  const [problem, setProblem] = useState('');
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const number = normalisePhone(typed, session.phone);
  const usable = number.length >= MIN_DIGITS && number.length <= MAX_DIGITS;

  const check = useCallback(
    async (target: string) => {
      setVerdict({ state: 'checking' });
      try {
        const answer = await contactApi.checkNumber(session.id, target);
        // The agent has typed on since this went out.
        setTyped(current => {
          if (normalisePhone(current, session.phone) !== target) return current;
          setVerdict(
            answer.exists && answer.whatsappId
              ? { state: 'on', whatsappId: answer.whatsappId }
              : { state: 'off' },
          );
          return current;
        });
      } catch (error) {
        // Said out loud rather than passed off as "fine". The check is the point
        // of this field, and an agent should know when it did not happen.
        setVerdict({ state: 'unknown', why: error instanceof Error ? error.message : String(error) });
      }
    },
    [session.id, session.phone],
  );

  useEffect(() => {
    if (timer.current) clearTimeout(timer.current);
    if (!usable) {
      setVerdict({ state: 'idle' });
      return;
    }
    timer.current = setTimeout(() => void check(number), CHECK_DEBOUNCE_MS);
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, [number, usable, check]);

  const send = async () => {
    const text = body.trim();
    if (!text || !usable) return;

    setSending(true);
    setProblem('');
    try {
      // The engine's own id when the check gave one. `@c.us` is the fallback for
      // the case where the check itself could not run — the send may still work,
      // and refusing it here would be this screen deciding on WhatsApp's behalf.
      const chatId = verdict.state === 'on' ? verdict.whatsappId : `${number}@c.us`;
      await messageApi.sendText(session.id, chatId, text);
      onStarted({
        id: chatId,
        name: number,
        isGroup: false,
        kind: 'individual',
        unreadCount: 0,
        timestamp: Math.floor(Date.now() / 1000),
        lastMessage: text,
      });
    } catch (error) {
      setSending(false);
      setProblem(error instanceof Error ? error.message : String(error));
    }
  };

  const note = () => {
    if (!typed.trim()) return 'Include the country code, or start with 0 for a local number.';
    if (!usable) return `${number.length} digits — a number with its country code is ${MIN_DIGITS} to ${MAX_DIGITS}.`;
    switch (verdict.state) {
      case 'checking':
        return `Checking +${number} on WhatsApp…`;
      case 'on':
        return `+${number} is on WhatsApp.`;
      case 'off':
        return `+${number} is not on WhatsApp. Sending would fail.`;
      case 'unknown':
        return `Could not check this number: ${verdict.why}`;
      default:
        return `Will send to +${number}`;
    }
  };

  const noteClass =
    verdict.state === 'on' ? 'a7-nc__note is-ok' : verdict.state === 'off' ? 'a7-nc__note is-bad' : 'a7-nc__note';

  return (
    <div className="a7-modal" role="dialog" aria-modal="true" aria-label="New contact">
      <div className="a7-modal__box">
        <div className="a7-modal__head">
          <h2>New contact</h2>
          <button type="button" className="a7-modal__x" onClick={onClose} aria-label="Close">
            <X size={18} />
          </button>
        </div>

        <div className="a7-modal__body">
          <label className="a7-field">
            <span>Send from</span>
            <div className="a7-field__static">
              {session.name}
              {session.phone ? ` · +${digitsOf(session.phone)}` : ''}
            </div>
          </label>

          <label className="a7-field">
            <span>To this number</span>
            <input
              type="tel"
              autoComplete="off"
              value={typed}
              placeholder="+971 55 548 4423"
              onChange={e => setTyped(e.target.value)}
            />
            <small className={noteClass}>{note()}</small>
          </label>

          <label className="a7-field">
            <span>First message</span>
            <textarea
              rows={4}
              value={body}
              maxLength={4096}
              placeholder="Say who you are — a stranger's first message is the one that gets reported."
              onChange={e => setBody(e.target.value)}
            />
          </label>

          {problem && <div className="a7-alert">{problem}</div>}
        </div>

        <div className="a7-modal__foot">
          <button type="button" className="btn btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button
            type="button"
            className="btn btn-primary"
            disabled={!usable || !body.trim() || sending || verdict.state === 'off'}
            onClick={() => void send()}
          >
            {sending ? <Loader2 size={16} className="spin" /> : null}
            {sending ? 'Sending…' : 'Start the chat'}
          </button>
        </div>
      </div>
    </div>
  );
}

export default NewContactModal;
