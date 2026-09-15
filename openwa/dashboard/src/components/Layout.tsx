import { useEffect, useRef } from 'react';
import { NavLink, Outlet } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  LayoutDashboard,
  Smartphone,
  MessageSquare,
  Webhook,
  Key,
  FileText,
  ClipboardList,
  LogOut,
  Send,
  Server,
  Sun,
  Moon,
  Monitor,
  Menu,
  X,
  SquarePen,
  UserRound,
  HeartPulse,
} from 'lucide-react';
import { useTheme } from '../hooks/useTheme';
import { type UserRole } from '../hooks/useRole';
import { AppMenuProvider, useAppMenu } from '../hooks/useAppMenu';
import { healthApi } from '../services/api';
import './Layout.css';

interface LayoutProps {
  onLogout: () => void;
  userRole: UserRole | null;
}

// A7: an agent gets Chats and nothing else. Everything else on this list is
// somebody administering the system rather than answering a customer.
const allNavItems = [
  { to: '/dashboard', icon: LayoutDashboard, key: 'dashboard' as const, adminOnly: true, core: true },
  { to: '/sessions', icon: Smartphone, key: 'sessions' as const, adminOnly: true, core: true },
  { to: '/chats', icon: MessageSquare, key: 'chats' as const, adminOnly: false, core: true },
  { to: '/api-keys', icon: Key, key: 'apiKeys' as const, adminOnly: true, core: true },
  // Advanced / upstream ops — hidden in Bitrix Linked phones embed (clutter).
  { to: '/webhooks', icon: Webhook, key: 'webhooks' as const, adminOnly: true, core: false },
  { to: '/templates', icon: ClipboardList, key: 'templates' as const, adminOnly: true, core: false },
  { to: '/message-tester', icon: Send, key: 'messageTester' as const, adminOnly: true, core: false },
  { to: '/infrastructure', icon: Server, key: 'infrastructure' as const, adminOnly: true, core: false },
  { to: '/logs', icon: FileText, key: 'logs' as const, adminOnly: true, core: false },
];

const themeIcons = { light: Sun, dark: Moon, system: Monitor };

