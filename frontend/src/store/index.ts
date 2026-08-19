import { create } from "zustand";
import type { EventFull, EventLite, FeedHealth, Hotspot } from "../types";

export type LiveMode = "live" | "paused";

interface AppState {
  events: Map<number, EventLite>;
  selected: EventFull | null;
  feeds: FeedHealth[];
  hotspots: Hotspot[];
  showHotspots: boolean;
  liveMode: LiveMode;
  /** epoch ms when auto-resume fires, null when live */
  resumeAt: number | null;
  queueDepth: number;
  queueOpen: boolean;
  categoryFilter: Set<string>;
  minReliability: number;
  sinceHours: number;
  streamConnected: boolean;

  addEvents: (rows: EventLite[]) => void;
  upsertLive: (event: EventFull) => void;
  select: (event: EventFull | null) => void;
  setFeeds: (feeds: FeedHealth[]) => void;
  setHotspots: (rows: Hotspot[]) => void;
  toggleHotspots: () => void;
  pauseLive: () => void;
  resumeLive: () => void;
  setResumeAt: (at: number | null) => void;
  setQueueDepth: (depth: number) => void;
  setQueueOpen: (open: boolean) => void;
  setCategoryFilter: (categories: Set<string>) => void;
  setMinReliability: (value: number) => void;
  setSinceHours: (hours: number) => void;
  setStreamConnected: (connected: boolean) => void;
}

function toLite(event: EventFull): EventLite {
  return { ...event };
}

export const useStore = create<AppState>((set) => ({
  events: new Map(),
  selected: null,
  feeds: [],
  hotspots: [],
  showHotspots: false,
  liveMode: "live",
  resumeAt: null,
  queueDepth: 0,
  queueOpen: false,
  categoryFilter: new Set(),
  minReliability: 0,
  sinceHours: 24 * 14,
  streamConnected: false,

  addEvents: (rows) =>
    set((s) => {
      const events = new Map(s.events);
      for (const row of rows) events.set(row.id, row);
      return { events };
    }),
  upsertLive: (event) =>
    set((s) => {
      const events = new Map(s.events);
      events.set(event.id, toLite(event));
      return { events };
    }),
  select: (event) => set({ selected: event }),
  setFeeds: (feeds) => set({ feeds }),
  setHotspots: (hotspots) => set({ hotspots }),
  toggleHotspots: () => set((s) => ({ showHotspots: !s.showHotspots })),
  pauseLive: () => set({ liveMode: "paused" }),
  resumeLive: () => set({ liveMode: "live", resumeAt: null }),
  setResumeAt: (resumeAt) => set({ resumeAt }),
  setQueueDepth: (queueDepth) => set({ queueDepth }),
  setQueueOpen: (queueOpen) => set({ queueOpen }),
  setCategoryFilter: (categoryFilter) => set({ categoryFilter }),
  setMinReliability: (minReliability) => set({ minReliability }),
  setSinceHours: (sinceHours) => set({ sinceHours }),
  setStreamConnected: (streamConnected) => set({ streamConnected }),
}));
