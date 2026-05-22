import { useEffect, useMemo, useState } from "react";
import { api } from "./api";
import type { ModelInfo, OverlayInfo, OverlaysResponse } from "./types";
import { MapView } from "./components/MapView";
import { FilterCard } from "./components/FilterCard";
import { DetailCard } from "./components/DetailCard";
import { Watchlist } from "./components/Watchlist";
import { Demographics } from "./components/Demographics";
import { Predictor } from "./components/Predictor";
import { Methodology } from "./components/Methodology";

type Tab = "map" | "watchlist" | "demographics" | "predictor" | "methodology";
const TABS: { id: Tab; label: string }[] = [
  { id: "map", label: "Map" },
  { id: "watchlist", label: "Watchlist" },
  { id: "demographics", label: "Demographics" },
  { id: "predictor", label: "Predictor" },
  { id: "methodology", label: "Methodology" },
];

export function App() {
  const [overlaysResp, setOverlaysResp] = useState<OverlaysResponse | null>(null);
  const [model, setModel] = useState<ModelInfo | null>(null);
  const [overlayLabel, setOverlayLabel] = useState("Risk Score");
  const [selectedGeoid, setSelectedGeoid] = useState<string | null>(null);
  const [flyTo, setFlyTo] = useState<{ lon: number; lat: number; key: number } | null>(null);
  const [tab, setTab] = useState<Tab>("map");

  useEffect(() => {
    api.overlays().then(setOverlaysResp).catch(console.error);
    api.model().then(setModel).catch(console.error);
  }, []);

  const overlay: OverlayInfo | null = useMemo(() => {
    const list = overlaysResp?.overlays ?? [];
    return list.find((o) => o.label === overlayLabel) ?? list[0] ?? null;
  }, [overlaysResp, overlayLabel]);

  // Select a tract from the watchlist: fetch its centroid, fly there, show detail.
  async function selectFromList(geoid: string) {
    setSelectedGeoid(geoid);
    setTab("map");
    try {
      const d = await api.tract(geoid);
      const lon = d.properties.centroid_lon as number | null;
      const lat = d.properties.centroid_lat as number | null;
      if (lon != null && lat != null) setFlyTo({ lon, lat, key: Date.now() });
    } catch (e) {
      console.error(e);
    }
  }

  return (
    <div className="app">
      <nav className="tabbar">
        <div className="brand">Underservice<span>·</span>NYC</div>
        {TABS.map((t) => (
          <button
            key={t.id}
            className={`tab ${tab === t.id ? "active" : ""}`}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </nav>

      {/* Map stays mounted across tabs so it never re-initializes. */}
      <div className="map-root" style={{ visibility: tab === "map" ? "visible" : "hidden" }}>
        {overlay && (
          <MapView
            overlay={overlay}
            residualBins={overlaysResp?.residual_bins ?? null}
            selectedGeoid={selectedGeoid}
            flyTo={flyTo}
            onSelect={(geoid) => setSelectedGeoid(geoid)}
          />
        )}
      </div>

      {tab === "map" && overlaysResp && overlay && (
        <>
          <FilterCard
            overlays={overlaysResp.overlays}
            selected={overlay}
            onChange={setOverlayLabel}
          />
          {selectedGeoid && (
            <DetailCard geoid={selectedGeoid} onClose={() => setSelectedGeoid(null)} />
          )}
        </>
      )}

      {tab === "watchlist" && (
        <div className="panel">
          <Watchlist onSelect={selectFromList} />
        </div>
      )}
      {tab === "demographics" && (
        <div className="panel">
          <Demographics />
        </div>
      )}
      {tab === "predictor" && (
        <div className="panel">
          <Predictor model={model} />
        </div>
      )}
      {tab === "methodology" && (
        <div className="panel">
          <Methodology />
        </div>
      )}
    </div>
  );
}
