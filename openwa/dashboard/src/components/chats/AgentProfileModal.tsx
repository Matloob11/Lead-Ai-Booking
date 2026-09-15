import { useEffect, useState } from 'react';
import { Loader2, X } from 'lucide-react';
import { API_BASE_URL, type Session } from '../../services/api';

/**
 * A7: the agent's own number, and what it has done today.
 *
 * Shaped after `backend/apps/reports/views.py` on the WABA side, which answers
 * the same four questions — how much came in, how much went out, how much
 * failed, and what the week looks like — so an agent moving between the two
 * panels reads the same figures in the same order.
 *
 * It asks `/stats/sessions/:id` rather than `/stats/overview`. The global routes
 * aggregate across every session and are ADMIN-only for exactly that reason; an
 * agent calling one gets a 403, and an agent is who this screen is for. The
 * per-session route carries a session id, so the gateway's own `allowedSessions`
 * fence already scopes it to phones this key holds.
 */

interface SessionStats {
  session: { id: string; name: string; status: string };
  messages: { sent: number; received: number; today: number; failed: number };
  topChats: Array<{ chatId: string; chatName: string | null; count: number; lastActive: string }>;
  hourlyActivity: Array<{ hour: number; sent: number; received: number }>;
}

interface AgentProfileModalProps {
  session: Session;
  /** Chats currently in this agent's list — the panel already has them loaded. */
  openChats: number;
  onClose: () => void;
}

const digitsOf = (value: string) => value.replace(/\D/g, '');

function AgentProfileModal({ session, openChats, onClose }: AgentProfileModalProps) {
  const [stats, setStats] = useState<SessionStats | null>(null);
  const [problem, setProblem] = useState('');

  useEffect(() => {
    let live = true;

    // Fetched here rather than through services/api.ts: this route has no client
    // there, and services/api.ts is upstream's file — a new export in it is a
    // line of merge conflict for one caller. API_BASE_URL and the key's storage
    // are the two things borrowed, and both are already public.
    const load = async () => {
      try {
        const key = sessionStorage.getItem('openwa_api_key');
        const response = await fetch(`${API_BASE_URL}/stats/sessions/${encodeURIComponent(session.id)}`, {
          headers: key ? { 'X-API-Key': key } : {},
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const body = (await response.json()) as SessionStats;
        if (live) setStats(body);
      } catch (error) {
        if (live) setProblem(error instanceof Error ? error.message : String(error));
      }
    };

    void load();
    return () => {
      live = false;
    };
  }, [session.id]);

  const hourly = stats?.hourlyActivity ?? [];
  // One scale for both series, so the two bars in an hour can be compared with
  // each other and with the hour beside them.
  const busiest = hourly.reduce((most, h) => Math.max(most, h.sent + h.received), 0) || 1;

  return (
    <div className="a7-modal" role="dialog" aria-modal="true" aria-label="My desk">
      <div className="a7-modal__box">
        <div className="a7-modal__head">
          <h2>My desk</h2>
          <button type="button" className="a7-modal__x" onClick={onClose} aria-label="Close">
            <X size={18} />
          </button>
        </div>

        <div className="a7-modal__body">
          <div className="a7-prof__who">
            <div className="a7-prof__name">{session.name}</div>
            <div className="a7-prof__num">
              {session.phone ? `+${digitsOf(session.phone)}` : 'No number linked yet'}
            </div>
            <div className={`a7-prof__state is-${session.status}`}>{session.status.replace(/_/g, ' ')}</div>
          </div>

          {problem && <div className="a7-alert">Could not load the figures: {problem}</div>}
          {!stats && !problem && (
            <div className="a7-prof__loading">
              <Loader2 size={16} className="spin" /> Loading your figures…
            </div>
          )}

          {stats && (
            <>
              <div className="a7-prof__grid">
                <div className="a7-prof__fig">
                  <div className="a7-prof__val">{stats.messages.today.toLocaleString()}</div>
                  <div className="a7-prof__lbl">Messages today</div>
                </div>
                <div className="a7-prof__fig">
                  <div className="a7-prof__val">{stats.messages.received.toLocaleString()}</div>
                  <div className="a7-prof__lbl">Received, all time</div>
                </div>
                <div className="a7-prof__fig">
                  <div className="a7-prof__val">{stats.messages.sent.toLocaleString()}</div>
                  <div className="a7-prof__lbl">Sent, all time</div>
                </div>
                <div className="a7-prof__fig">
                  <div className="a7-prof__val">{openChats.toLocaleString()}</div>
                  <div className="a7-prof__lbl">Chats open</div>
                </div>
                <div className={`a7-prof__fig ${stats.messages.failed ? 'is-bad' : ''}`}>
                  <div className="a7-prof__val">{stats.messages.failed.toLocaleString()}</div>
                  <div className="a7-prof__lbl">Sends that failed</div>
                </div>
              </div>

              {hourly.length > 0 && (
                <div className="a7-prof__section">
                  <div className="a7-prof__label">Today, hour by hour</div>
                  <div className="a7-prof__hours">
                    {hourly.map(h => (
                      <div
                        key={h.hour}
                        className="a7-prof__hour"
                        title={`${String(h.hour).padStart(2, '0')}:00 — ${h.received} in, ${h.sent} out`}
                      >
                        <div className="a7-prof__bar">
                          <span className="in" style={{ height: `${(h.received / busiest) * 100}%` }} />
                          <span className="out" style={{ height: `${(h.sent / busiest) * 100}%` }} />
                        </div>
                        {/* Every fourth hour, so the row stays readable at 800px. */}
                        <span className="a7-prof__tick">{h.hour % 4 === 0 ? h.hour : ''}</span>
                      </div>
                    ))}
                  </div>
                  <div className="a7-prof__key">
                    <span className="in" /> received <span className="out" /> sent
                  </div>
                </div>
              )}

              {stats.topChats.length > 0 && (
                <div className="a7-prof__section">
                  <div className="a7-prof__label">Busiest chats</div>
                  <div className="a7-prof__chats">
                    {stats.topChats.slice(0, 5).map(c => (
                      <div key={c.chatId} className="a7-prof__chat">
                        <span className="a7-prof__chat-name" title={c.chatName || c.chatId}>
                          {c.chatName || c.chatId.split('@')[0]}
                        </span>
                        <span className="a7-prof__chat-n">{c.count}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

export default AgentProfileModal;
