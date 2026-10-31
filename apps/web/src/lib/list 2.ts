/** Immutable list edits for the editors. */
export const move = <T>(list: T[], from: number, by: -1 | 1): T[] => {
  const to = from + by;
  if (to < 0 || to >= list.length) return list;
  const next = [...list];
  [next[from], next[to]] = [next[to] as T, next[from] as T];
  return next;
};
export const replaceAt = <T>(list: T[], i: number, item: T): T[] => list.map((x, j) => (j === i ? item : x));
export const removeAt = <T>(list: T[], i: number): T[] => list.filter((_, j) => j !== i);

/** The API's identifier rule for variable and capture names: "Budget range" -> "budget_range". */
export const identifier = (s: string) =>
  s
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^[^a-z]+|_+$/g, "")
    .slice(0, 40);
