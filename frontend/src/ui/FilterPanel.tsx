import { useState } from "react";
import { useStore } from "../store";
import TimeScrubber from "./TimeScrubber";

const CATEGORIES: [string, string][] = [
  ["airstrike", "Airstrike"],
  ["missile_strike", "Missile strike"],
  ["drone_strike", "Drone strike"],
  ["artillery", "Artillery"],
  ["ied", "IED"],
  ["small_arms", "Small arms"],
  ["ground_assault", "Ground assault"],
  ["naval", "Naval"],
  ["abduction", "Abduction"],
  ["riot", "Riot"],
  ["protest", "Protest"],
  ["other_violence", "Other violence"],
  ["non_kinetic", "Non-kinetic"],
];

export default function FilterPanel() {
  const [open, setOpen] = useState(false);
  const categoryFilter = useStore((s) => s.categoryFilter);
  const setCategoryFilter = useStore((s) => s.setCategoryFilter);
  const minReliability = useStore((s) => s.minReliability);
  const setMinReliability = useStore((s) => s.setMinReliability);

  const toggle = (key: string) => {
    const next = new Set(categoryFilter);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    setCategoryFilter(next);
  };

  return (
    <div className="pointer-events-auto absolute left-4 top-4 z-20 w-64">
      <button
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="border border-edge bg-panel/95 px-3 py-1.5 font-mono text-xs text-muted hover:text-bone focus:outline-none focus:ring-1 focus:ring-signal"
      >
        filters {categoryFilter.size > 0 || minReliability > 0 ? "· active" : ""}
      </button>
      {open && (
        <div className="mt-1 space-y-4 border border-edge bg-panel/95 p-3 text-sm">
          <div>
            <div className="mb-1 font-mono text-xs uppercase tracking-wide text-faint">
              Category
            </div>
            <div className="grid grid-cols-2 gap-x-2 gap-y-1">
              {CATEGORIES.map(([key, label]) => (
                <label key={key} className="flex items-center gap-1.5 text-muted">
                  <input
                    type="checkbox"
                    checked={categoryFilter.size === 0 || categoryFilter.has(key)}
                    onChange={() => toggle(key)}
                    className="accent-[#d98e32]"
                  />
                  <span className="text-xs">{label}</span>
                </label>
              ))}
            </div>
            <p className="mt-1 font-mono text-[10px] text-faint">
              all checked = no filter
            </p>
          </div>
          <div>
            <div className="mb-1 font-mono text-xs uppercase tracking-wide text-faint">
              Reliability floor:{" "}
              <span className="text-bone">{minReliability.toFixed(2)}</span>
            </div>
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={minReliability}
              onChange={(e) => setMinReliability(Number(e.target.value))}
              className="w-full accent-[#d98e32]"
              aria-label="Minimum reliability"
            />
          </div>
          <TimeScrubber />
        </div>
      )}
    </div>
  );
}
