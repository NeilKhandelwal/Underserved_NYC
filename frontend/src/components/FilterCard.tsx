import type { OverlayInfo } from "../types";
import { colorAt } from "../colors";

interface Props {
  overlays: OverlayInfo[];
  selected: OverlayInfo;
  onChange: (label: string) => void;
}

export function FilterCard({ overlays, selected, onChange }: Props) {
  return (
    <div className="card filters">
      <h3>Map Overlay</h3>
      {overlays.map((o) => (
        <label
          key={o.label}
          className={`overlay-opt ${o.label === selected.label ? "active" : ""}`}
        >
          <input
            type="radio"
            name="overlay"
            checked={o.label === selected.label}
            onChange={() => onChange(o.label)}
          />
          {o.label}
        </label>
      ))}
      <Legend overlay={selected} />
    </div>
  );
}

function Legend({ overlay }: { overlay: OverlayInfo }) {
  const swatches = Array.from({ length: 9 }, (_, i) => colorAt(i / 8, overlay.scheme));
  const [lo, hi] = overlay.symmetric_bins
    ? ["− residual", "+ residual"]
    : overlay.reverse
      ? ["lower", "higher"]
      : ["lower", "higher"];
  return (
    <>
      <div className="legend-bar">
        {swatches.map((c, i) => (
          <div key={i} style={{ background: c }} />
        ))}
      </div>
      <div className="legend-ends">
        <span>{lo}</span>
        <span>{hi}</span>
      </div>
      <div className="legend-note">{overlay.legend}</div>
    </>
  );
}
