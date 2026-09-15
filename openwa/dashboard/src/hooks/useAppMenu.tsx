import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react';

/** Actions Chats registers so the app dropdown can open its modals. */
export interface ChatsMenuActions {
  onNewContact: () => void;
  onOpenProfile: () => void;
  onOpenHealth: () => void;
}

interface AppMenuContextValue {
  menuOpen: boolean;
  openMenu: () => void;
  closeMenu: () => void;
  toggleMenu: () => void;
  /** True while Chats mounts its own hamburger (hide the global FAB). */
  chatsHostsMenu: boolean;
  setChatsHostsMenu: (hosted: boolean) => void;
  chatsActions: ChatsMenuActions | null;
  registerChatsActions: (actions: ChatsMenuActions | null) => void;
}

const AppMenuContext = createContext<AppMenuContextValue | null>(null);

export function AppMenuProvider({ children }: { children: ReactNode }) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [chatsHostsMenu, setChatsHostsMenu] = useState(false);
  const [chatsActions, setChatsActions] = useState<ChatsMenuActions | null>(null);

  const openMenu = useCallback(() => setMenuOpen(true), []);
  const closeMenu = useCallback(() => setMenuOpen(false), []);
  const toggleMenu = useCallback(() => setMenuOpen(open => !open), []);
  const registerChatsActions = useCallback((actions: ChatsMenuActions | null) => {
    setChatsActions(actions);
  }, []);

  const value = useMemo(
    () => ({
      menuOpen,
      openMenu,
      closeMenu,
      toggleMenu,
      chatsHostsMenu,
      setChatsHostsMenu,
      chatsActions,
      registerChatsActions,
    }),
    [
      menuOpen,
      openMenu,
      closeMenu,
      toggleMenu,
      chatsHostsMenu,
      chatsActions,
      registerChatsActions,
    ],
  );

  return <AppMenuContext.Provider value={value}>{children}</AppMenuContext.Provider>;
}

export function useAppMenu(): AppMenuContextValue {
  const ctx = useContext(AppMenuContext);
  if (!ctx) {
    throw new Error('useAppMenu must be used within AppMenuProvider');
  }
  return ctx;
}
