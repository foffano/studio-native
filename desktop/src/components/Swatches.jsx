import React from "react";
import { IconCheck } from "./Icons.jsx";

const PALETTE = [
  "#ffffff",
  "#000000",
  "#9ca3af",
  "#ef4444",
  "#f97316",
  "#facc15",
  "#22c55e",
  "#3b82f6",
  "#a855f7",
  "#ec4899",
];

const norm = (c) => String(c || "").toLowerCase();

export default function Swatches({ value, onChange }) {
  const isCustom = !PALETTE.some((c) => norm(c) === norm(value));
  return (
    <div className="swatches">
      {PALETTE.map((color) => (
        <button
          type="button"
          key={color}
          className={"swatch" + (norm(color) === norm(value) ? " active" : "")}
          style={{ background: color }}
          onClick={() => onChange(color)}
          title={color}
        >
          <span className="chk">
            <IconCheck width={14} height={14} strokeWidth={3.5} />
          </span>
        </button>
      ))}
      <button
        type="button"
        className={"swatch swatch--custom" + (isCustom ? " active" : "")}
        title="Cor personalizada"
      >
        <span className="chk">
          <IconCheck width={14} height={14} strokeWidth={3.5} />
        </span>
        <input
          type="color"
          value={value && value.startsWith("#") ? value : "#ffffff"}
          onChange={(e) => onChange(e.target.value)}
        />
      </button>
    </div>
  );
}
