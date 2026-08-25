import { useEffect, useRef, useState } from "react";

// NYC Planning Labs GeoSearch — free, no API key, NYC-tuned autocomplete.
// https://geosearch.planninglabs.nyc/docs/
const GEOSEARCH = "https://geosearch.planninglabs.nyc/v2/autocomplete";
const DEBOUNCE_MS = 250;

export interface Place {
  label: string;
  lon: number;
  lat: number;
}

interface GeoSearchResponse {
  features: {
    geometry: { coordinates: [number, number] }; // [lon, lat]
    properties: { label: string };
  }[];
}

interface Props {
  onSelect: (place: Place) => void;
  onClear: () => void;
}

export function SearchBox({ onSelect, onClear }: Props) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Place[]>([]);
  const [open, setOpen] = useState(false);
  const skipNextFetch = useRef(false); // suppress the fetch a selection's setQuery triggers

  // Debounced autocomplete; aborts the in-flight request when the query changes.
  useEffect(() => {
    if (skipNextFetch.current) {
      skipNextFetch.current = false;
      return;
    }
    const text = query.trim();
    if (text.length < 3) {
      setResults([]);
      setOpen(false);
      return;
    }
    const controller = new AbortController();
    const timer = setTimeout(async () => {
      try {
        const res = await fetch(
          `${GEOSEARCH}?text=${encodeURIComponent(text)}`,
          { signal: controller.signal },
        );
        if (!res.ok) return;
        const data: GeoSearchResponse = await res.json();
        setResults(
          data.features.map((f) => ({
            label: f.properties.label,
            lon: f.geometry.coordinates[0],
            lat: f.geometry.coordinates[1],
          })),
        );
        setOpen(true);
      } catch {
        /* aborted or network error — leave prior results untouched */
      }
    }, DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [query]);

  function choose(place: Place) {
    skipNextFetch.current = true;
    setQuery(place.label);
    setResults([]);
    setOpen(false);
    onSelect(place);
  }

  function clear() {
    setQuery("");
    setResults([]);
    setOpen(false);
    onClear();
  }

  return (
    <div className="search-box">
      <input
        className="search-input"
        type="text"
        value={query}
        placeholder="Search an address…"
        aria-label="Search an address"
        onChange={(e) => setQuery(e.target.value)}
        onFocus={() => results.length && setOpen(true)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && results.length) choose(results[0]);
          else if (e.key === "Escape") clear();
        }}
      />
      {query && (
        <button className="search-clear" aria-label="Clear search" onClick={clear}>
          ×
        </button>
      )}
      {open && results.length > 0 && (
        <ul className="search-results">
          {results.map((p, i) => (
            <li key={i}>
              <button className="search-result" onClick={() => choose(p)}>
                {p.label}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
