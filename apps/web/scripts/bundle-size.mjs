// First-load JavaScript of the built app: the entry chunk and every chunk it imports statically,
// gzipped. Lazy routes are not counted; they load when visited. Prints BUNDLE-OK under budget.
import { readFileSync } from "node:fs";
import { gzipSync } from "node:zlib";

const BUDGET = 150 * 1024;
const dist = new URL("../dist/", import.meta.url);
const manifest = JSON.parse(readFileSync(new URL(".vite/manifest.json", dist), "utf8"));
const seen = new Set();
const walk = (key) => {
  if (seen.has(key)) return;
  seen.add(key);
  for (const dep of manifest[key].imports ?? []) walk(dep);
};
walk(Object.keys(manifest).find((k) => manifest[k].isEntry));

let total = 0;
for (const key of seen) {
  const size = gzipSync(readFileSync(new URL(manifest[key].file, dist))).length;
  total += size;
  console.log(`${(size / 1024).toFixed(1).padStart(7)} KB  ${manifest[key].file}`);
}
console.log(`${(total / 1024).toFixed(1).padStart(7)} KB  first load (budget ${BUDGET / 1024} KB)`);
if (total > BUDGET) process.exit(1);
console.log("BUNDLE-OK");
