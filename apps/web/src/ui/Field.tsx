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

/** A labelled native select in the same style as Field. */
export function Select(props: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: [string, string][];
  hint?: string;
}) {
  return (
    <label className="block">
      <span className="text-sm text-ink">{props.label}</span>
      <select
        value={props.value}
        onChange={(e) => props.onChange(e.target.value)}
        className="mt-1.5 h-12 w-full rounded-ctl border border-line-accent bg-surface px-3 text-ink-strong outline-none focus:border-accent"
      >
        {props.options.map(([v, l]) => (
          <option key={v} value={v}>
            {l}
          </option>
        ))}
      </select>
      {props.hint && <span className="mt-1.5 block text-xs text-ink-muted">{props.hint}</span>}
    </label>
  );
}
