import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import {
  ArrowLeft,
  CheckCircle2,
  ExternalLink,
  Loader2,
  MessageSquare,
  RefreshCw,
  ShieldCheck,
  X,
} from 'lucide-react';
import {
  conversationHealthApi,
  type ConversationColour,
  type HealthListRow,
  type HealthSummary,
} from '../services/api';
import './ConversationHealthPanel.css';

const COLOURS: ConversationColour[] = ['red', 'pink', 'yellow', 'white', 'green'];

const COLOUR_CLASS: Record<ConversationColour, string> = {
  red: 'chp-red',
  pink: 'chp-pink',
  yellow: 'chp-yellow',
  white: 'chp-white',
  green: 'chp-green',
};

const COLOUR_DOT: Record<ConversationColour, string> = {
  red: '#ef4444',
  pink: '#ec4899',
  yellow: '#eab308',
  white: '#64748b',
  green: '#22c55e',
};

/** Agent-facing labels — yellow reads as Amber (warning), white as Hot. */
const COLOUR_LABEL: Record<ConversationColour, string> = {
  red: 'Red',
  pink: 'Pink',
  yellow: 'Amber',
  white: 'Hot',
  green: 'Green',
};

const COLOUR_MEANING: Record<ConversationColour, string> = {
  red: 'Integrity risk — deal may be moving outside the company',
  pink: 'Client issue — abuse, threats, or aggressive complaints',
  yellow: 'Agent cannot satisfy — budget / area / capability gap',
  white: 'Hot deal — interest + closing discussion',
  green: 'Clean / normal — no problems',
};

interface Props {
  compact?: boolean;
}

function rowTitle(row: HealthListRow): string {
  const name = row.name?.trim();
  if (name) return name;
  if (row.phone) return row.phone;
  return row.chatId.split('@')[0] || row.chatId;
}

function rowSubtitle(row: HealthListRow): string {
  const parts: string[] = [];
  if (row.sessionName) parts.push(row.sessionName);
  if (row.phone && row.phone !== row.name?.trim()) parts.push(row.phone);
  return parts.join(' · ');
}

