import { useEffect, useRef, useState } from "react";
import { useStore } from "../store";

/** Timeline scrubber with playback (Phase 6). The handle positions the END of
 * the visible window inside the loaded 14-day range; the span buttons set the
 * window length. Scrubbing suspends live mode with no auto-resume countdown —
 * LIVE is an explicit act. Playback sweeps the window forward and hands back
 * to live when it reaches now. */

const RANGE_MS = 14 * 24 * 3_600_000; // matches the /events default load depth
const STEP_MS = 15 * 60_000;
const PLAY_TICK_MS = 100;
const PLAY_ADVANCE_MS = 36 * 60_000; // 6 h of history per real second

const SPANS: [number, string][] = [
  [6, "6 h"],
  [24, "24 h"],
  [72, "3 d"],
  [24 * 7, "7 d"],
  [24 * 14, "14 d"],
];

function utcShort(ms: number): string {
  return new Date(ms).toISOString().replace("T", " ").slice(5, 16);
}

export default function TimeScrubber() {
  const sinceHours = useStore((s) => s.sinceHours);
  const setSinceHours = useStore((s) => s.setSinceHours);
  const scrubEnd = useStore((s) => s.scrubEnd);
  const setScrubEnd = useStore((s) => s.setScrubEnd);
  const resumeLive = useStore((s) => s.resumeLive);
  const [playing, setPlaying] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const playTimer = useRef<number | null>(null);

  // Keep the rail's "now" edge honest while idle.
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 60_000);
    return () => window.clearInterval(id);
  }, []);

  // Anything that returns the timeline to live also stops playback.
  useEffect(() => {
    if (scrubEnd === null) setPlaying(false);
  }, [scrubEnd]);

  useEffect(() => {
    if (!playing) {
      if (playTimer.current !== null) {
        window.clearInterval(playTimer.current);
        playTimer.current = null;
      }
      return;
    }
    playTimer.current = window.setInterval(() => {
      const current = useStore.getState().scrubEnd;
      if (current === null) return;
      const next = current + PLAY_ADVANCE_MS;
      if (next >= Date.now()) {
        setPlaying(false);
        resumeLive(); // caught up: back to live, timeline at now
      } else {
        setScrubEnd(next);
      }
    }, PLAY_TICK_MS);
    return () => {
      if (playTimer.current !== null) window.clearInterval(playTimer.current);
      playTimer.current = null;
    };
  }, [playing, resumeLive, setScrubEnd]);

  const end = scrubEnd ?? now;
  const min = now - RANGE_MS;
  const windowStart = end - sinceHours * 3_600_000;

  const startPlayback = () => {
    // From live, play means: replay the currently visible window from its start.
    if (useStore.getState().scrubEnd === null) {
      setScrubEnd(Math.max(min, Date.now() - sinceHours * 3_600_000));
    }
    setPlaying(true);
  };

  return (
    <div className="pointer-events-auto absolute bottom-12 left-1/2 z-20 w-[min(680px,92vw)] -translate-x-1/2 border border-edge bg-panel/95 px-3 py-2">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <button
          onClick={() => (playing ? setPlaying(false) : startPlayback())}
          aria-label={playing ? "Pause timeline playback" : "Play timeline"}
          className="border border-edge px-2 py-0.5 font-mono text-xs text-muted hover:text-bone focus:outline-none focus:ring-1 focus:ring-signal"
        >
          {playing ? "⏸ pause" : "▶ play"}
        </button>
        <button
          onClick={() => resumeLive()}
          aria-pressed={scrubEnd === null}
          className={`border px-2 py-0.5 font-mono text-xs focus:outline-none focus:ring-1 focus:ring-signal ${
            scrubEnd === null
              ? "border-signal text-signal"
              : "border-edge text-muted hover:text-bone"
          }`}
        >
          LIVE
        </button>
        <div className="flex gap-1" role="radiogroup" aria-label="Window span">
          {SPANS.map(([hours, label]) => (
            <button
              key={hours}
              role="radio"
              aria-checked={sinceHours === hours}
              onClick={() => setSinceHours(hours)}
              className={`border px-1.5 py-0.5 font-mono text-[11px] focus:outline-none focus:ring-1 focus:ring-signal ${
                sinceHours === hours
                  ? "border-signal text-signal"
                  : "border-edge text-muted hover:text-bone"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
        <span className="ml-auto font-mono text-[11px] text-muted">
          {utcShort(windowStart)} → {scrubEnd === null ? "now" : utcShort(end)} UTC
        </span>
      </div>
      <input
        type="range"
        min={min}
        max={now}
        step={STEP_MS}
        value={end}
        onChange={(e) => {
          const value = Number(e.target.value);
          // Snapping the handle to the right edge is a return to live.
          if (now - value < STEP_MS) resumeLive();
          else setScrubEnd(value);
        }}
        aria-label="Timeline position (window end)"
        aria-valuetext={`window ending ${utcShort(end)} UTC`}
        className="mt-1.5 w-full accent-[#d98e32]"
      />
    </div>
  );
}
