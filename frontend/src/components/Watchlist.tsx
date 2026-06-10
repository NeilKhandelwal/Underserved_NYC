import { Fragment, useEffect, useState } from "react";
import { api } from "../api";
import type {
  TractDetail,
  WatchlistDirection,
  WatchlistGroupRow,
  WatchlistRow,
} from "../types";

const BOROUGHS = ["Bronx", "Brooklyn", "Manhattan", "Queens", "Staten Island"];
const DIRECTIONS: { id: WatchlistDirection; label: string }[] = [
  { id: "neglect", label: "Most unexplained neglect (+)" },
  { id: "success", label: "Unexpected success (−)" },
  { id: "surprise", label: "Biggest surprises (|res|)" },
];
type View = "tracts" | "neighborhood" | "council_district";
const VIEWS: { id: View; label: string }[] = [
  { id: "tracts", label: "Tracts" },
  { id: "neighborhood", label: "Neighborhoods" },
  { id: "council_district", label: "Districts" },
];

// The 4 composite components shown in the drilldown (label as in DetailCard).
const COMPONENT_KEYS = new Set([
  "accountability_gap",
  "weighted_violation_rate",
  "avg_closure_time",
  "vacate_rate",
]);

function fmtIncome(v: number | null): string {
  return v != null ? `$${Math.round(v / 1000)}k` : "—";
}

function fmtResidual(v: number | null): string {
  return v != null ? `${v >= 0 ? "+" : ""}${v.toFixed(1)}` : "";
}

function ResidualBar({ value, max }: { value: number | null; max: number }) {
  if (value == null) return null;
  const pct = Math.min(100, (Math.abs(value) / (max || 1)) * 100);
  return (
    <span className="resbar">
      <span
        style={{ width: `${pct}%`, background: value >= 0 ? "var(--red)" : "var(--teal)" }}
      />
    </span>
  );
}

