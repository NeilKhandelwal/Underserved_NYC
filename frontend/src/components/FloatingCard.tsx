import { useRef, useState, type ReactNode } from "react";

interface Props {
  className: string;
  title: ReactNode;
  onClose?: () => void;
  children: ReactNode;
}

// Shared shell for the floating map cards: header is a drag handle (pointer
// events, offset applied as a translate on top of the CSS anchor position),
// with minimize and optional close buttons.
export function FloatingCard({ className, title, onClose, children }: Props) {
  const [collapsed, setCollapsed] = useState(false);
  const [pos, setPos] = useState({ x: 0, y: 0 });
  const dragRef = useRef<{
    startX: number;
    startY: number;
    baseX: number;
    baseY: number;
    // Card rect at drag start; clamping keeps it inside the viewport.
    left: number;
    top: number;
    width: number;
  } | null>(null);

  function onPointerDown(e: React.PointerEvent<HTMLDivElement>) {
    if ((e.target as HTMLElement).closest("button, select, input")) return;
    const rect = (e.currentTarget.parentElement as HTMLElement).getBoundingClientRect();
    dragRef.current = {
      startX: e.clientX,
      startY: e.clientY,
      baseX: pos.x,
      baseY: pos.y,
      left: rect.left,
      top: rect.top,
      width: rect.width,
    };
    e.currentTarget.setPointerCapture(e.pointerId);
  }

  function onPointerMove(e: React.PointerEvent<HTMLDivElement>) {
    const d = dragRef.current;
    if (!d) return;
    // Keep the card horizontally on-screen and its header row reachable
    // vertically (below the 52px tab bar, above the bottom edge).
    const dx = Math.min(
      Math.max(e.clientX - d.startX, 8 - d.left),
      window.innerWidth - d.width - 8 - d.left,
    );
    const dy = Math.min(
      Math.max(e.clientY - d.startY, 60 - d.top),
      window.innerHeight - 48 - d.top,
    );
    setPos({ x: d.baseX + dx, y: d.baseY + dy });
  }

  function onPointerUp(e: React.PointerEvent<HTMLDivElement>) {
    dragRef.current = null;
    e.currentTarget.releasePointerCapture(e.pointerId);
  }

  return (
    <div
      className={`card ${className} ${collapsed ? "collapsed" : ""}`}
      style={{ transform: `translate(${pos.x}px, ${pos.y}px)` }}
    >
      <div
        className="card-header"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
      >
        <h3>{title}</h3>
        <button
          className="card-btn"
          onClick={() => setCollapsed((c) => !c)}
          aria-label={collapsed ? "Expand" : "Minimize"}
        >
          {collapsed ? "+" : "–"}
        </button>
        {onClose && (
          <button className="card-btn" onClick={onClose} aria-label="Close">
            ✕
          </button>
        )}
      </div>
      {!collapsed && children}
    </div>
  );
}
