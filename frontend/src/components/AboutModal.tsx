import { AboutContent } from "./About";

/**
 * Welcome dialog shown to first-time visitors. Dismissing it records a flag in
 * localStorage so returning visitors aren't interrupted; the same content stays
 * available any time under the "About" tab.
 */
export function AboutModal({ onClose }: { onClose: () => void }) {
  return (
    <div className="about-backdrop" onClick={onClose}>
      <div
        className="about-modal"
        role="dialog"
        aria-modal="true"
        aria-label="About this tool"
        onClick={(e) => e.stopPropagation()}
      >
        <button className="about-close" aria-label="Close" onClick={onClose}>
          ×
        </button>
        <AboutContent />
        <div className="about-actions">
          <button className="about-cta" onClick={onClose}>
            Explore the map
          </button>
        </div>
      </div>
    </div>
  );
}
