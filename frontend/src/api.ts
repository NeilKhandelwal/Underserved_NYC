import type {
  Correlation,
  ModelInfo,
  OverlaysResponse,
  PredictResponse,
  ScatterResponse,
  TractDetail,
  WatchlistDirection,
  WatchlistGroupRow,
  WatchlistRow,
} from "./types";

async function getJSON<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} for ${url}`);
  return res.json() as Promise<T>;
}

export const api = {
  overlays: () => getJSON<OverlaysResponse>("/api/overlays"),
  model: () => getJSON<ModelInfo>("/api/model"),
  correlations: () => getJSON<Correlation[]>("/api/correlations"),
  scatter: (column: string) => getJSON<ScatterResponse>(`/api/scatter/${column}`),
  tract: (geoid: string) => getJSON<TractDetail>(`/api/tract/${geoid}`),

  watchlist: (direction: WatchlistDirection, boroughs: string[], n: number) => {
    const params = new URLSearchParams({ direction, n: String(n) });
    for (const b of boroughs) params.append("borough", b);
    return getJSON<WatchlistRow[]>(`/api/watchlist?${params}`);
  },

  watchlistGroups: (
    by: "neighborhood" | "council_district",
    direction: WatchlistDirection,
    boroughs: string[],
    n: number,
  ) => {
    const params = new URLSearchParams({ by, direction, n: String(n) });
    for (const b of boroughs) params.append("borough", b);
    return getJSON<WatchlistGroupRow[]>(`/api/watchlist/groups?${params}`);
  },

  predict: async (inputs: Record<string, number>): Promise<PredictResponse> => {
    const res = await fetch("/api/predict", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ inputs }),
    });
    if (!res.ok) throw new Error(`predict failed: ${res.status}`);
    return res.json() as Promise<PredictResponse>;
  },
};
