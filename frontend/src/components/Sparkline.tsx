import { useMemo } from "react";

// Trend over a null-padded quarterly series: compares the first and last
// *scored* quarters (gaps ignored). Returns null when fewer than two quarters
// have data, so callers can omit the indicator entirely.
export interface Trend {
  first: number;
  last: number;
  delta: number;
  arrow: "↑" | "↓" | "→";
  firstQuarter: string;
  lastQuarter: string;
}

export function trend(quarters: string[], values: (number | null)[]): Trend | null {
  const scored = quarters
    .map((q, i) => [q, values[i]] as const)
    .filter((p): p is readonly [string, number] => p[1] != null);
  if (scored.length < 2) return null;
  const [firstQuarter, first] = scored[0];
  const [lastQuarter, last] = scored[scored.length - 1];
  const delta = last - first;
  // ±1 percentile-point dead-band so noise doesn't read as a trend.
  const arrow = delta > 1 ? "↑" : delta < -1 ? "↓" : "→";
  return { first, last, delta, arrow, firstQuarter, lastQuarter };
}

export function TrendBadge({ t }: { t: Trend }) {
  const cls = t.arrow === "↑" ? "pos" : t.arrow === "↓" ? "neg" : "flat";
  return (
    <span className={`trend-badge ${cls}`}>
      {t.arrow} {t.delta >= 0 ? "+" : ""}
      {t.delta.toFixed(1)}
    </span>
  );
}

const W = 240;
const H = 56;
const PAD = { l: 4, r: 4, t: 6, b: 6 };

interface SparklineProps {
  quarters: string[];
  values: (number | null)[];
  /** y-axis range. risk_score is [0, 100]; a residual gets a symmetric range. */
  domain: [number, number];
  /** draw a dashed reference line at this y (e.g. 0 for residuals). */
  baseline?: number;
  color?: string;
  label: string;
}

export function Sparkline({
  quarters,
  values,
  domain,
  baseline,
  color = "var(--accent)",
  label,
}: SparklineProps) {
  const [lo, hi] = domain;
  const span = hi - lo || 1;
  const innerW = W - PAD.l - PAD.r;
  const innerH = H - PAD.t - PAD.b;

  const sx = (i: number) =>
    PAD.l + (quarters.length <= 1 ? 0 : (i / (quarters.length - 1)) * innerW);
  const sy = (v: number) => PAD.t + (1 - (v - lo) / span) * innerH;

  // Break the path at gaps so null quarters leave a hole instead of a straight
  // line bridging across missing data.
  const segments = useMemo(() => {
    const out: { i: number; v: number }[][] = [];
    let run: { i: number; v: number }[] = [];
    values.forEach((v, i) => {
      if (v == null) {
        if (run.length) out.push(run);
        run = [];
      } else {
        run.push({ i, v });
      }
    });
    if (run.length) out.push(run);
    return out;
  }, [values]);

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      className="sparkline"
      role="img"
      aria-label={`${label} from ${quarters[0]} to ${quarters[quarters.length - 1]}`}
    >
      {baseline != null && baseline >= lo && baseline <= hi && (
        <line
          x1={PAD.l}
          x2={W - PAD.r}
          y1={sy(baseline)}
          y2={sy(baseline)}
          className="spark-base"
        />
      )}
      {segments.map((seg, si) => (
        <polyline
          key={si}
          fill="none"
          stroke={color}
          strokeWidth={1.75}
          strokeLinejoin="round"
          strokeLinecap="round"
          points={seg.map((p) => `${sx(p.i)},${sy(p.v)}`).join(" ")}
        />
      ))}
      {values.map((v, i) =>
        v == null ? null : (
          <circle key={i} cx={sx(i)} cy={sy(v)} r={1.9} fill={color} />
        ),
      )}
    </svg>
  );
}
