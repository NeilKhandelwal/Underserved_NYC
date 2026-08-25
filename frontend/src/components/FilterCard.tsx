import type { OverlayInfo } from "../types";
import { FloatingCard } from "./FloatingCard";

interface Props {
  overlays: OverlayInfo[];
  selected: OverlayInfo;
  showDistricts: boolean;
  onChange: (label: string) => void;
  onToggleDistricts: (show: boolean) => void;
}

export function FilterCard({
  overlays,
  selected,
  showDistricts,
  onChange,
  onToggleDistricts,
}: Props) {
  return (
    <FloatingCard className="filters" title="Map Overlay">
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
    </FloatingCard>
  );
}
