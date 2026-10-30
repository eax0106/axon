import * as Dialog from "@radix-ui/react-dialog";
import { useState } from "react";
import { useNavigate } from "react-router";

import { session } from "../lib/api";
import { setTheme, useTheme } from "../lib/theme";
import { NAV } from "./nav";

type Command = { id: string; label: string; hint: string; keywords: string; run: () => void };

export function CommandPalette(props: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);

  const theme = useTheme();
  const commands: Command[] = [
    ...NAV.map((n) => ({
      id: `go:${n.to}`,
      label: n.label,
      hint: "Go to",
      keywords: n.keywords,
      run: () => navigate(n.to),
    })),
    {
      id: "theme",
      label: theme === "dark" ? "Switch to light theme" : "Switch to dark theme",
      hint: "Theme",
      keywords: "appearance light dark mode colour color",
      run: () => setTheme(theme === "dark" ? "light" : "dark"),
    },
    { id: "signout", label: "Sign out", hint: "Account", keywords: "logout log out", run: () => session.set(null) },
  ];

  const q = query.trim().toLowerCase();
  const shown = q
    ? commands.filter((c) => `${c.label} ${c.keywords}`.toLowerCase().includes(q))
    : commands;
  const index = Math.min(active, Math.max(shown.length - 1, 0));

  function run(c: Command | undefined) {
    if (!c) return;
    props.onOpenChange(false);
    c.run();
  }

  return (
    <Dialog.Root
      open={props.open}
      onOpenChange={(open) => {
        props.onOpenChange(open);
        setQuery("");
        setActive(0);
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-bg-deep/70 backdrop-blur-sm" />
        <Dialog.Content
          className="pop-in fixed top-[12vh] left-1/2 z-50 w-[min(560px,calc(100vw-32px))] -translate-x-1/2 overflow-hidden rounded-card border border-line-accent bg-surface"
          aria-describedby={undefined}
        >
          <Dialog.Title className="sr-only">Command palette</Dialog.Title>
          <input
            autoFocus
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setActive(0);
            }}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown" || e.key === "ArrowUp") {
                e.preventDefault();
                const step = e.key === "ArrowDown" ? 1 : -1;
                setActive((index + step + shown.length) % Math.max(shown.length, 1));
              } else if (e.key === "Enter") {
                e.preventDefault();
                run(shown[index]);
              }
            }}
            placeholder="Jump to a page or run a command"
            aria-label="Search commands"
            aria-controls="palette-list"
            aria-activedescendant={shown[index] ? `cmd-${shown[index].id}` : undefined}
            role="combobox"
            aria-expanded
            className="h-14 w-full border-b border-line bg-transparent px-5 text-base text-ink-strong outline-none placeholder:text-ink-muted"
          />
          <ul id="palette-list" role="listbox" className="max-h-80 overflow-y-auto p-2">
            {shown.map((c, i) => (
              <li
                key={c.id}
                id={`cmd-${c.id}`}
                role="option"
                aria-selected={i === index}
                onMouseMove={() => setActive(i)}
                onClick={() => run(c)}
                className="flex cursor-pointer items-center justify-between rounded-ctl px-3 py-2.5 text-sm text-ink transition-colors duration-150 aria-selected:bg-accent-soft aria-selected:text-ink-strong"
              >
                {c.label}
                <span className="text-xs text-ink-muted">{c.hint}</span>
              </li>
            ))}
            {shown.length === 0 && (
              <li className="px-3 py-6 text-center text-sm text-ink-muted">Nothing matches "{query}"</li>
            )}
          </ul>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
