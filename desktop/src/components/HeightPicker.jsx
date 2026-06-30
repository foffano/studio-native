import React, { useCallback, useEffect, useRef } from "react";

const PAD = 8;
const clamp01 = (v) => Math.max(0, Math.min(1, v));

// value: 0..1 (0 = topo, 1 = base). onChange(value).
export default function HeightPicker({ value, onChange }) {
  const frameRef = useRef(null);
  const indRef = useRef(null);
  const dragging = useRef(false);

  const layout = useCallback(() => {
    const f = frameRef.current;
    const ind = indRef.current;
    if (!f || !ind) return;
    const usable = Math.max(1, f.clientHeight - ind.offsetHeight - 2 * PAD);
    ind.style.top = PAD + clamp01(value) * usable + "px";
  }, [value]);

  useEffect(() => {
    layout();
    window.addEventListener("resize", layout);
    return () => window.removeEventListener("resize", layout);
  }, [layout]);

  const fromEvent = (e) => {
    const f = frameRef.current;
    const ind = indRef.current;
    const r = f.getBoundingClientRect();
    const clientY = e.touches ? e.touches[0].clientY : e.clientY;
    const cy = clientY - r.top;
    const usable = Math.max(1, r.height - ind.offsetHeight - 2 * PAD);
    return clamp01((cy - PAD - ind.offsetHeight / 2) / usable);
  };

  const onDown = (e) => {
    dragging.current = true;
    try {
      e.currentTarget.setPointerCapture(e.pointerId);
    } catch (_) {}
    onChange(fromEvent(e));
  };
  const onMove = (e) => {
    if (dragging.current) onChange(fromEvent(e));
  };
  const onUp = (e) => {
    dragging.current = false;
    try {
      e.currentTarget.releasePointerCapture(e.pointerId);
    } catch (_) {}
  };

  return (
    <div className="height-picker">
      <div
        className="hp-frame"
        ref={frameRef}
        onPointerDown={onDown}
        onPointerMove={onMove}
        onPointerUp={onUp}
      >
        <div className="hp-indicator" ref={indRef}>
          <span />
          <span />
        </div>
      </div>
      <div className="hp-info">
        <div className="hp-value">
          {Math.round(value * 100)}
          <small>%</small>
        </div>
        <div className="hp-hint">
          Arraste no preview para escolher a altura. 0% = topo · 100% = base.
          O texto fica centralizado na horizontal.
        </div>
      </div>
    </div>
  );
}
