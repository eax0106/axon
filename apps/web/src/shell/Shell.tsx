import * as Dialog from "@radix-ui/react-dialog";
import { Suspense, useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router";

import { session } from "../lib/api";
import { useMe } from "../lib/queries";
import { setTheme, useTheme } from "../lib/theme";
import { CommandPalette } from "./CommandPalette";
import { Skeleton } from "../ui/states";
import { NAV } from "./nav";
import { Bell, CreditChip, LiveIndicator } from "./TopBar";

const isMac = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform);

export function Shell() {
  const { pathname } = useLocation();
  const [palette, setPalette] = useState(false);
  const [menu, setMenu] = useState(false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key.toLowerCase() === "k" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        setPalette((open) => !open);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    setMenu(false);
  }, [pathname]);

  return (
    <div className="min-h-dvh md:grid md:grid-cols-[232px_1fr]">
      <a
        href="#main"
        className="sr-only z-50 rounded-ctl bg-btn px-3 py-2 text-accent-ink focus:not-sr-only focus:fixed focus:top-3 focus:left-3"
      >
        Skip to content
      </a>
      <aside className="sticky top-0 hidden h-dvh flex-col border-r border-line bg-bg-deep md:flex">
        <Rail />
      </aside>

      <div className="min-w-0">
        <header className="sticky top-0 z-20 flex h-14 items-center gap-3 border-b border-line bg-bg/85 px-4 backdrop-blur-md md:px-8">
          <Dialog.Root open={menu} onOpenChange={setMenu}>
            <Dialog.Trigger
              aria-label="Open menu"
              className="grid size-8 place-items-center rounded-ctl text-ink-muted hover:text-ink-strong md:hidden"
            >
              <svg aria-hidden viewBox="0 0 20 20" className="size-5" fill="none" stroke="currentColor" strokeWidth="1.5">
                <path d="M3 6h14M3 10h14M3 14h14" />
              </svg>
            </Dialog.Trigger>
            <Dialog.Portal>
              <Dialog.Overlay className="fixed inset-0 z-40 bg-bg-deep/70 md:hidden" />
              <Dialog.Content
                aria-describedby={undefined}
                className="fixed inset-y-0 left-0 z-50 flex w-[min(280px,85vw)] flex-col border-r border-line bg-bg-deep md:hidden"
              >
                <Dialog.Title className="sr-only">Menu</Dialog.Title>
                <Rail />
              </Dialog.Content>
            </Dialog.Portal>
          </Dialog.Root>

          <button
            type="button"
            onClick={() => setPalette(true)}
            className="flex h-8 min-w-0 flex-1 items-center gap-3 rounded-ctl border border-line px-3 text-sm text-ink-muted transition-colors duration-150 hover:border-line-accent hover:text-ink sm:max-w-80"
          >
            <svg aria-hidden viewBox="0 0 20 20" className="size-4 shrink-0" fill="none" stroke="currentColor" strokeWidth="1.5">
              <circle cx="9" cy="9" r="5.5" />
              <path d="m13 13 4 4" />
            </svg>
            <span className="truncate">Jump to…</span>
            <kbd className="num ml-auto hidden text-xs sm:inline">{isMac ? "⌘K" : "Ctrl K"}</kbd>
          </button>

          <div className="ml-auto flex items-center gap-3">
            <LiveIndicator />
            <CreditChip />
            <Bell />
          </div>
        </header>

        <main id="main" key={pathname} className="page-in mx-auto max-w-6xl px-4 py-8 md:px-8 md:py-12">
          <Suspense fallback={<Skeleton className="h-10 w-64" />}>
            <Outlet />
          </Suspense>
        </main>
      </div>

      <CommandPalette open={palette} onOpenChange={setPalette} />
    </div>
  );
}

function Rail() {
  const me = useMe().data;
  const theme = useTheme();
  return (
    <>
      <div className="flex h-14 items-center gap-2.5 px-5">
        <span aria-hidden className="size-2.5 rounded-full bg-accent shadow-[0_0_12px_var(--accent)]" />
        <span className="display text-lg">Axon</span>
        <span className="text-xs text-ink-muted">by ALTERX</span>
      </div>
      <nav aria-label="Main" className="flex-1 overflow-y-auto px-3 py-4">
        <ul className="space-y-0.5">
          {NAV.map((n) => (
            <li key={n.to}>
              <NavLink
                to={n.to}
                end
                className={({ isActive }) =>
                  `flex h-9 items-center gap-3 rounded-ctl px-3 text-sm transition-colors duration-150 ${
                    isActive
                      ? "bg-accent-soft text-ink-strong"
                      : "text-ink-muted hover:bg-accent-soft hover:text-ink"
                  }`
                }
              >
                {({ isActive }) => (
                  <>
                    <span aria-hidden className={`size-1.5 rounded-full ${isActive ? "bg-accent" : "bg-line"}`} />
                    {n.label}
                  </>
                )}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>
      <div className="space-y-1 border-t border-line p-3">
        <button
          type="button"
          onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
          className="flex h-9 w-full items-center rounded-ctl px-3 text-sm text-ink-muted transition-colors duration-150 hover:bg-accent-soft hover:text-ink"
        >
          {theme === "dark" ? "Light theme" : "Dark theme"}
        </button>
        <div className="flex items-center justify-between gap-2 px-3 pt-2">
          <span className="min-w-0">
            <span className="block truncate text-sm text-ink">{me?.account.name ?? " "}</span>
            <span className="block truncate text-xs text-ink-muted">{me?.user.email ?? " "}</span>
          </span>
          <button
            type="button"
            onClick={() => session.set(null)}
            className="shrink-0 text-xs text-ink-muted transition-colors duration-150 hover:text-accent"
          >
            Sign out
          </button>
        </div>
      </div>
    </>
  );
}
