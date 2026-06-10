// Render values using the Python-style format strings the API ships in
// OverlayInfo.format ("{:.1f}", "{:+.1f}", "${:,.0f}", "{:.1%}").
export function formatValue(v: number, fmt: string): string {
  const pct = fmt.match(/\{:\.(\d)%\}/);
  if (pct) return `${(v * 100).toFixed(Number(pct[1]))}%`;
  if (fmt.includes(",")) {
    const prefix = fmt.startsWith("$") ? "$" : "";
    return `${prefix}${Math.round(v).toLocaleString()}`;
  }
  const fixed = fmt.match(/\{:(\+?)\.(\d)f\}/);
  if (fixed) {
    const s = v.toFixed(Number(fixed[2]));
    return fixed[1] === "+" && v >= 0 ? `+${s}` : s;
  }
  return String(v);
}
