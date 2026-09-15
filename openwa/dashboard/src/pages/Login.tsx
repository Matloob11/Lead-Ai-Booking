import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { Eye, EyeOff } from 'lucide-react';
import { GithubIcon } from '../components/GithubIcon';
import { API_BASE_URL } from '../services/api';
import './Login.css';

interface LoginProps {
  onLogin: (apiKey: string) => void;
}

/**
 * A7: exactly which origins may hand this dashboard an API key.
 *
 * Whole origins, compared with `===`. Not `includes`, not `endsWith`: a message
 * arriving from `https://localhost.attacker.com` contains "localhost", and
 * `https://wa.srv1802669.hstgr.cloud.attacker.com` contains the panel's hostname.
 * Either would have passed a substring test, and what is at stake is not a leak
 * but an injection — an attacker who can post a key here logs the agent into
 * *their* account, and every conversation the agent then opens or answers runs
 * through a WhatsApp session somebody else controls, looking entirely normal.
 *
 * `event.origin` is set by the browser, never by the sender, and is already
 * normalised to `scheme://host[:port]` — so an exact match against this set is
 * the whole check and needs no parsing.
 *
 * Framing is separately restricted by `frame-ancestors` (see A7.md), but that is
 * one control, it is configurable through the environment, and it does not cover
 * a window opened with `window.open()` — whose opener can post to it freely.
 */
const TRUSTED_KEY_ORIGINS: readonly string[] = [
  // The dashboard talking to itself.
  window.location.origin,
  // The A7 panel, which frames this and is what actually hands over the key.
  'https://wa.srv1802669.hstgr.cloud',
  // Vite's dev server, and only ever in a dev build.
  ...(import.meta.env.DEV ? ['http://localhost:5173', 'http://127.0.0.1:5173'] : []),
];

export function Login({ onLogin }: LoginProps) {
  const { t } = useTranslation();
  const [apiKey, setApiKey] = useState('');
  const [showKey, setShowKey] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    // Preserve CRM deep-link phone across the login paint (BrowserRouter mounts after auth).
    const phone = (new URLSearchParams(window.location.search).get('phone') || '').replace(/\D/g, '');
    if (phone.length >= 8) sessionStorage.setItem('openwa_open_phone', phone);

    const handleAutoLoginKey = async (key: string) => {
      if (!key || typeof key !== 'string') return;
      setIsLoading(true);
      setError('');
      try {
        const response = await fetch(`${API_BASE_URL}/auth/validate`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-API-Key': key,
          },
        });
        if (response.ok) {
          onLogin(key);
        } else {
          const errorData = await response.json().catch(() => ({}));
          setError(errorData.message || t('login.invalidKey'));
        }
      } catch {
        setError(t('login.connectionError'));
      } finally {
        setIsLoading(false);
      }
    };

    const handleMessage = (event: MessageEvent) => {
      if (!TRUSTED_KEY_ORIGINS.includes(event.origin)) return;

      if (event.data && typeof event.data === 'object') {
        const key = event.data.apiKey || (event.data.type === 'openwa_auth' ? event.data.key : null);
        if (typeof key === 'string' && key.trim()) {
          void handleAutoLoginKey(key.trim());
        }
        if (event.data.type === 'openwa_open_phone') {
          const p = String(event.data.phone || '').replace(/\D/g, '');
          if (p.length >= 8) sessionStorage.setItem('openwa_open_phone', p);
        }
      }
    };

    window.addEventListener('message', handleMessage);

    // Tell the panel we are listening. Addressed to each trusted origin in turn
    // rather than to '*': the browser delivers only to a parent whose origin
    // matches and silently drops the rest, so this says "ready" to the panel
    // without announcing it to whatever else might be holding the window.
    try {
      if (window.parent && window.parent !== window) {
        for (const origin of TRUSTED_KEY_ORIGINS) {
          window.parent.postMessage({ type: 'openwa_ready' }, origin);
        }
      }
    } catch {
      // Ignore cross-origin error on ready ping
    }

    return () => {
      window.removeEventListener('message', handleMessage);
    };
  }, [onLogin, t]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!apiKey.trim()) {
      setError(t('login.apiKeyRequired'));
      return;
    }
    setIsLoading(true);
    setError('');

    try {
      const response = await fetch(`${API_BASE_URL}/auth/validate`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-API-Key': apiKey,
        },
      });

      if (response.ok) {
        onLogin(apiKey);
      } else {
        const errorData = await response.json().catch(() => ({}));
        setError(errorData.message || t('login.invalidKey'));
      }
    } catch {
      setError(t('login.connectionError'));
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="login-container">
      <div className="login-card">
        <div className="login-logo">
          <img src="/a7-logo.png" alt="A7 Group" className="logo-icon" />
          <span className="version-info">
            {t('login.version', {
              version: __APP_VERSION__,
              // ISO date (YYYYMMDD) so the format is stable across locales/regions instead of the
              // locale-dependent toLocaleDateString() which renders differently per browser region.
              date: new Date(__BUILD_TIME__).toISOString().slice(0, 10).replace(/-/g, ''),
            })}
          </span>
        </div>

        <form onSubmit={handleSubmit} className="login-form">
          <div className="input-group">
            <label htmlFor="apiKey">{t('login.apiKey')}</label>
            <div className="input-wrapper">
              <input
                id="apiKey"
                type={showKey ? 'text' : 'password'}
                value={apiKey}
                onChange={e => setApiKey(e.target.value)}
                placeholder={t('login.apiKeyPlaceholder')}
                className={error ? 'error' : ''}
              />
              <button
                type="button"
                className="toggle-visibility"
                onClick={() => setShowKey(!showKey)}
                aria-label={showKey ? t('common.hideApiKey') : t('common.showApiKey')}
              >
                {showKey ? <EyeOff size={20} /> : <Eye size={20} />}
              </button>
            </div>
            {error && <span className="error-message">{error}</span>}
          </div>

          <button type="submit" className="connect-btn" disabled={isLoading}>
            {isLoading ? t('login.connecting') : t('login.connect')}
          </button>
        </form>

        {document.documentElement.dataset.embedded === 'true' ? (
          <p className="login-help">
            Ask a panel admin for your Linked phones key if this screen appears. Do not use a
            personal OpenWA cloud key here.
          </p>
        ) : (
          <p className="login-help">
            {t('login.help')}{' '}
            <a href="https://docs.open-wa.org" target="_blank" rel="noopener noreferrer">
              {t('login.viewDocs')}
            </a>
          </p>
        )}
      </div>

      {document.documentElement.dataset.embedded === 'true' ? null : (
        <footer className="login-footer">
          <span>{t('login.footer')}</span>
          <a
            href="https://github.com/rmyndharis/OpenWA"
            target="_blank"
            rel="noopener noreferrer"
            className="github-link"
            aria-label="GitHub"
          >
            <GithubIcon size={18} />
          </a>
        </footer>
      )}
    </div>
  );
}
