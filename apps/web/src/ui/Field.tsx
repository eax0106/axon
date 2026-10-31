import type { InputHTMLAttributes } from "react";

/** A labelled 48 px input in the ALTERX form style; `hint` sits under it, `error` replaces it. */
export function Field({
  label,
  hint,
  error,
  prefix,
  ...input
}: InputHTMLAttributes<HTMLInputElement> & { label: string; name: string; hint?: string; error?: string; prefix?: string }) {
  const note = error ?? hint;
  const noteId = note ? `${input.name}-note` : undefined;
  return (
    <label className="block">
      <span className="text-sm text-ink">{label}</span>
      <span
        className={`mt-1.5 flex h-12 items-center rounded-ctl border bg-surface transition-colors duration-150 focus-within:border-accent ${
          error ? "border-danger" : "border-line-accent"
        }`}
      >
        {prefix && <span className="num pl-3.5 text-ink-muted">{prefix}</span>}
        <input
          {...input}
          aria-invalid={error ? true : undefined}
          aria-describedby={noteId}
          className="h-full w-full min-w-0 bg-transparent px-3.5 text-ink-strong outline-none placeholder:text-ink-muted"
        />
      </span>
      {note && (
        <span id={noteId} className={`mt-1.5 block text-xs ${error ? "text-danger" : "text-ink-muted"}`}>
          {note}
        </span>
      )}
    </label>
  );
}

export function SubmitButton({ busy, children, busyText }: { busy: boolean; children: string; busyText: string }) {
  return (
    <button
      type="submit"
      disabled={busy}
      className="h-12 w-full rounded-ctl bg-btn font-medium text-accent-ink transition-[transform,opacity] duration-150 active:scale-[0.98] disabled:opacity-60"
    >
      {busy ? busyText : children}
    </button>
  );
}
