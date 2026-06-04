import { useEffect, useRef } from "react";
import maplibregl from "maplibre-gl";
import { Protocol } from "pmtiles";
import type { OverlayInfo } from "../types";
import { fillColor } from "../colors";

const STYLE = "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json";
const SOURCE = "tracts";
const SOURCE_LAYER = "tracts";
const FILL = "tracts-fill";
const NYC_CENTER: [number, number] = [-73.95, 40.7];

// Register the pmtiles:// protocol once for the whole app.
let protocolRegistered = false;
function ensureProtocol() {
  if (protocolRegistered) return;
  maplibregl.addProtocol("pmtiles", new Protocol().tile);
  protocolRegistered = true;
}

// Drop the basemap's road/street layers (OpenMapTiles "transportation" schema)
// so only land, water, boundaries, and place labels remain under the choropleth.
function stripStreets(map: maplibregl.Map) {
  for (const layer of map.getStyle().layers ?? []) {
    const sourceLayer = (layer as { "source-layer"?: string })["source-layer"];
    if (sourceLayer === "transportation" || sourceLayer === "transportation_name") {
      if (map.getLayer(layer.id)) map.removeLayer(layer.id);
    }
  }
}

interface Props {
  overlay: OverlayInfo;
  residualBins: number[] | null;
  selectedGeoid: string | null;
  flyTo: { lon: number; lat: number; key: number } | null;
  onSelect: (geoid: string | null) => void;
}

export function MapView({ overlay, residualBins, selectedGeoid, flyTo, onSelect }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const readyRef = useRef(false);
  const selectedRef = useRef<string | null>(null);
  const hoveredRef = useRef<string | null>(null);
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;

  // Init map once.
  useEffect(() => {
    ensureProtocol();
    if (!containerRef.current) return;
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: STYLE,
      center: NYC_CENTER,
      zoom: 10,
      // Tract-level analysis: cap zoom so the map never overzooms the tiles
      // (which stair-steps edges and reveals basemap buildings under the fill).
      maxZoom: 13,
      minZoom: 9,
      attributionControl: { compact: true },
    });
    mapRef.current = map;
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");

    map.on("load", () => {
      stripStreets(map);
      map.addSource(SOURCE, {
        type: "vector",
        url: "pmtiles:///tiles/tracts.pmtiles",
        promoteId: "GEOID",
      });

      // Insert choropleth beneath the basemap's text labels for readability.
      const firstSymbol = map.getStyle().layers?.find((l) => l.type === "symbol")?.id;

      map.addLayer(
        {
          id: FILL,
          type: "fill",
          source: SOURCE,
          "source-layer": SOURCE_LAYER,
          paint: {
            "fill-color": fillColor(overlay, residualBins),
            "fill-opacity": [
              "case",
              ["boolean", ["feature-state", "hover"], false],
              0.9,
              0.72,
            ],
          },
        },
        firstSymbol,
      );
      map.addLayer(
        {
          id: "tracts-line",
          type: "line",
          source: SOURCE,
          "source-layer": SOURCE_LAYER,
          paint: {
            "line-color": "#2a2a38",
            "line-opacity": 0.55,
            // Thicken with zoom so borders stay legible as you zoom in.
            "line-width": ["interpolate", ["linear"], ["zoom"], 9, 0.5, 11, 1, 13, 1.8],
          },
        },
        firstSymbol,
      );
      map.addLayer({
        id: "tracts-selected",
        type: "line",
        source: SOURCE,
        "source-layer": SOURCE_LAYER,
        paint: {
          "line-color": "#111",
          "line-width": ["case", ["boolean", ["feature-state", "selected"], false], 3, 0],
          "line-dasharray": [2, 1],
        },
      });

      readyRef.current = true;
      applySelection(selectedRef.current);
    });

    // Hover + click handlers.
    map.on("mousemove", FILL, (e) => {
      map.getCanvas().style.cursor = "pointer";
      const id = e.features?.[0]?.properties?.GEOID as string | undefined;
      if (id === hoveredRef.current) return;
      setHover(hoveredRef.current, false);
      hoveredRef.current = id ?? null;
      setHover(hoveredRef.current, true);
    });
    map.on("mouseleave", FILL, () => {
      map.getCanvas().style.cursor = "";
      setHover(hoveredRef.current, false);
      hoveredRef.current = null;
    });
    map.on("click", (e) => {
      const feats = map.queryRenderedFeatures(e.point, { layers: [FILL] });
      const id = feats[0]?.properties?.GEOID as string | undefined;
      onSelectRef.current(id ?? null);
    });

    function setHover(id: string | null, on: boolean) {
      if (!id) return;
      map.setFeatureState({ source: SOURCE, sourceLayer: SOURCE_LAYER, id }, { hover: on });
    }

    return () => {
      map.remove();
      mapRef.current = null;
      readyRef.current = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Re-style fill when the overlay changes.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !readyRef.current) return;
    map.setPaintProperty(FILL, "fill-color", fillColor(overlay, residualBins));
  }, [overlay, residualBins]);

  // Reflect the selected tract via feature-state.
  useEffect(() => {
    applySelection(selectedGeoid);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedGeoid]);

  function applySelection(geoid: string | null) {
    const map = mapRef.current;
    if (!map || !readyRef.current) {
      selectedRef.current = geoid;
      return;
    }
    if (selectedRef.current) {
      map.setFeatureState(
        { source: SOURCE, sourceLayer: SOURCE_LAYER, id: selectedRef.current },
        { selected: false },
      );
    }
    if (geoid) {
      map.setFeatureState(
        { source: SOURCE, sourceLayer: SOURCE_LAYER, id: geoid },
        { selected: true },
      );
    }
    selectedRef.current = geoid;
  }

  // Fly to a tract centroid (from the watchlist).
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !flyTo) return;
    map.flyTo({ center: [flyTo.lon, flyTo.lat], zoom: 12.5, duration: 900 });
  }, [flyTo]);

  return <div ref={containerRef} style={{ width: "100%", height: "100%" }} />;
}
