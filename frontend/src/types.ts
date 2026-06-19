// Mirrors the FastAPI response schemas (api/schemas.py).

export interface TractSummary {
  geoid: string;
  neighborhood: string | null;
  borough: string | null;
  council_district: number | null;
  risk_score: number | null;
  risk_residual: number | null;
}

export interface WatchlistRow extends TractSummary {
  predicted_risk: number | null;
  median_income: number | null;
}

export interface WatchlistGroupRow {
  key: string;
  group_by: "neighborhood" | "council_district";
  borough: string | null;
  tract_count: number;
  mean_residual: number;
  mean_risk: number | null;
  top_geoid: string;
  top_neighborhood: string | null;
  top_residual: number;
}

export interface MetricComparison {
  key: string;
  label: string;
  value: number | null;
  citywide_mean: number | null;
  ratio: number | null;
  direction: "higher" | "lower" | null;
  unit: string;
}

export interface TractDetail extends TractSummary {
  predicted_risk: number | null;
  band: "high" | "elevated" | "low";
  interpretation: string | null;
  metrics: MetricComparison[];
  properties: Record<string, number | string | null>;
}

// Per-tract quarterly series (api/schemas.py:TractTimeSeries). Every list is
// index-aligned to `quarters` and null-padded where the tract had no score that
// quarter. `risk_residual` is present only when the bundle carries the residual.
export interface TractTimeSeries {
  geoid: string;
  quarters: string[];
  risk_score: (number | null)[];
  risk_residual: (number | null)[] | null;
  accountability_gap: (number | null)[];
  weighted_violation_rate: (number | null)[];
  avg_closure_time_adjusted: (number | null)[];
  vacate_rate: (number | null)[];
}

export interface Correlation {
  column: string;
  label: string;
  r: number;
}

export interface ScatterResponse {
  column: string;
  label: string;
  r: number;
  n: number;
  points: [number, number][]; // [feature value, risk score]
}

export interface FeatureRange {
  min: number;
  max: number;
  median: number;
}

export interface ModelInfo {
  features: string[];
  labels: Record<string, string>;
  r2: number;
  rmse: number;
  importance: Record<string, number>;
  feature_ranges: Record<string, FeatureRange>;
}

export interface OverlayInfo {
  label: string;
  column: string;
  format: string;
  legend: string;
  scheme: "RdYlGn" | "RdYlGn_r";
  reverse: boolean;
  symmetric_bins: boolean;
  domain: [number, number] | null;
}

export interface OverlaysResponse {
  overlays: OverlayInfo[];
  residual_bins: number[] | null;
}

export interface PredictResponse {
  predicted_risk: number;
  band: "high" | "elevated" | "low";
  inputs_used: Record<string, number>;
  clamped: string[];
}

export type WatchlistDirection = "neglect" | "success" | "surprise";
