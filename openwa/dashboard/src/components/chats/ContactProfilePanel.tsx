import { useEffect, useRef, useState } from 'react';
import {
  Archive,
  Ban,
  Check,
  Copy,
  ExternalLink,
  FileText,
  Image as ImageIcon,
  Loader2,
  Mail,
  Music,
  Pin,
  Video,
  X,
} from 'lucide-react';
import {
  chatProfileApi,
  contactApi,
  sessionApi,
  type Chat,
  type ChatProfileMediaItem,
  type ChatProfileView,
  type Session,
} from '../../services/api';
import { formatPhoneForDisplay } from '../../utils/formatPhone';
import { useToast } from '../../hooks/useToast';

/**
 * Contact card beside the open thread — WhatsApp-style profile drawer:
 * hero identity, quick actions (pin / archive / unread / block), blur-save
 * name/notes, media grid, Bitrix lead, activity.
 * Team-local fields only; the customer never sees them.
 */

interface ContactProfilePanelProps {
  session: Session | null;
  sessionId: string;
  chat: Chat;
  pictureUrl?: string | null;
  phoneText?: string | null;
  onClose: () => void;
  onDisplayNameSaved: (chatId: string, displayName: string | null) => void;
  onPinnedChange?: (chatId: string, pinned: boolean) => void;
  onArchived?: (chatId: string) => void;
  onOpenMedia?: (messageId: string) => void;
}

function initials(label: string): string {
  const parts = label.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return '?';
  if (parts.length === 1) return parts[0]!.slice(0, 2).toUpperCase();
  return `${parts[0]![0] ?? ''}${parts[1]![0] ?? ''}`.toUpperCase();
}

function mediaIcon(type: string) {
  if (type === 'image' || type === 'sticker') return <ImageIcon size={18} />;
  if (type === 'video') return <Video size={18} />;
  if (type === 'audio' || type === 'voice') return <Music size={18} />;
  return <FileText size={18} />;
}

function healthColourLabel(colour: string | null | undefined): string {
  const key = String(colour || '').toLowerCase();
  if (key === 'yellow') return 'Amber';
  if (key === 'white') return 'Hot';
  if (key === 'red') return 'Red';
  if (key === 'pink') return 'Pink';
  if (key === 'green') return 'Green';
  return colour ? colour.toUpperCase() : '';
}