export function Watchlist({ onSelect }: { onSelect: (geoid: string) => void }) {
  const [view, setView] = useState<View>("tracts");
  const [direction, setDirection] = useState<WatchlistDirection>("neglect");
  const [boroughs, setBoroughs] = useState<string[]>(BOROUGHS);
  const [n, setN] = useState(20);
  const [rows, setRows] = useState<WatchlistRow[]>([]);
  const [groups, setGroups] = useState<WatchlistGroupRow[]>([]);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [details, setDetails] = useState<Record<string, TractDetail>>({});

  useEffect(() => {
    if (view === "tracts") {
      api.watchlist(direction, boroughs, n).then(setRows).catch(console.error);
    } else {
      api.watchlistGroups(view, direction, boroughs, n).then(setGroups).catch(console.error);
    }
  }, [view, direction, boroughs, n]);

  function toggleBorough(b: string) {
    setBoroughs((cur) => (cur.includes(b) ? cur.filter((x) => x !== b) : [...cur, b]));
  }

  function toggleExpand(geoid: string) {
    const next = expanded === geoid ? null : geoid;
    setExpanded(next);
    if (next && !details[next]) {
      api
        .tract(next)
        .then((d) => setDetails((cur) => ({ ...cur, [next]: d })))
        .catch(console.error);
    }
  }

  const maxAbs = Math.max(
    1e-6,
    ...(view === "tracts"
      ? rows.map((r) => Math.abs(r.risk_residual ?? 0))
      : groups.map((g) => Math.abs(g.mean_residual))),
  );

  return (
    <>
      <h2>Top Residual Outliers</h2>
      <p className="sub">
        Tracts whose risk score diverges most from what demographics predict. Positive
        residual = more underserved than poverty, race, and education alone would suggest.
        |residual| &lt; 10 is within the model's noise floor. Click a row to see it on the
        map; use the chevron to see what drives a tract.
      </p>

      <div className="controls">
        <label>
          View
          <div className="seg">
            {VIEWS.map((v) => (
              <button
                key={v.id}
                className={view === v.id ? "active" : ""}
                onClick={() => setView(v.id)}
              >
                {v.label}
              </button>
            ))}
          </div>
        </label>
        <label>
          Ranking
          <div className="seg">
            {DIRECTIONS.map((d) => (
              <button
                key={d.id}
                className={direction === d.id ? "active" : ""}
                onClick={() => setDirection(d.id)}
              >
                {d.label}
              </button>
            ))}
          </div>
        </label>
        <label>
          Show top: {n}
          <input
            type="range"
            min={10}
            max={50}
            step={5}
            value={n}
            onChange={(e) => setN(Number(e.target.value))}
          />
        </label>
        <label>
          Boroughs
          <div className="seg">
            {BOROUGHS.map((b) => (
              <button
                key={b}
                className={boroughs.includes(b) ? "active" : ""}
                onClick={() => toggleBorough(b)}
              >
                {b}
              </button>
            ))}
          </div>
        </label>
      </div>

      {view === "tracts" ? (
        <table className="data">
          <thead>
            <tr>
              <th />
              <th>Neighborhood</th>
              <th>Borough</th>
              <th className="num">District</th>
              <th className="num">Predicted → Actual</th>
              <th className="num">Income</th>
              <th className="num">Residual</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <Fragment key={r.geoid}>
                <tr onClick={() => onSelect(r.geoid)}>
                  <td className="chev">
                    <button
                      className="chev-btn"
                      aria-label="Why this tract?"
                      aria-expanded={expanded === r.geoid}
                      onClick={(e) => {
                        e.stopPropagation();
                        toggleExpand(r.geoid);
                      }}
                    >
                      {expanded === r.geoid ? "▾" : "▸"}
                    </button>
                  </td>
                  <td className="name">{r.neighborhood ?? "—"}</td>
                  <td>{r.borough}</td>
                  <td className="num">{r.council_district ?? "—"}</td>
                  <td className="num">
                    {r.predicted_risk != null && r.risk_score != null
                      ? `${r.predicted_risk.toFixed(1)} → ${r.risk_score.toFixed(1)}`
                      : r.risk_score?.toFixed(1) ?? "—"}
                  </td>
                  <td className="num">{fmtIncome(r.median_income)}</td>
                  <td className={`num ${(r.risk_residual ?? 0) >= 0 ? "pos" : "neg"}`}>
                    {fmtResidual(r.risk_residual)}
                  </td>
                  <td className="barcell">
                    <ResidualBar value={r.risk_residual} max={maxAbs} />
                  </td>
                </tr>
                {expanded === r.geoid && (
                  <tr className="drill">
                    <td colSpan={8}>
                      <Drilldown detail={details[r.geoid]} />
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      ) : (
        <table className="data">
          <thead>
            <tr>
              <th>{view === "neighborhood" ? "Neighborhood" : "Council District"}</th>
              <th>Borough</th>
              <th className="num">Tracts</th>
              <th className="num">Mean risk</th>
              <th className="num">Mean residual</th>
              <th />
              <th>Most extreme tract</th>
            </tr>
          </thead>
          <tbody>
            {groups.map((g) => (
              <tr key={g.key} onClick={() => onSelect(g.top_geoid)}>
                <td className="name">{g.key}</td>
                <td>{g.borough}</td>
                <td className="num">{g.tract_count}</td>
                <td className="num">{g.mean_risk?.toFixed(1) ?? "—"}</td>
                <td className={`num ${g.mean_residual >= 0 ? "pos" : "neg"}`}>
                  {fmtResidual(g.mean_residual)}
                </td>
                <td className="barcell">
                  <ResidualBar value={g.mean_residual} max={maxAbs} />
                </td>
                <td>
                  {g.top_neighborhood ?? g.top_geoid}{" "}
                  <span className={g.top_residual >= 0 ? "pos" : "neg"}>
                    ({fmtResidual(g.top_residual)})
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}

function Drilldown({ detail }: { detail: TractDetail | undefined }) {
  if (!detail) return <div className="loading">Loading tract detail…</div>;
  const p = detail.properties;
  const pct = (k: string) =>
    typeof p[k] === "number" ? `${((p[k] as number) * 100).toFixed(0)}%` : "—";
  const components = detail.metrics.filter((m) => COMPONENT_KEYS.has(m.key));

  return (
    <div className="drill-body">
      {detail.interpretation && <div className="drill-headline">{detail.interpretation}</div>}
      <div className="drill-metrics">
        {components.map((m) => (
          <div key={m.key} className="drill-metric">
            <div className="l">{m.label}</div>
            <div className="v">
              {m.value != null ? m.value.toFixed(m.key === "vacate_rate" ? 4 : 2) : "—"}
              {m.unit}
            </div>
            {m.ratio != null && (
              <div className={`r ${m.ratio > 1 ? "pos" : "neg"}`}>
                {m.ratio.toFixed(1)}× city avg
              </div>
            )}
          </div>
        ))}
      </div>
      <div className="drill-demo">
        Median income{" "}
        {typeof p.median_income === "number"
          ? `$${Math.round(p.median_income as number).toLocaleString()}`
          : "—"}
        {" · "}poverty {pct("poverty_rate")}
        {" · "}Black {pct("pct_black")}
        {" · "}Hispanic {pct("pct_hispanic")}
        {" · "}built ≈{typeof p.median_year_built === "number" ? Math.round(p.median_year_built as number) : "—"}
      </div>
    </div>
  );
}
