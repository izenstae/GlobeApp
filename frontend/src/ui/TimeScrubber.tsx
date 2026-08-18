import { useStore } from "../store";

/** Time-window control. Full scrubber playback is Phase 6 work; this covers
 * the window selection the globe filters on today. */

const WINDOWS: [number, string][] = [
  [6, "6 h"],
  [24, "24 h"],
  [72, "3 d"],
  [24 * 7, "7 d"],
  [24 * 14, "14 d"],
];

export default function TimeScrubber() {
  const sinceHours = useStore((s) => s.sinceHours);
  const setSinceHours = useStore((s) => s.setSinceHours);
  return (
    <div>
      <div className="mb-1 font-mono text-xs uppercase tracking-wide text-faint">Window</div>
      <div className="flex gap-1" role="radiogroup" aria-label="Time window">
        {WINDOWS.map(([hours, label]) => (
          <button
            key={hours}
            role="radio"
            aria-checked={sinceHours === hours}
            onClick={() => setSinceHours(hours)}
            className={`border px-2 py-0.5 font-mono text-xs focus:outline-none focus:ring-1 focus:ring-signal ${
              sinceHours === hours
                ? "border-signal text-signal"
                : "border-edge text-muted hover:text-bone"
            }`}
          >
            {label}
          </button>
        ))}
      </div>
    </div>
  );
}
