"use client";

import { createContext, useCallback, useContext, useSyncExternalStore, type ReactNode } from "react";

type Theme = "light" | "dark";
const KEY = "dzt-ui-theme";

const listeners = new Set<() => void>();
function subscribe(cb: () => void) {
  listeners.add(cb);
  return () => { listeners.delete(cb); };
}
function getSnapshot(): Theme {
  return document.documentElement.classList.contains("dark") ? "dark" : "light";
}
function getServerSnapshot(): Theme {
  return "light";
}
function applyTheme(t: Theme) {
  document.documentElement.classList.toggle("dark", t === "dark");
  try { window.localStorage.setItem(KEY, t); } catch { /* storage blocked */ }
  listeners.forEach((l) => l());
}

const ThemeContext = createContext<{ theme: Theme; toggle: () => void; set: (t: Theme) => void }>({
  theme: "light",
  toggle: () => {},
  set: () => {},
});

/** The html class is set before hydration by `themeInitScript`; React only mirrors it. */
export function ThemeProvider({ children }: { children: ReactNode }) {
  const theme = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
  const set = useCallback((t: Theme) => applyTheme(t), []);
  const toggle = useCallback(() => applyTheme(getSnapshot() === "dark" ? "light" : "dark"), []);
  return <ThemeContext.Provider value={{ theme, toggle, set }}>{children}</ThemeContext.Provider>;
}

export function useTheme() {
  return useContext(ThemeContext);
}

/** Inline script that applies the stored theme (or ?theme=dark|light) before hydration, so there is no flash. */
export const themeInitScript = `(function(){try{var u=new URLSearchParams(location.search).get('theme');var s=u||localStorage.getItem('${KEY}');if(!s){s=matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light'}if(s==='dark'){document.documentElement.classList.add('dark')}}catch(e){}})();`;
