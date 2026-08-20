import type { EventFull, EventLite, FeedHealth, FilterMeta, Hotspot } from "./types";

const BASE = "/api";

async function get<T>(path: string): Promise<T> {
  const resp = await fetch(`${BASE}${path}`);
  if (!resp.ok) throw new Error(`${path}: ${resp.status}`);
  return resp.json() as Promise<T>;
}

export async function fetchEvents(params: {
  since?: string;
  category?: string[];
  country?: string[];
  actor?: string;
  weapon?: string[];
  minReliability?: number;
} = {}): Promise<EventLite[]> {
  const q = new URLSearchParams();
  if (params.since) q.set("since", params.since);
  if (params.minReliability !== undefined)
    q.set("min_reliability", String(params.minReliability));
  if (params.actor) q.set("actor", params.actor);
  for (const c of params.category ?? []) q.append("category", c);
  for (const c of params.country ?? []) q.append("country", c);
  for (const w of params.weapon ?? []) q.append("weapon", w);
  const body = await get<{ events: EventLite[] }>(`/events?${q}`);
  return body.events;
}

export async function fetchFilterMeta(): Promise<FilterMeta> {
  return get<FilterMeta>("/meta/filters");
}

export async function fetchEvent(id: number): Promise<EventFull> {
  return get<EventFull>(`/events/${id}`);
}

export async function fetchFeedHealth(): Promise<FeedHealth[]> {
  const body = await get<{ feeds: FeedHealth[] }>("/health/feeds");
  return body.feeds;
}

export async function fetchHotspots(): Promise<Hotspot[]> {
  const body = await get<{ hotspots: Hotspot[] }>("/hotspots");
  return body.hotspots;
}

export const STREAM_URL = `${BASE}/stream/events`;
