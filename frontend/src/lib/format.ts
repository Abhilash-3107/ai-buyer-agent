const usd = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 2 });
const int = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });

export const money = (n: number) => usd.format(n);
export const count = (n: number) => int.format(n);
/** 3200 -> "3.2k". */
export const compact = (n: number) => (n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n));
export const seconds = (n: number) => `${n.toFixed(n < 10 ? 1 : 0)} s`;

/** 0.047 -> "47 ms", 68.4 -> "68 s". */
export const duration = (n: number) => (n < 1 ? `${Math.round(n * 1000)} ms` : seconds(n));

export function ordinal(n: number): string {
  const s = ["th", "st", "nd", "rd"];
  const v = n % 100;
  return n + (s[(v - 20) % 10] || s[v] || s[0]);
}

export function plural(n: number, one: string, many = one + "s"): string {
  return `${count(n)} ${n === 1 ? one : many}`;
}

/** "2026-11-11 18:53" in the viewer's time zone. */
export function stamp(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

export function percent(part: number, whole: number): string {
  return whole === 0 ? "-" : `${Math.round((part / whole) * 100)}%`;
}
