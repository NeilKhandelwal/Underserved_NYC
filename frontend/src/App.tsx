import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import type { ModelInfo, OverlayInfo, OverlaysResponse } from "./types";
import { MapView } from "./components/MapView";
import { FilterCard } from "./components/FilterCard";
import { MapLegend } from "./components/MapLegend";
import { DetailCard } from "./components/DetailCard";
import { Watchlist } from "./components/Watchlist";
import { SearchBox, type Place } from "./components/SearchBox";
import { Demographics } from "./components/Demographics";
import { Predictor } from "./components/Predictor";
import { Methodology } from "./components/Methodology";
import { About } from "./components/About";
import { AboutModal } from "./components/AboutModal";
import { AskPlaceholder } from "./components/AskPlaceholder";

type Tab = "map" | "watchlist" | "demographics" | "predictor" | "ask" | "about" | "methodology";
const TABS: { id: Tab; label: string }[] = [
  { id: "map", label: "Map" },
  { id: "watchlist", label: "Watchlist" },
  { id: "demographics", label: "Demographics" },
  { id: "predictor", label: "Predictor" },
  { id: "ask", label: "Ask" },
  { id: "about", label: "About" },
  { id: "methodology", label: "Methodology" },
];

const ABOUT_SEEN_KEY = "underserved-nyc:about-seen";
const DEFAULT_OVERLAY = "Risk Score";

// Shareable map state from the query string. The overlay label is re-validated
// against the catalog once it loads; the tract geoid is passed through (a bad
// one just surfaces as the detail card's fetch error).
function initFromURL() {
  const p = new URLSearchParams(window.location.search);
  return {
    overlay: p.get("overlay") ?? DEFAULT_OVERLAY,
    tract: p.get("tract"),
    districts: p.get("districts") === "1",
  };
}

