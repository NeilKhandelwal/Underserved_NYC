import type { OverlayInfo } from "../types";
import { colorAt, MISSING, RESIDUAL_COLORS } from "../colors";
import { formatValue } from "../format";

interface Props {
  overlays: OverlayInfo[];
  selected: OverlayInfo;
  residualBins: number[] | null;
  showDistricts: boolean;
  onChange: (label: string) => void;
  onToggleDistricts: (show: boolean) => void;
}

export function FilterCard({
  overlays,
  selected,
  residualBins,
  showDistricts,
  onChange,
  onToggleDistricts,
}: Props) {
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
      <label className="overlay-opt districts-toggle">
        <input
          type="checkbox"
          checked={showDistricts}
          onChange={(e) => onToggleDistricts(e.target.checked)}
        />
        Council district boundaries
      </label>
      {selected.symmetric_bins && residualBins ? (
        <ResidualLegend bins={residualBins} />
      ) : (
        <ContinuousLegend overlay={selected} />
      )}
      <div className="legend-note">{selected.legend}</div>
      <div className="legend-missing">
        <span className="swatch" style={{ background: MISSING }} />
        no data
      </div>
    </div>
  );
}

// Continuous overlays interpolate linearly between the citywide min and max,
// so the legend shows the actual end values in the overlay's own format.
function ContinuousLegend({ overlay }: { overlay: OverlayInfo }) {
  const swatches = Array.from({ length: 9 }, (_, i) => colorAt(i / 8, overlay.scheme));
  const [min, max] = overlay.domain ?? [0, 1];
  return (
    <>
      <div className="legend-bar">
        {swatches.map((c, i) => (
          <div key={i} style={{ background: c }} />
        ))}
      </div>
      <div className="legend-ends">
        <span>{formatValue(min, overlay.format)}</span>
        <span>{formatValue(max, overlay.format)}</span>
      </div>
    </>
  );
}

// The residual layer paints 6 fixed classes (not a continuous ramp), so the
// legend mirrors those exact bins with their edge values.
function ResidualLegend({ bins }: { bins: number[] }) {
  const inner = bins.slice(1, -1); // e.g. [-20, -10, 0, 10, 20]
  return (
    <>
      <div className="legend-bar binned">
        {RESIDUAL_COLORS.map((c, i) => (
          <div key={i} style={{ background: c }} />
        ))}
      </div>
      <div className="legend-ticks">
        {inner.map((e, i) => (
          <span key={e} style={{ left: `${((i + 1) / RESIDUAL_COLORS.length) * 100}%` }}>
            {e > 0 ? `+${e}` : e}
          </span>
        ))}
      </div>
      <div className="legend-ends">
        <span>better than predicted</span>
        <span>worse than predicted</span>
      </div>
    </>
  );
}
