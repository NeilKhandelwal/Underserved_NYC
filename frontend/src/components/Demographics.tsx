import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import type { Correlation, OverlayInfo, ScatterResponse } from "../types";
import { formatValue } from "../format";

function strength(r: number): string {
  const a = Math.abs(r);
  if (a >= 0.7) return "strong";
  if (a >= 0.4) return "moderate";
  if (a >= 0.2) return "weak";
  return "very weak";
}

interface Props {
  overlays: OverlayInfo[];
  onShowOnMap: (overlayLabel: string) => void;
}

export function Demographics({ overlays, onShowOnMap }: Props) {
  const [rows, setRows] = useState<Correlation[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [scatter, setScatter] = useState<ScatterResponse | null>(null);

  useEffect(() => {
    api.correlations().then((r) => {
      setRows(r);
      if (r.length) setSelected(r[0].column);
    }).catch(console.error);
  }, []);

  useEffect(() => {
    if (!selected) return;
    setScatter(null);
    api.scatter(selected).then(setScatter).catch(console.error);
  }, [selected]);

  const overlayByColumn = useMemo(
    () => new Map(overlays.map((o) => [o.column, o])),
    [overlays],
  );

  const max = Math.max(1e-6, ...rows.map((r) => Math.abs(r.r)));
  const current = rows.find((r) => r.column === selected);

  return (
    <>
      <h2>Demographics vs. Risk Score</h2>
      <p className="sub">
        Pearson correlation (r, from −1 to +1) between each demographic /
        building-stock feature and the underservice risk score, across all NYC
        census tracts. <span style={{ color: "var(--red)" }}>Red</span> = higher
        values coincide with higher risk;{" "}
        <span style={{ color: "var(--teal)" }}>teal</span> = higher values
        coincide with lower risk. Correlation is not causation — click a row to
        see the tract-level scatterplot behind the number.
      </p>

      <div className="demo-layout">
        <div className="bars">
          {rows.map((r) => {
            const pct = (Math.abs(r.r) / max) * 100;
            const pos = r.r >= 0;
            return (
              <button
                className={`bar-row clickable ${r.column === selected ? "selected" : ""}`}
                key={r.column}
                onClick={() => setSelected(r.column)}
              >
                <div className="lbl">{r.label}</div>
                <div className="bar-track">
                  <div
                    className="bar-fill"
                    style={{ width: `${pct}%`, background: pos ? "var(--red)" : "var(--teal)" }}
                  />
                </div>
                <div className="val">{r.r >= 0 ? "+" : ""}{r.r.toFixed(3)}</div>
              </button>
            );
          })}
        </div>

        <div className="scatter-pane">
          {current && (
            <>
              <h3 style={{ margin: "0 0 2px" }}>{current.label}</h3>
              <div className="scatter-meta">
                r = {current.r >= 0 ? "+" : ""}
                {current.r.toFixed(3)} — a {strength(current.r)}{" "}
                {current.r >= 0 ? "positive" : "negative"} relationship
                {scatter ? ` across ${scatter.n.toLocaleString()} tracts` : ""}
              </div>
              {scatter ? (
                <ScatterPlot
                  scatter={scatter}
                  overlay={overlayByColumn.get(current.column) ?? null}
                />
              ) : (
                <div className="loading">Loading scatter…</div>
              )}
              {overlayByColumn.has(current.column) && (
                <button
                  className="map-link"
                  onClick={() => onShowOnMap(overlayByColumn.get(current.column)!.label)}
                >
                  View {current.label} on the map →
                </button>
              )}
            </>
          )}
        </div>
      </div>
    </>
  );
}

const W = 460;
const H = 320;
const PAD = { l: 46, r: 12, t: 10, b: 34 };

function ScatterPlot({
  scatter,
  overlay,
}: {
  scatter: ScatterResponse;
  overlay: OverlayInfo | null;
}) {
  const xs = scatter.points.map((p) => p[0]);
  const xMin = Math.min(...xs);
  const xMax = Math.max(...xs);
  const xSpan = xMax - xMin || 1;
  const sx = (x: number) => PAD.l + ((x - xMin) / xSpan) * (W - PAD.l - PAD.r);
  const sy = (y: number) => PAD.t + (1 - y / 100) * (H - PAD.t - PAD.b);

  // Least-squares fit line to make the correlation's direction visible.
  const n = scatter.points.length;
  const mx = xs.reduce((a, b) => a + b, 0) / n;
  const my = scatter.points.reduce((a, p) => a + p[1], 0) / n;
  let sxy = 0;
  let sxx = 0;
  for (const [x, y] of scatter.points) {
    sxy += (x - mx) * (y - my);
    sxx += (x - mx) * (x - mx);
  }
  const slope = sxx ? sxy / sxx : 0;
  const yAt = (x: number) => my + slope * (x - mx);

  const fmtX = (v: number) => (overlay ? formatValue(v, overlay.format) : v.toFixed(2));

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="scatter" role="img"
      aria-label={`Scatterplot of ${scatter.label} vs. risk score`}>
      <defs>
        <clipPath id="plot-area">
          <rect x={PAD.l} y={PAD.t} width={W - PAD.l - PAD.r} height={H - PAD.t - PAD.b} />
        </clipPath>
      </defs>
      {[0, 25, 50, 75, 100].map((y) => (
        <g key={y}>
          <line x1={PAD.l} x2={W - PAD.r} y1={sy(y)} y2={sy(y)} className="grid" />
          <text x={PAD.l - 6} y={sy(y) + 3} className="tick" textAnchor="end">{y}</text>
        </g>
      ))}
      {[xMin, xMin + xSpan / 2, xMax].map((x, i) => (
        <text
          key={i}
          x={sx(x)}
          y={H - PAD.b + 16}
          className="tick"
          textAnchor={i === 0 ? "start" : i === 2 ? "end" : "middle"}
        >
          {fmtX(x)}
        </text>
      ))}
      <text x={(PAD.l + W - PAD.r) / 2} y={H - 4} className="axis" textAnchor="middle">
        {scatter.label}
      </text>
      <text
        x={12} y={(PAD.t + H - PAD.b) / 2} className="axis" textAnchor="middle"
        transform={`rotate(-90 12 ${(PAD.t + H - PAD.b) / 2})`}
      >
        Risk Score
      </text>
      {scatter.points.map(([x, y], i) => (
        <circle key={i} cx={sx(x)} cy={sy(y)} r={1.6} className="pt" />
      ))}
      <line
        x1={sx(xMin)} y1={sy(yAt(xMin))}
        x2={sx(xMax)} y2={sy(yAt(xMax))}
        className="fit" clipPath="url(#plot-area)"
      />
    </svg>
  );
}
