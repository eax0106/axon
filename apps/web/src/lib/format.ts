/** Credits (1 credit = ₹1) as the API sends them, a decimal string, in Indian grouping. */
export const credits = (value: string) =>
  Number(value).toLocaleString("en-IN", { maximumFractionDigits: 2 });

const relative = new Intl.RelativeTimeFormat("en-IN", { numeric: "auto" });

/** "5 minutes ago", "yesterday". */
export function ago(iso: string, now = Date.now()) {
  const minutes = Math.round((Date.parse(iso) - now) / 60_000);
  if (Math.abs(minutes) < 60) return relative.format(minutes, "minute");
  if (Math.abs(minutes) < 1440) return relative.format(Math.round(minutes / 60), "hour");
  return relative.format(Math.round(minutes / 1440), "day");
}
