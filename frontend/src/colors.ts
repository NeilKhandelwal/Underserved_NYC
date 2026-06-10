import type { ExpressionSpecification } from "maplibre-gl";
import type { OverlayInfo } from "./types";

// ColorBrewer RdYlGn (9-class), ordered low -> high (red -> green).
export const RDYLGN = [
  "#d73027", "#f46d43", "#fdae61", "#fee08b", "#ffffbf",
  "#d9ef8b", "#a6d96a", "#66bd63", "#1a9850",
];

export const MISSING = "#d9d9d9"; // matches folium's nan_fill_color "lightgray"

// 6-class diverging for the residual layer (RdYlGn_r: negative=green, positive=red).
export const RESIDUAL_COLORS = [
  "#1a9850", "#91cf60", "#d9ef8b", "#fee08b", "#fc8d59", "#d73027",
];

/** Color for a normalized [0,1] position, honoring the overlay's scheme. */
export function colorAt(t: number, scheme: OverlayInfo["scheme"]): string {
  const ramp = scheme === "RdYlGn_r" ? [...RDYLGN].reverse() : RDYLGN;
  const x = Math.max(0, Math.min(1, t)) * (ramp.length - 1);
  return ramp[Math.round(x)];
}

/** MapLibre fill-color expression for the given overlay. */
export function fillColor(
  overlay: OverlayInfo,
  residualBins: number[] | null,
): ExpressionSpecification {
  const col = overlay.column;
  const value: unknown = ["to-number", ["get", col]];

  // Residual: fixed symmetric step bins (magnitude, not rank).
  if (overlay.symmetric_bins && residualBins) {
    // bins = [-edge,-20,-10,0,10,20,edge]; 6 interior classes use the 5 inner edges.
    const inner = residualBins.slice(1, -1); // [-20,-10,0,10,20]
    const step: unknown[] = ["step", value, RESIDUAL_COLORS[0]];
    inner.forEach((edge, i) => step.push(edge, RESIDUAL_COLORS[i + 1]));
    return guardMissing(col, step as unknown as ExpressionSpecification);
  }

  // Continuous: interpolate across the domain.
  const [min, max] = overlay.domain ?? [0, 1];
  const ramp = overlay.scheme === "RdYlGn_r" ? [...RDYLGN].reverse() : RDYLGN;
  const interp: unknown[] = ["interpolate", ["linear"], value];
  ramp.forEach((c, i) => {
    const stop = min + ((max - min) * i) / (ramp.length - 1);
    interp.push(stop, c);
  });
  return guardMissing(col, interp as unknown as ExpressionSpecification);
}

/** Wrap an expression so missing/non-numeric values render as gray. */
function guardMissing(
  col: string,
  expr: ExpressionSpecification,
): ExpressionSpecification {
  return [
    "case",
    ["==", ["typeof", ["get", col]], "number"],
    expr,
    MISSING,
  ] as unknown as ExpressionSpecification;
}
