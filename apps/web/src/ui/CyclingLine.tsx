import { useEffect, useState } from "react";

/** The site's cycling headline: a fixed lead, then a mint phrase that rebuilds letter by letter.
 *  Screen readers get one full sentence; reduced motion keeps the first phrase still. */
export function CyclingLine({ lead, words, sentence }: { lead: string; words: readonly string[]; sentence: string }) {
  const [index, setIndex] = useState(0);
  useEffect(() => {
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const id = setInterval(() => setIndex((i) => (i + 1) % words.length), 2800);
    return () => clearInterval(id);
  }, [words.length]);
  return (
    <>
      <span className="sr-only">{sentence}</span>
      <span aria-hidden>{lead} </span>
      <span key={index} aria-hidden className="text-accent">
        {/* Letters sit in a no-wrap box per word, so a line breaks only between words. */}
        {(words[index] ?? "").split(" ").map((word, w, all) => {
          const start = all.slice(0, w).join(" ").length + (w ? 1 : 0);
          return (
            <span key={w}>
              {w > 0 && " "}
              <span className="inline-block whitespace-nowrap">
                {[...word].map((ch, i) => (
                  <span key={i} className="letter-in inline-block" style={{ animationDelay: `${(start + i) * 24}ms` }}>
                    {ch}
                  </span>
                ))}
              </span>
            </span>
          );
        })}
      </span>
    </>
  );
}