export function ConversationHealthPanel({ compact = false }: Props) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [activeColour, setActiveColour] = useState<ConversationColour | null>(null);
  const [allowTarget, setAllowTarget] = useState<HealthListRow | null>(null);
  const [allowPassword, setAllowPassword] = useState('');
  const [allowBusy, setAllowBusy] = useState(false);
  const [allowError, setAllowError] = useState<string | null>(null);
  const [reclassifyBusy, setReclassifyBusy] = useState(false);
  const [reclassifyNote, setReclassifyNote] = useState<string | null>(null);

  const summaryQ = useQuery({
    queryKey: ['conversation-health', 'summary'],
    queryFn: conversationHealthApi.summary,
    staleTime: 30_000,
    retry: false,
  });

  const listQ = useQuery({
    queryKey: ['conversation-health', 'list', activeColour],
    queryFn: () => conversationHealthApi.list(activeColour!),
    enabled: Boolean(activeColour),
    staleTime: 15_000,
    retry: false,
  });

  const summary: HealthSummary | undefined = summaryQ.data;

  const openChat = (row: HealthListRow) => {
    setActiveColour(null);
    navigate('/chats', { state: { openSessionId: row.sessionId, openChatId: row.chatId } });
  };

  const openLead = (row: HealthListRow) => {
    window.open(row.leadUrl, '_blank', 'noopener,noreferrer');
  };

  const closeAllow = () => {
    if (allowBusy) return;
    setAllowTarget(null);
    setAllowPassword('');
    setAllowError(null);
  };

  const runFalseRedReclassify = async () => {
    setReclassifyBusy(true);
    setReclassifyNote(null);
    try {
      const res = await conversationHealthApi.reclassifyFalseRed();
      if (!res.enabled) {
        setReclassifyNote(t('conversationHealth.reclassifyDisabled'));
      } else if (!res.candidates) {
        setReclassifyNote(t('conversationHealth.reclassifyEmpty'));
      } else {
        setReclassifyNote(
          t('conversationHealth.reclassifyQueued', { count: res.enqueued }),
        );
        await queryClient.invalidateQueries({ queryKey: ['conversation-health'] });
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : t('conversationHealth.reclassifyFailed');
      setReclassifyNote(msg || t('conversationHealth.reclassifyFailed'));
    } finally {
      setReclassifyBusy(false);
    }
  };

  const submitAllow = async () => {
    if (!allowTarget) return;
    setAllowBusy(true);
    setAllowError(null);
    try {
      await conversationHealthApi.allowGreen(allowTarget.sessionId, allowTarget.chatId, allowPassword);
      setAllowTarget(null);
      setAllowPassword('');
      await queryClient.invalidateQueries({ queryKey: ['conversation-health'] });
    } catch (err) {
      const msg = err instanceof Error ? err.message : t('conversationHealth.allowFailed');
      setAllowError(msg || t('conversationHealth.allowFailed'));
    } finally {
      setAllowBusy(false);
    }
  };

  const allowDialog = allowTarget ? (
    <div className="chp-allow-backdrop" role="presentation" onClick={closeAllow}>
      <div
        className="chp-allow-dialog"
        role="dialog"
        aria-modal="true"
        aria-label={t('conversationHealth.allowTitle')}
        onClick={e => e.stopPropagation()}
      >
        <div className="chp-allow-head">
          <ShieldCheck size={18} />
          <strong>{t('conversationHealth.allowTitle')}</strong>
          <button type="button" className="chp-allow-x" onClick={closeAllow} aria-label={t('common.close')} disabled={allowBusy}>
            <X size={16} />
          </button>
        </div>
        <p className="chp-allow-copy">
          {t('conversationHealth.allowBody', { name: rowTitle(allowTarget) })}
        </p>
        <label className="chp-allow-field">
          <span>{t('conversationHealth.adminPassword')}</span>
          <input
            type="password"
            autoFocus
            autoComplete="current-password"
            value={allowPassword}
            disabled={allowBusy}
            onChange={e => setAllowPassword(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter') void submitAllow();
            }}
          />
        </label>
        {allowError ? <div className="chp-allow-error">{allowError}</div> : null}
        <div className="chp-allow-actions">
          <button type="button" className="chp-btn chp-btn--ghost" onClick={closeAllow} disabled={allowBusy}>
            {t('common.cancel')}
          </button>
          <button
            type="button"
            className="chp-btn chp-btn--allow"
            onClick={() => void submitAllow()}
            disabled={allowBusy || !allowPassword.trim()}
          >
            {allowBusy ? <Loader2 className="animate-spin" size={15} /> : <CheckCircle2 size={15} />}
            <span>{t('conversationHealth.confirmAllow')}</span>
          </button>
        </div>
      </div>
    </div>
  ) : null;

  if (summaryQ.isError) {
    return (
      <section className={`chp ${compact ? 'chp-compact' : ''}`} aria-label={t('conversationHealth.title')}>
        <div className="chp-empty chp-empty--error">
          <p>{t('conversationHealth.loadError')}</p>
          <button type="button" className="chp-btn chp-btn--ghost" onClick={() => void summaryQ.refetch()}>
            <RefreshCw size={15} />
            <span>{t('common.retry')}</span>
          </button>
        </div>
      </section>
    );
  }

  if (activeColour) {
    const rows = listQ.data ?? [];
    return (
      <section className={`chp chp-list-view ${compact ? 'chp-compact' : ''}`} aria-label={t('conversationHealth.title')}>
        <div className="chp-list-toolbar">
          <button type="button" className="chp-back" onClick={() => setActiveColour(null)}>
            <ArrowLeft size={16} />
            <span>{t('common.back')}</span>
          </button>
          <div className="chp-list-title">
            <span className="chp-dot" style={{ background: COLOUR_DOT[activeColour] }} aria-hidden />
            <div>
              <strong>{COLOUR_LABEL[activeColour]}</strong>
              <span>
                {listQ.isLoading
                  ? t('conversationHealth.loading')
                  : t('conversationHealth.countLabel', { count: rows.length })}
              </span>
            </div>
          </div>
        </div>
        <p className="chp-hint">{COLOUR_MEANING[activeColour]}</p>
        {activeColour === 'red' ? (
          <p className="chp-hint chp-hint--warn">{t('conversationHealth.redAllowHint')}</p>
        ) : null}

        <div className="chp-list">
          {listQ.isLoading && (
            <div className="chp-empty">
              <Loader2 className="animate-spin" size={22} />
              <span>{t('conversationHealth.loading')}</span>
            </div>
          )}
          {listQ.isError && (
            <div className="chp-empty chp-empty--error">
              <p>{t('conversationHealth.loadError')}</p>
              <button type="button" className="chp-btn chp-btn--ghost" onClick={() => void listQ.refetch()}>
                <RefreshCw size={15} />
                <span>{t('common.retry')}</span>
              </button>
            </div>
          )}
          {!listQ.isLoading && !listQ.isError && rows.length === 0 && (
            <div className="chp-empty">{t('conversationHealth.empty')}</div>
          )}
          {rows.map(row => {
            const title = rowTitle(row);
            const subtitle = rowSubtitle(row);
            return (
              <article key={`${row.sessionId}:${row.chatId}`} className={`chp-row ${activeColour === 'red' ? 'chp-row--red' : ''}`}>
                <div className="chp-row-avatar" aria-hidden>
                  {title.slice(0, 1).toUpperCase()}
                </div>
                <div className="chp-row-meta">
                  <strong title={title}>{title}</strong>
                  {subtitle ? <span title={subtitle}>{subtitle}</span> : null}
                </div>
                <div className="chp-row-actions">
                  {activeColour === 'red' ? (
                    <button
                      type="button"
                      className="chp-btn chp-btn--allow"
                      onClick={() => {
                        setAllowError(null);
                        setAllowPassword('');
                        setAllowTarget(row);
                      }}
                      title={t('conversationHealth.allowAsGreen')}
                    >
                      <ShieldCheck size={15} />
                      <span>{t('conversationHealth.allowAsGreen')}</span>
                    </button>
                  ) : null}
                  <button
                    type="button"
                    className="chp-btn chp-btn--primary"
                    onClick={() => openChat(row)}
                    title={t('conversationHealth.openChat')}
                  >
                    <MessageSquare size={15} />
                    <span>{t('conversationHealth.openChat')}</span>
                  </button>
                  <button
                    type="button"
                    className="chp-btn chp-btn--ghost"
                    onClick={() => openLead(row)}
                    title={t('conversationHealth.openLead')}
                    disabled={!row.leadUrl}
                  >
                    <ExternalLink size={15} />
                    <span>{t('conversationHealth.openLead')}</span>
                  </button>
                </div>
              </article>
            );
          })}
        </div>
        {allowDialog}
      </section>
    );
  }

  return (
    <section className={`chp ${compact ? 'chp-compact' : ''}`} aria-label={t('conversationHealth.title')}>
      {!compact && (
        <div className="chp-header">
          <h2>{t('conversationHealth.title')}</h2>
          <span className="chp-subtitle">{t('conversationHealth.subtitle')}</span>
        </div>
      )}
      <p className="chp-hint">{t('conversationHealth.pickColour')}</p>
      <div className="chp-toolbar">
        <button
          type="button"
          className="chp-btn chp-btn--ghost"
          onClick={() => void runFalseRedReclassify()}
          disabled={reclassifyBusy}
          title={t('conversationHealth.reclassifyHint')}
        >
          {reclassifyBusy ? <Loader2 className="animate-spin" size={15} /> : <RefreshCw size={15} />}
          <span>{t('conversationHealth.reclassifyFalseRed')}</span>
        </button>
        {reclassifyNote ? <span className="chp-toolbar-note">{reclassifyNote}</span> : null}
      </div>
      <ul className="chp-legend" aria-label={t('conversationHealth.legendTitle')}>
        {COLOURS.map(colour => (
          <li key={colour}>
            <span className="chp-dot" style={{ background: COLOUR_DOT[colour] }} aria-hidden />
            <span>
              <strong>{COLOUR_LABEL[colour]}</strong> — {COLOUR_MEANING[colour]}
            </span>
          </li>
        ))}
      </ul>
      <div className="chp-grid">
        {COLOURS.map(colour => {
          const count = summary ? summary[colour] : '—';
          return (
            <button
              key={colour}
              type="button"
              className={`chp-card ${COLOUR_CLASS[colour]}`}
              onClick={() => setActiveColour(colour)}
              disabled={!summary || typeof count !== 'number'}
              title={COLOUR_MEANING[colour]}
            >
              <span className="chp-card-top">
                <span className="chp-dot" style={{ background: COLOUR_DOT[colour] }} aria-hidden />
                <span className="chp-card-label">{COLOUR_LABEL[colour]}</span>
              </span>
              <span className="chp-card-value">
                {summaryQ.isLoading ? <Loader2 className="animate-spin" size={18} /> : count}
              </span>
            </button>
          );
        })}
      </div>
      {allowDialog}
    </section>
  );
}
