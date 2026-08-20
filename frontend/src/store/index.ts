import { create } from "zustand";
import type { EventFull, EventLite, FeedHealth, FilterMeta, Hotspot } from "../types";

export type LiveMode = "live" | "paused";

interface AppState {
  events: Map<number, EventLite>;
  selected: EventFull | null;
  feeds: FeedHealth[];
  hotspots: Hotspot[];
  showHotspots: boolean;
  showArcs: boolean;
  liveMode: LiveMode;
  /** epoch ms when auto-resume fires, null when live */
  resumeAt: number | null;
  queueDepth: number;
  queueOpen: boolean;
  categoryFilter: Set<string>;
  minReliability: number;
  sinceHours: number;
  /** Scrubbed window end (epoch ms); null = tracking now. Setting a value
   * suspends live mode without an auto-resume countdown — returning to live
   * is an explicit act, never a surprise while examining history. */
  scrubEnd: number | null;
  /** Server-side filters (need data the light rows don't carry). */
  countryFilter: Set<string>;
  actorFilter: string;
  weaponFilter: Set<string>;
  filterMeta: FilterMeta | null;
  streamConnected: boolean;

  addEvents: (rows: EventLite[]) => void;
  replaceEvents: (rows: EventLite[]) => void;
  upsertLive: (event: EventFull) => void;
  select: (event: EventFull | null) => void;
  setFeeds: (feeds: FeedHealth[]) => void;
  setHotspots: (rows: Hotspot[]) => void;
  toggleHotspots: () => void;
  toggleArcs: () => void;
  pauseLive: () => void;
  resumeLive: () => void;
  setResumeAt: (at: number | null) => void;
  setQueueDepth: (depth: number) => void;
  setQueueOpen: (open: boolean) => void;
  setCategoryFilter: (categories: Set<string>) => void;
  setMinReliability: (value: number) => void;
  setSinceHours: (hours: number) => void;
  setScrubEnd: (end: number | null) => void;
  setCountryFilter: (countries: Set<string>) => void;
  setActorFilter: (actor: string) => void;
  setWeaponFilter: (weapons: Set<string>) => void;
  setFilterMeta: (meta: FilterMeta) => void;
  setStreamConnected: (connected: boolean) => void;
}

function toLite(event: EventFull): EventLite {
  return { ...event };
}

/** Do the active server-side filters admit this live event? The SSE payload is
 * full, so the check mirrors the backend's semantics client-side; without it a
 * filtered view would silently accumulate events the filter excludes. */
export function passesServerFilters(
  state: Pick<AppState, "countryFilter" | "actorFilter" | "weaponFilter">,
  event: EventFull,
): boolean {
  if (state.countryFilter.size > 0) {
    const country = event.country?.toLowerCase();
    if (!country) return false;
    let hit = false;
    for (const c of state.countryFilter) if (c.toLowerCase() === country) hit = true;
    if (!hit) return false;
  }
  if (state.actorFilter.trim()) {
    const pat = state.actorFilter.trim().toLowerCase();
    const fields = [
      event.actor_a,
      event.actor_b,
      event.actor_a_canonical,
      event.actor_b_canonical,
    ];
    if (!fields.some((f) => f?.toLowerCase().includes(pat))) return false;
  }
  if (state.weaponFilter.size > 0) {
    if (!event.weapons?.some((w) => state.weaponFilter.has(w.weapon_key))) return false;
  }
  return true;
}

export const useStore = create<AppState>((set) => ({
  events: new Map(),
  selected: null,
  feeds: [],
  hotspots: [],
  showHotspots: false,
  showArcs: true,
  liveMode: "live",
  resumeAt: null,
  queueDepth: 0,
  queueOpen: false,
  categoryFilter: new Set(),
  minReliability: 0,
  sinceHours: 24 * 14,
  scrubEnd: null,
  countryFilter: new Set(),
  actorFilter: "",
  weaponFilter: new Set(),
  filterMeta: null,
  streamConnected: false,

  addEvents: (rows) =>
    set((s) => {
      const events = new Map(s.events);
      for (const row of rows) events.set(row.id, row);
      return { events };
    }),
  replaceEvents: (rows) => set({ events: new Map(rows.map((r) => [r.id, r])) }),
  upsertLive: (event) =>
    set((s) => {
      if (!passesServerFilters(s, event)) return s;
      const events = new Map(s.events);
      events.set(event.id, toLite(event));
      return { events };
    }),
  select: (event) => set({ selected: event }),
  setFeeds: (feeds) => set({ feeds }),
  setHotspots: (hotspots) => set({ hotspots }),
  toggleHotspots: () => set((s) => ({ showHotspots: !s.showHotspots })),
  toggleArcs: () => set((s) => ({ showArcs: !s.showArcs })),
  pauseLive: () => set({ liveMode: "paused" }),
  // Returning to live also returns the timeline to now: "LIVE" means both.
  resumeLive: () => set({ liveMode: "live", resumeAt: null, scrubEnd: null }),
  setResumeAt: (resumeAt) => set({ resumeAt }),
  setQueueDepth: (queueDepth) => set({ queueDepth }),
  setQueueOpen: (queueOpen) => set({ queueOpen }),
  setCategoryFilter: (categoryFilter) => set({ categoryFilter }),
  setMinReliability: (minReliability) => set({ minReliability }),
  setSinceHours: (sinceHours) => set({ sinceHours }),
  setScrubEnd: (scrubEnd) =>
    set(scrubEnd === null ? { scrubEnd } : { scrubEnd, liveMode: "paused", resumeAt: null }),
  setCountryFilter: (countryFilter) => set({ countryFilter }),
  setActorFilter: (actorFilter) => set({ actorFilter }),
  setWeaponFilter: (weaponFilter) => set({ weaponFilter }),
  setFilterMeta: (filterMeta) => set({ filterMeta }),
  setStreamConnected: (streamConnected) => set({ streamConnected }),
}));
