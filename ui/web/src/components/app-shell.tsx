"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Clapperboard, History, Moon, Plus, Sun } from "lucide-react";
import { useEffect, useState, useSyncExternalStore } from "react";
import { Button } from "@/components/ui/button";
import { useTheme } from "@/lib/theme";
import { api } from "@/lib/api";
import { t } from "@/i18n";
import { cn } from "@/lib/utils";

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { theme: liveTheme, toggle } = useTheme();
  // the html class is set pre-hydration; render theme-dependent bits only after mount to keep SSR and client identical
  const mounted = useSyncExternalStore(() => () => {}, () => true, () => false);
  const theme = mounted ? liveTheme : "light";
  const [backendOk, setBackendOk] = useState<boolean | null>(null);
  const s = t();

  useEffect(() => {
    let alive = true;
    const check = () => api.health().then(() => alive && setBackendOk(true)).catch(() => alive && setBackendOk(false));
    check();
    const iv = window.setInterval(check, 15000);
    return () => { alive = false; window.clearInterval(iv); };
  }, []);

  const nav = [
    { href: "/", label: s.app.nav.history, icon: History, active: pathname === "/" || pathname.startsWith("/job") },
    { href: "/new", label: s.app.nav.newVideo, icon: Plus, active: pathname.startsWith("/new") },
  ];

  return (
    <div className="flex min-h-screen flex-col">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-lg focus:bg-card focus:px-3 focus:py-2 focus:shadow-lift">
        Skip to content
      </a>
      <header className="sticky top-0 z-40 border-b border-border/70 bg-background/85 backdrop-blur supports-backdrop-filter:bg-background/70">
        <div className="mx-auto flex h-16 w-full max-w-7xl items-center gap-4 px-4 sm:px-6">
          <Link href="/" className="flex items-center gap-2.5 rounded-lg outline-none focus-visible:ring-3 focus-visible:ring-ring/50" aria-label={s.app.name}>
            <span className="grid size-9 place-items-center rounded-xl bg-brand text-brand-foreground shadow-soft">
              <Clapperboard className="size-5" aria-hidden />
            </span>
            <span className="font-display text-lg font-medium tracking-tight">{s.app.name}</span>
          </Link>
          <nav className="ml-auto flex items-center gap-1" aria-label="Main">
            {nav.map((n) => (
              <Link
                key={n.href}
                href={n.href}
                aria-current={n.active ? "page" : undefined}
                className={cn(
                  "inline-flex h-9 items-center gap-1.5 rounded-lg px-3 text-sm font-medium outline-none transition-colors focus-visible:ring-3 focus-visible:ring-ring/50",
                  n.active ? "bg-brand-soft text-foreground" : "text-muted-foreground hover:bg-muted hover:text-foreground",
                )}
              >
                <n.icon className="size-4" aria-hidden />
                <span className="hidden sm:inline">{n.label}</span>
              </Link>
            ))}
            <Button variant="ghost" size="icon" aria-label={theme === "dark" ? s.app.theme.light : s.app.theme.dark} onClick={toggle} className="ml-1 size-9 rounded-lg">
              {theme === "dark" ? <Sun className="size-4" /> : <Moon className="size-4" />}
            </Button>
          </nav>
        </div>
        {backendOk === false && (
          <div role="alert" className="border-t border-danger/30 bg-danger-soft px-4 py-2 text-center text-sm text-foreground">
            {s.app.backendDown}
          </div>
        )}
      </header>
      <main id="main" className="mx-auto w-full max-w-7xl flex-1 px-4 py-8 sm:px-6 sm:py-10">
        {children}
      </main>
      <footer className="mx-auto w-full max-w-7xl px-4 pb-8 text-xs text-muted-foreground sm:px-6">
        {s.app.name} · {s.app.tagline}
      </footer>
    </div>
  );
}
