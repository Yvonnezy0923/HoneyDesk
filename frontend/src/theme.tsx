import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';

export type ThemeMode = 'light' | 'dark' | 'system';
export type ResolvedTheme = 'light' | 'dark';

const KEY = 'honey_theme_mode';
const VALID = ['light', 'dark', 'system'];

function readStored(): ThemeMode {
  try {
    const v = localStorage.getItem(KEY);
    return (VALID as string[]).includes(v || '') ? (v as ThemeMode) : 'light';
  } catch {
    return 'light';
  }
}

function systemTheme(): ResolvedTheme {
  try {
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  } catch {
    return 'light';
  }
}

interface ThemeCtx {
  mode: ThemeMode;
  resolved: ResolvedTheme;
  setMode: (m: ThemeMode) => void;
}

const Ctx = createContext<ThemeCtx>({
  mode: 'light',
  resolved: 'light',
  setMode: () => {},
});

export const useThemeMode = () => useContext(Ctx);

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [mode, setModeState] = useState<ThemeMode>(readStored);
  const [resolved, setResolved] = useState<ResolvedTheme>(() =>
    readStored() === 'system' ? systemTheme() : (readStored() as ResolvedTheme)
  );

  useEffect(() => {
    try {
      localStorage.setItem(KEY, mode);
    } catch {
      /* ignore */
    }
  }, [mode]);

  useEffect(() => {
    const update = () => setResolved(mode === 'system' ? systemTheme() : mode);
    update();
    if (mode !== 'system') return;
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    mq.addEventListener?.('change', update);
    return () => mq.removeEventListener?.('change', update);
  }, [mode]);

  const value = useMemo(() => ({ mode, resolved, setMode: setModeState }), [mode, resolved]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}