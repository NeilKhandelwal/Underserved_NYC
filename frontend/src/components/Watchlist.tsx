import { useEffect, useState } from "react";
import { api } from "../api";
import type { TractSummary, WatchlistDirection } from "../types";

const BOROUGHS = ["Bronx", "Brooklyn", "Manhattan", "Queens", "Staten Island"];
const DIRECTIONS: { id: WatchlistDirection; label: string }[] = [
  { id: "neglect", label: "Most unexplained neglect (+)" },
  { id: "success", label: "Unexpected success (−)" },
  { id: "surprise", label: "Biggest surprises (|res|)" },
];

export function Watchlist({ onSelect }: { onSelect: (geoid: string) => void }) {
  const [direction, setDirection] = useState<WatchlistDirection>("neglect");
  const [boroughs, setBoroughs] = useState<string[]>(BOROUGHS);
  const [n, setN] = useState(20);
  const [rows, setRows] = useState<TractSummary[]>([]);

  useEffect(() => {
    api.watchlist(direction, boroughs, n).then(setRows).catch(console.error);
  }, [direction, boroughs, n]);

  function toggleBorough(b: string) {
    setBoroughs((cur) => (cur.includes(b) ? cur.filter((x) => x !== b) : [...cur, b]));
  }

  return (
    <>
      <h2>Top Residual Outliers</h2>
      <p className="sub">
        Tracts whose risk score diverges most from what demographics predict. Positive
        residual = more underserved than poverty, race, and education alone would suggest.
        |residual| &lt; 10 is within the model's noise floor. Click a row to see it on the map.
      </p>

      <div className="controls">
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

      <table className="data">
        <thead>
          <tr>
            <th>Neighborhood</th>
            <th>Borough</th>
            <th className="num">Risk</th>
            <th className="num">Residual</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.geoid} onClick={() => onSelect(r.geoid)}>
              <td className="name">{r.neighborhood ?? "—"}</td>
              <td>{r.borough}</td>
              <td className="num">{r.risk_score?.toFixed(1)}</td>
              <td className={`num ${(r.risk_residual ?? 0) >= 0 ? "pos" : "neg"}`}>
                {r.risk_residual != null
                  ? `${r.risk_residual >= 0 ? "+" : ""}${r.risk_residual.toFixed(1)}`
                  : ""}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