export function App() {
  const [init] = useState(initFromURL);
  const [overlaysResp, setOverlaysResp] = useState<OverlaysResponse | null>(null);
  const [model, setModel] = useState<ModelInfo | null>(null);
  const [overlayLabel, setOverlayLabel] = useState(init.overlay);
  const [selectedGeoid, setSelectedGeoid] = useState<string | null>(init.tract);
  const [showDistricts, setShowDistricts] = useState(init.districts);
  const [flyTo, setFlyTo] = useState<{ lon: number; lat: number; key: number } | null>(null);
  const [pin, setPin] = useState<{ lon: number; lat: number } | null>(null);
  const [tab, setTab] = useState<Tab>("map");
  const [showAbout, setShowAbout] = useState(false);
  // Id of the latest navigation intent (address search, list pick). Each one
  // awaits a request; a slow response from an older intent must not apply
  // its selection or camera move after a newer one has started.
  const navSeqRef = useRef(0);

  useEffect(() => {
    api
      .overlays()
      .then((resp) => {
        setOverlaysResp(resp);
        // Drop a URL-supplied overlay label the catalog doesn't know.
        const labels = new Set(resp.overlays.map((o) => o.label));
        setOverlayLabel((l) => (labels.has(l) ? l : DEFAULT_OVERLAY));
      })
      .catch(console.error);
    api.model().then(setModel).catch(console.error);
  }, []);

  // A shared link with a tract should land the viewer on it — unless they've
  // already navigated elsewhere (search, watchlist pick) before it resolves.
  useEffect(() => {
    if (!init.tract) return;
    const seq = ++navSeqRef.current;
    api
      .tract(init.tract)
      .then((d) => {
        if (navSeqRef.current !== seq) return; // superseded by a newer navigation
        const lon = d.properties.centroid_lon as number | null;
        const lat = d.properties.centroid_lat as number | null;
        if (lon != null && lat != null) setFlyTo({ lon, lat, key: Date.now() });
      })
      .catch(() => {
        /* bad geoid — the detail card surfaces the fetch error */
      });
  }, [init.tract]);

  // Mirror the shareable map state into the URL — replace, not push, so
  // browsing the map doesn't pollute history. Defaults are omitted.
  useEffect(() => {
    const p = new URLSearchParams();
    if (overlayLabel !== DEFAULT_OVERLAY) p.set("overlay", overlayLabel);
    if (selectedGeoid) p.set("tract", selectedGeoid);
    if (showDistricts) p.set("districts", "1");
    const qs = p.toString();
    window.history.replaceState(null, "", qs ? `?${qs}` : window.location.pathname);
  }, [overlayLabel, selectedGeoid, showDistricts]);

  // Greet first-time visitors with the About modal; returning visitors aren't interrupted.
  useEffect(() => {
    try {
      if (!localStorage.getItem(ABOUT_SEEN_KEY)) setShowAbout(true);
    } catch {
      setShowAbout(true);
    }
  }, []);

  function dismissAbout() {
    setShowAbout(false);
    try {
      localStorage.setItem(ABOUT_SEEN_KEY, "1");
    } catch {
      /* ignore (private mode, etc.) */
    }
  }

  const overlay: OverlayInfo | null = useMemo(() => {
    const list = overlaysResp?.overlays ?? [];
    return list.find((o) => o.label === overlayLabel) ?? list[0] ?? null;
  }, [overlaysResp, overlayLabel]);

  // Address search: drop a pin, fly there, and select the tract the point lands in.
  async function searchPlace(place: Place) {
    const seq = ++navSeqRef.current;
    setTab("map");
    setPin({ lon: place.lon, lat: place.lat });
    setFlyTo({ lon: place.lon, lat: place.lat, key: Date.now() });
    // Clear the previous tract now so its detail card can't describe the new
    // pin while the lookup is in flight (or if the lookup fails).
    setSelectedGeoid(null);
    try {
      const hit = await api.tractAt(place.lat, place.lon);
      if (navSeqRef.current !== seq) return; // superseded by a newer navigation
      setSelectedGeoid(hit?.geoid ?? null); // null when the point is outside all tracts
    } catch (e) {
      console.error(e);
    }
  }

  // Select a tract from the watchlist: fetch its centroid, fly there, show detail.
  async function selectFromList(geoid: string) {
    const seq = ++navSeqRef.current;
    setSelectedGeoid(geoid);
    setTab("map");
    try {
      const d = await api.tract(geoid);
      if (navSeqRef.current !== seq) return; // superseded by a newer navigation
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
            showDistricts={showDistricts}
            selectedGeoid={selectedGeoid}
            flyTo={flyTo}
            pin={pin}
            onSelect={(geoid) => setSelectedGeoid(geoid)}
          />
        )}
      </div>

      {tab === "map" && overlaysResp && overlay && (
        <>
          <SearchBox onSelect={searchPlace} onClear={() => setPin(null)} />
          <FilterCard
            overlays={overlaysResp.overlays}
            selected={overlay}
            showDistricts={showDistricts}
            onChange={setOverlayLabel}
            onToggleDistricts={setShowDistricts}
          />
          {selectedGeoid && (
            <DetailCard geoid={selectedGeoid} onClose={() => setSelectedGeoid(null)} />
          )}
          <MapLegend overlay={overlay} residualBins={overlaysResp.residual_bins} />
        </>
      )}

      {tab === "watchlist" && (
        <div className="panel">
          <Watchlist onSelect={selectFromList} />
        </div>
      )}
      {tab === "demographics" && (
        <div className="panel">
          <Demographics
            overlays={overlaysResp?.overlays ?? []}
            onShowOnMap={(label) => {
              setOverlayLabel(label);
              setTab("map");
            }}
          />
        </div>
      )}
      {tab === "predictor" && (
        <div className="panel">
          <Predictor model={model} />
        </div>
      )}
      {tab === "ask" && (
        <div className="panel">
          <AskPlaceholder />
        </div>
      )}
      {tab === "about" && (
        <div className="panel">
          <About />
        </div>
      )}
      {tab === "methodology" && (
        <div className="panel">
          <Methodology />
        </div>
      )}

      {showAbout && <AboutModal onClose={dismissAbout} />}
    </div>
  );
}
