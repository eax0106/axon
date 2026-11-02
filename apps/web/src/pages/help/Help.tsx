import { useState } from "react";
import { Link, Navigate, useParams } from "react-router";

import { ARTICLES } from "./articles";

const GROUPS = [...new Set(ARTICLES.map((a) => a.group))];

export default function Help() {
  const { slug } = useParams();
  return slug ? <Article slug={slug} /> : <Index />;
}

function Index() {
  const [q, setQ] = useState("");
  const term = q.trim().toLowerCase();
  const shown = ARTICLES.filter((a) => `${a.title} ${a.summary} ${a.keywords}`.toLowerCase().includes(term));
  return (
    <>
      <p className="eyebrow">Help</p>
      <h1 className="display mt-3 text-4xl">How Axon works</h1>
      <p className="mt-2 max-w-xl text-ink-muted">Short answers, and step-by-step guides for every way leads reach your employees.</p>
      <input type="search" aria-label="Search help" placeholder="Search: Zapier, credits, do not call…" value={q} onChange={(e) => setQ(e.target.value)}
        className="mt-8 h-12 w-full max-w-lg rounded-ctl border border-line-accent bg-surface px-4 text-ink-strong outline-none placeholder:text-ink-muted focus:border-accent" />
      <div className="mt-10 space-y-10">
        {GROUPS.map((g) => {
          const items = shown.filter((a) => a.group === g);
          return items.length === 0 ? null : (
            <section key={g} aria-label={g}>
              <h2 className="eyebrow">{g}</h2>
              <ul className="mt-3 grid gap-px overflow-hidden rounded-card border border-line bg-line sm:grid-cols-2 lg:grid-cols-3">
                {items.map((a) => (
                  <li key={a.slug} className="bg-surface">
                    <Link to={`/help/${a.slug}`} className="block h-full p-5 transition-colors duration-150 hover:bg-accent-soft">
                      <span className="block text-ink-strong">{a.title}</span>
                      <span className="mt-1 block text-sm text-ink-muted">{a.summary}</span>
                    </Link>
                  </li>
                ))}
              </ul>
            </section>
          );
        })}
        {shown.length === 0 && <p className="text-ink-muted">Nothing matches "{q}". <Link to="/support" className="text-accent underline">Ask the team</Link>.</p>}
      </div>
    </>
  );
}

function Article({ slug }: { slug: string }) {
  const a = ARTICLES.find((x) => x.slug === slug);
  if (!a) return <Navigate to="/help" replace />;
  const related = ARTICLES.filter((x) => x.group === a.group && x.slug !== a.slug);
  return (
    <div className="grid gap-12 lg:grid-cols-[1fr_14rem]">
      <article className="min-w-0 max-w-2xl">
        <Link to="/help" className="text-sm text-ink-muted hover:text-accent">← Help</Link>
        <p className="eyebrow mt-6">{a.group}</p>
        <h1 className="display mt-3 text-3xl">{a.title}</h1>
        <div className="mt-6 leading-relaxed text-ink">{a.body()}</div>
        <p className="mt-10 border-t border-line pt-6 text-sm text-ink-muted">Still stuck? <Link to="/support" className="text-accent underline">Write to the Axon team</Link>.</p>
      </article>
      {related.length > 0 && (
        <nav aria-label={`More in ${a.group}`} className="text-sm">
          <p className="eyebrow">More in {a.group}</p>
          <ul className="mt-3 space-y-2">{related.map((r) => <li key={r.slug}><Link to={`/help/${r.slug}`} className="text-ink-muted hover:text-accent">{r.title}</Link></li>)}</ul>
        </nav>
      )}
    </div>
  );
}