function LayoutShell({ onLogout, userRole }: LayoutProps) {
  const { t } = useTranslation();
  const { theme, setTheme, resolvedTheme } = useTheme();
  const ThemeIcon = themeIcons[theme];
  const { menuOpen, closeMenu, toggleMenu, chatsHostsMenu, chatsActions } = useAppMenu();
  const menuRef = useRef<HTMLDivElement>(null);

  const embedded = document.documentElement.dataset.embedded === 'true';
  const navItems = allNavItems.filter(item => {
    if (item.adminOnly && userRole !== 'admin') return false;
    // In the Bitrix iframe, keep desk tools only — Webhooks/Infra/Tester are Advanced.
    if (embedded && !item.core) return false;
    return true;
  });

  // Framed agent → mark document so a7-embedded.css can trim page chrome.
  useEffect(() => {
    const embedded = document.documentElement.dataset.embedded === 'true';
    const agent = embedded && userRole !== null && userRole !== 'admin';
    if (agent) {
      document.documentElement.dataset.agentEmbed = 'true';
    } else {
      delete document.documentElement.dataset.agentEmbed;
    }
    return () => {
      delete document.documentElement.dataset.agentEmbed;
    };
  }, [userRole]);

  // Live version is unused in the dropdown shell (no brand rail). Still ping
  // health so a dead API surfaces elsewhere; keep the call for compatibility.
  useEffect(() => {
    void healthApi.check().catch(() => undefined);
  }, []);

  useEffect(() => {
    if (!menuOpen) return;
    const onDoc = (event: MouseEvent) => {
      if (menuRef.current?.contains(event.target as Node)) return;
      // Hamburger buttons set data-a7-menu-trigger so a second click toggles
      // rather than immediately re-closing from the outside-click handler.
      if (event.target instanceof Element && event.target.closest('[data-a7-menu-trigger]')) {
        return;
      }
      closeMenu();
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') closeMenu();
    };
    document.addEventListener('mousedown', onDoc);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDoc);
      document.removeEventListener('keydown', onKey);
    };
  }, [menuOpen, closeMenu]);

  useEffect(() => {
    document.body.style.overflow = menuOpen ? 'hidden' : '';
    return () => {
      document.body.style.overflow = '';
    };
  }, [menuOpen]);

  const runAndClose = (fn: () => void) => {
    closeMenu();
    fn();
  };

  return (
    <div className="layout a7-menu-shell">
      {/* Global trigger when Chats is not hosting the hamburger (other routes). */}
      {!chatsHostsMenu ? (
        <button
          type="button"
          className={`a7-app-menu-trigger ${menuOpen ? 'open' : ''}`}
          data-a7-menu-trigger
          aria-expanded={menuOpen}
          aria-controls="a7-app-menu"
          aria-label={menuOpen ? 'Close menu' : 'Open menu'}
          onClick={toggleMenu}
        >
          {menuOpen ? <X size={20} strokeWidth={2.25} /> : <Menu size={20} strokeWidth={2.25} />}
        </button>
      ) : null}

      {menuOpen ? (
        <>
          <div className="a7-app-menu-backdrop" onClick={closeMenu} aria-hidden="true" />
          <div
            id="a7-app-menu"
            className="a7-app-menu"
            ref={menuRef}
            role="menu"
            aria-label="App menu"
          >
            {chatsActions ? (
              <>
                {/* Conversation Health is admin-only — agents must not see colour monitor. */}
                {userRole === 'admin' ? (
                  <button
                    type="button"
                    className="a7-app-menu-item"
                    role="menuitem"
                    onClick={() => runAndClose(chatsActions.onOpenHealth)}
                  >
                    <HeartPulse size={18} />
                    <span>Conversation Health</span>
                  </button>
                ) : null}
                <button
                  type="button"
                  className="a7-app-menu-item"
                  role="menuitem"
                  onClick={() => runAndClose(chatsActions.onNewContact)}
                >
                  <SquarePen size={18} />
                  <span>New contact</span>
                </button>
                <button
                  type="button"
                  className="a7-app-menu-item"
                  role="menuitem"
                  onClick={() => runAndClose(chatsActions.onOpenProfile)}
                >
                  <UserRound size={18} />
                  <span>My desk</span>
                </button>
                <div className="a7-app-menu-divider" role="separator" />
              </>
            ) : null}

            {navItems.map(({ to, icon: Icon, key }) => {
              const label = t(`nav.${key}`);
              return (
                <NavLink
                  key={to}
                  to={to}
                  role="menuitem"
                  className={({ isActive }) => `a7-app-menu-item ${isActive ? 'active' : ''}`}
                  onClick={closeMenu}
                >
                  <Icon size={18} />
                  <span>{label}</span>
                </NavLink>
              );
            })}

            <div className="a7-app-menu-footer">
              {/* Embedded CRM uses the glass dark shell — Theme light fights it and blanks labels. */}
              {document.documentElement.dataset.embedded !== 'true' ? (
                <button
                  type="button"
                  className="a7-app-menu-theme"
                  onClick={() => setTheme(resolvedTheme === 'dark' ? 'light' : 'dark')}
                  title={t('theme.toggleTo', {
                    value: t(resolvedTheme === 'dark' ? 'theme.light' : 'theme.dark'),
                  })}
                >
                  <ThemeIcon size={16} />
                  <span>Theme</span>
                </button>
              ) : null}
              <button type="button" className="a7-app-menu-item a7-app-menu-logout" onClick={onLogout}>
                <LogOut size={18} />
                <span>{t('common.logout')}</span>
              </button>
            </div>
          </div>
        </>
      ) : null}

      <main className="main-content a7-full">
        <Outlet />
      </main>
    </div>
  );
}

export function Layout({ onLogout, userRole }: LayoutProps) {
  return (
    <AppMenuProvider>
      <LayoutShell onLogout={onLogout} userRole={userRole} />
    </AppMenuProvider>
  );
}
