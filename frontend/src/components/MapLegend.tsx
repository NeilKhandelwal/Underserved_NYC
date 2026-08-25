import type { OverlayInfo } from "../types";
import { colorAt, MISSING, RESIDUAL_COLORS } from "../colors";
import { formatValue } from "../format";

// Static color key pinned to the bottom-left corner of the map, so it stays
// visible however the floating cards are dragged or collapsed.
export function MapLegend({
  overlay,
  residualBins,
}: {
  overlay: OverlayInfo;
  residualBins: number[] | null;
}) {
  return (
    <div className="map-legend">
      <div className="legend-title">{overlay.label}</div>
      {overlay.symmetric_bins && residualBins ? (
        <ResidualLegend bins={residualBins} />
      ) : (
        <ContinuousLegend overlay={overlay} />
      )}
      <div className="legend-note">{overlay.legend}</div>
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