function ContactProfilePanel({
  session,
  sessionId,
  chat,
  pictureUrl,
  phoneText,
  onClose,
  onDisplayNameSaved,
  onPinnedChange,
  onArchived,
  onOpenMedia,
}: ContactProfilePanelProps) {
  const { error: showError, success: showSuccess } = useToast();
  const [data, setData] = useState<ChatProfileView | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [notes, setNotes] = useState('');
  const [savedFlash, setSavedFlash] = useState('');
  const [fieldError, setFieldError] = useState('');
  const [saving, setSaving] = useState(false);
  const [blocking, setBlocking] = useState(false);
  const [blocked, setBlocked] = useState(false);
  const [pinned, setPinned] = useState(false);
  const [busyAction, setBusyAction] = useState('');
  const [copied, setCopied] = useState(false);
  const nameRef = useRef<HTMLInputElement>(null);
  const panelRef = useRef<HTMLElement>(null);

  useEffect(() => {
    let live = true;
    setLoading(true);
    setLoadError('');
    setFieldError('');
    setSavedFlash('');
    void chatProfileApi
      .get(sessionId, chat.id)
      .then(view => {
        if (!live) return;
        setData(view);
        setDisplayName(view.displayName || '');
        setNotes(view.notes || '');
        setPinned(Boolean(view.pinned));
      })
      .catch(err => {
        if (!live) return;
        setLoadError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (live) setLoading(false);
      });
    return () => {
      live = false;
    };
  }, [sessionId, chat.id]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey, true);
    return () => document.removeEventListener('keydown', onKey, true);
  }, [onClose]);

  const title =
    displayName.trim() ||
    data?.displayName ||
    chat.name ||
    data?.waName ||
    chat.id.split('@')[0] ||
    chat.id;

  const phoneLine =
    phoneText ||
    (data?.phone ? formatPhoneForDisplay(data.phone) || data.phone : null) ||
    (chat.kind === 'individual' ? null : chat.isGroup ? 'Group' : 'Private contact');

  const waHint = (data?.waName || chat.name || '').trim();
  const namePlaceholder = waHint || 'Type a team name…';
  const digitsForCopy = (data?.phone || phoneText || '').replace(/[^\d+]/g, '');

  async function saveIfChanged() {
    if (!data || saving) return;
    const nextName = displayName.trim();
    const nextNotes = notes;
    const prevName = (data.displayName || '').trim();
    const prevNotes = data.notes || '';
    if (nextName === prevName && nextNotes === prevNotes) return;

    setSaving(true);
    setSavedFlash('');
    setFieldError('');
    try {
      const fresh = await chatProfileApi.patch(sessionId, chat.id, {
        displayName: nextName,
        notes: nextNotes,
      });
      setData(fresh);
      setDisplayName(fresh.displayName || '');
      setNotes(fresh.notes || '');
      setPinned(Boolean(fresh.pinned));
      setSavedFlash('Saved');
      onDisplayNameSaved(chat.id, fresh.displayName);
      window.setTimeout(() => setSavedFlash(''), 1600);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setFieldError(msg);
      showError('Could not save profile', msg);
    } finally {
      setSaving(false);
    }
  }

  function clearName() {
    setDisplayName('');
    window.setTimeout(() => nameRef.current?.focus(), 0);
  }

  async function togglePin() {
    if (busyAction) return;
    const next = !pinned;
    setBusyAction('pin');
    try {
      const fresh = await chatProfileApi.patch(sessionId, chat.id, { pinned: next });
      setData(fresh);
      setPinned(Boolean(fresh.pinned));
      onPinnedChange?.(chat.id, Boolean(fresh.pinned));
      showSuccess(next ? 'Chat pinned' : 'Chat unpinned');
    } catch (err) {
      showError('Could not update pin', err instanceof Error ? err.message : String(err));
    } finally {
      setBusyAction('');
    }
  }

  async function archiveChat() {
    if (busyAction) return;
    const label = displayName || phoneLine || chat.id;
    if (!window.confirm(`Archive ${label}? It will leave the main chat list on this linked phone.`)) {
      return;
    }
    setBusyAction('archive');
    try {
      const res = await sessionApi.archiveChat(sessionId, chat.id, true);
      if (!res.success) {
        showError('Could not archive', 'WhatsApp could not archive this chat (needs recent history).');
        return;
      }
      showSuccess('Chat archived');
      onArchived?.(chat.id);
      onClose();
    } catch (err) {
      showError('Could not archive', err instanceof Error ? err.message : String(err));
    } finally {
      setBusyAction('');
    }
  }

  async function markUnread() {
    if (busyAction) return;
    setBusyAction('unread');
    try {
      const res = await sessionApi.markChatUnread(sessionId, chat.id);
      if (!res.success) {
        showError('Could not mark unread', 'WhatsApp declined this chat.');
        return;
      }
      showSuccess('Marked as unread');
    } catch (err) {
      showError('Could not mark unread', err instanceof Error ? err.message : String(err));
    } finally {
      setBusyAction('');
    }
  }

  async function copyPhone() {
    if (!digitsForCopy) return;
    try {
      await navigator.clipboard.writeText(digitsForCopy.startsWith('+') ? digitsForCopy : `+${digitsForCopy}`);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1400);
    } catch {
      showError('Could not copy', 'Clipboard is not available here.');
    }
  }

  async function toggleBlock(block: boolean) {
    if (blocking) return;
    setBlocking(true);
    try {
      if (block) await contactApi.block(sessionId, chat.id);
      else await contactApi.unblock(sessionId, chat.id);
      setBlocked(block);
      showSuccess(block ? 'Contact blocked' : 'Contact unblocked');
    } catch (err) {
      showError(
        block ? 'Could not block' : 'Could not unblock',
        err instanceof Error ? err.message : String(err),
      );
    } finally {
      setBlocking(false);
    }
  }

  const media = data?.media ?? [];
  const images = media.filter(m => m.type === 'image' || m.type === 'sticker' || m.type === 'video');
  const files = media.filter(m => m.type !== 'image' && m.type !== 'sticker' && m.type !== 'video');

  return (
    <>
      <button
        type="button"
        className="a7-cp__backdrop"
        aria-label="Close contact panel"
        onClick={onClose}
      />
      <aside
        ref={panelRef}
        className="a7-cp"
        role="dialog"
        aria-modal="true"
        aria-label="Contact"
        onClick={e => e.stopPropagation()}
      >
        <header className="a7-cp__head">
          <div className="a7-cp__head-title">Contact info</div>
          <button type="button" className="a7-cp__x" onClick={onClose} aria-label="Close">
            <X size={18} />
          </button>
        </header>

        <div className="a7-cp__body">
          {loading ? (
            <div className="a7-cp__hint">
              <Loader2 size={16} className="a7-cp__spin" /> Loading…
            </div>
          ) : loadError ? (
            <div className="a7-cp__alert">{loadError}</div>
          ) : (
            <>
              <div className="a7-cp__hero">
                <div className="a7-cp__avatar a7-cp__avatar--lg">
                  {pictureUrl ? <img src={pictureUrl} alt="" /> : <span>{initials(title)}</span>}
                </div>
                <div className="a7-cp__hero-name">{title}</div>
                {phoneLine ? (
                  <button type="button" className="a7-cp__hero-phone" onClick={() => void copyPhone()} title="Copy number">
                    {phoneLine}
                    {digitsForCopy ? (copied ? <Check size={13} /> : <Copy size={13} />) : null}
                  </button>
                ) : null}
                {data?.waName && data.waName !== title ? (
                  <div className="a7-cp__wa-name">WhatsApp · {data.waName}</div>
                ) : null}
              </div>

              <div className="a7-cp__quick">
                <button
                  type="button"
                  className={`a7-cp__quick-btn${pinned ? ' is-on' : ''}`}
                  disabled={Boolean(busyAction)}
                  onClick={() => void togglePin()}
                >
                  <Pin size={18} />
                  <span>{pinned ? 'Unpin' : 'Pin'}</span>
                </button>
                <button
                  type="button"
                  className="a7-cp__quick-btn"
                  disabled={Boolean(busyAction)}
                  onClick={() => void archiveChat()}
                >
                  <Archive size={18} />
                  <span>Archive</span>
                </button>
                <button
                  type="button"
                  className="a7-cp__quick-btn"
                  disabled={Boolean(busyAction)}
                  onClick={() => void markUnread()}
                >
                  <Mail size={18} />
                  <span>Unread</span>
                </button>
                {!chat.isGroup ? (
                  blocked ? (
                    <button
                      type="button"
                      className="a7-cp__quick-btn"
                      disabled={blocking}
                      onClick={() => void toggleBlock(false)}
                    >
                      <Ban size={18} />
                      <span>Unblock</span>
                    </button>
                  ) : (
                    <button
                      type="button"
                      className="a7-cp__quick-btn a7-cp__quick-btn--danger"
                      disabled={blocking}
                      onClick={() => {
                        const label = displayName || phoneText || chat.id;
                        if (
                          !window.confirm(
                            `Block ${label}? They will not be able to message this WhatsApp number until you unblock them.`,
                          )
                        ) {
                          return;
                        }
                        void toggleBlock(true);
                      }}
                    >
                      <Ban size={18} />
                      <span>Block</span>
                    </button>
                  )
                ) : null}
              </div>

              <section className="a7-cp__block">
                <h3 className="a7-cp__block-title">
                  Name and notes
                  {saving ? (
                    <span className="a7-cp__status a7-cp__status--muted">Saving…</span>
                  ) : savedFlash ? (
                    <span className="a7-cp__status a7-cp__status--ok">{savedFlash}</span>
                  ) : null}
                </h3>

                <label className="a7-cp__field">
                  <span className="a7-cp__field-label">
                    Team name
                    {data?.displayName ? (
                      <span className="a7-cp__field-hint">Current: {data.displayName}</span>
                    ) : waHint ? (
                      <span className="a7-cp__field-hint">From WhatsApp: {waHint}</span>
                    ) : null}
                  </span>
                  <div className="a7-cp__input-wrap">
                    <input
                      ref={nameRef}
                      className="a7-cp__input a7-cp__input--with-clear"
                      type="text"
                      value={displayName}
                      maxLength={255}
                      placeholder={namePlaceholder}
                      aria-label="Team name"
                      onChange={e => {
                        setDisplayName(e.target.value);
                        if (fieldError) setFieldError('');
                      }}
                      onBlur={() => void saveIfChanged()}
                      onKeyDown={e => {
                        if (e.key === 'Enter') (e.target as HTMLInputElement).blur();
                      }}
                    />
                    {displayName ? (
                      <button
                        type="button"
                        className="a7-cp__clear"
                        aria-label="Clear name"
                        title="Clear name"
                        onMouseDown={e => e.preventDefault()}
                        onClick={clearName}
                      >
                        <X size={14} />
                      </button>
                    ) : null}
                  </div>
                </label>

                <label className="a7-cp__field">
                  <span className="a7-cp__field-label">Notes</span>
                  <textarea
                    className="a7-cp__input a7-cp__notes"
                    rows={4}
                    value={notes}
                    placeholder="What has been agreed, what they are looking for, budget…"
                    onChange={e => {
                      setNotes(e.target.value);
                      if (fieldError) setFieldError('');
                    }}
                    onBlur={() => void saveIfChanged()}
                  />
                </label>

                {fieldError ? <div className="a7-cp__field-error">{fieldError}</div> : null}
                <div className="a7-cp__note">Only your team sees this. The customer never does.</div>
              </section>

              <section className="a7-cp__block">
                <h3 className="a7-cp__block-title">
                  Media
                  {media.length > 0 ? <span className="a7-cp__count">{media.length}</span> : null}
                </h3>
                {media.length === 0 ? (
                  <div className="a7-cp__note">No photos, videos, or files in this chat yet.</div>
                ) : (
                  <>
                    {images.length > 0 ? (
                      <div className="a7-cp__grid">
                        {images.map((item: ChatProfileMediaItem) => (
                          <button
                            key={item.id}
                            type="button"
                            className={`a7-cp__tile a7-cp__tile--${item.type}`}
                            title={item.type}
                            disabled={!onOpenMedia}
                            onClick={() => onOpenMedia?.(item.id)}
                          >
                            {mediaIcon(item.type)}
                            <span>{item.type}</span>
                          </button>
                        ))}
                      </div>
                    ) : null}
                    {files.length > 0 ? (
                      <div className="a7-cp__files">
                        {files.map((item: ChatProfileMediaItem) => (
                          <button
                            key={item.id}
                            type="button"
                            className="a7-cp__file"
                            disabled={!onOpenMedia}
                            onClick={() => onOpenMedia?.(item.id)}
                          >
                            {mediaIcon(item.type)}
                            <span>{item.type}</span>
                          </button>
                        ))}
                      </div>
                    ) : null}
                  </>
                )}
              </section>

              <section className="a7-cp__block">
                <h3 className="a7-cp__block-title">Handled by</h3>
                <div className="a7-cp__row">
                  <span className="a7-cp__row-label">Our number</span>
                  <span className="a7-cp__row-value">
                    {session?.name || data?.session.name || '—'}
                    {session?.phone || data?.session.phone
                      ? ` · +${session?.phone || data?.session.phone}`
                      : ''}
                  </span>
                </div>
                <div className="a7-cp__row">
                  <span className="a7-cp__row-label">Session status</span>
                  <span className="a7-cp__row-value a7-cp__pill">{session?.status || data?.session.status || '—'}</span>
                </div>
                {data?.lead ? (
                  <button
                    type="button"
                    className="a7-cp__lead"
                    onClick={() => window.open(data.lead!.leadUrl, '_blank', 'noopener,noreferrer')}
                  >
                    <ExternalLink size={14} />
                    Open Bitrix lead
                    {data.lead.colour ? ` · ${healthColourLabel(data.lead.colour)}` : ''}
                  </button>
                ) : (
                  <div className="a7-cp__note">No Bitrix lead linked for this chat yet.</div>
                )}
              </section>

              {data ? (
                <section className="a7-cp__block a7-cp__block--actions">
                  <h3 className="a7-cp__block-title">Activity</h3>
                  <div className="a7-cp__stats">
                    <div className="a7-cp__stat">
                      <b>{data.stats.total}</b>
                      <span>messages</span>
                    </div>
                    <div className="a7-cp__stat">
                      <b>{data.stats.inbound}</b>
                      <span>received</span>
                    </div>
                    <div className="a7-cp__stat">
                      <b>{data.stats.outbound}</b>
                      <span>sent</span>
                    </div>
                    {data.stats.failed > 0 ? (
                      <div className="a7-cp__stat a7-cp__stat--bad">
                        <b>{data.stats.failed}</b>
                        <span>failed</span>
                      </div>
                    ) : null}
                  </div>
                </section>
              ) : null}
            </>
          )}
        </div>
      </aside>
    </>
  );
}

export default ContactProfilePanel;
