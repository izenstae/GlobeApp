import type { EventLite, Hotspot } from "../types";
import type { Pov } from "./CameraDirector";

/** The signature element is the uncertainty radius: every marker's footprint is
 * drawn at its true reported precision. A country-centroid event is a large
 * soft disc; an exact-coordinate event is a tight point. Saturation encodes
 * reliability and nothing else. */

export const SIGNAL_RGB = "217,142,50"; // restrained amber
export const THERMAL_RGB = "138,90,74";

const KM_PER_DEGREE = 111;

export interface GlobePoint {
  kind: "event" | "hotspot";
  id: number;
  lat: number;
  lng: number;
  radiusDeg: number;
  color: string;
  altitude: number;
  event?: EventLite;
}

export function uncertaintyRadiusDeg(radiusM: number | null): number {
  const km = (radiusM ?? 10_000) / 1000;
  return Math.max(km / KM_PER_DEGREE, 0.12);
}

export function eventFillAlpha(reliability: number | null): number {
  // Low confidence renders faint — closer to an unfilled ring than a claim.
  const r = reliability ?? 0.25;
  return 0.08 + 0.5 * Math.min(Math.max(r, 0), 1);
}

export function eventPoint(event: EventLite): GlobePoint {
  return {
    kind: "event",
    id: event.id,
    lat: event.lat,
    lng: event.lon,
    radiusDeg: uncertaintyRadiusDeg(event.geo_radius_m),
    color: `rgba(${SIGNAL_RGB},${eventFillAlpha(event.reliability).toFixed(3)})`,
    altitude: 0.004,
    event,
  };
}

export function hotspotPoint(h: Hotspot): GlobePoint {
  return {
    kind: "hotspot",
    id: h.id,
    lat: h.lat,
    lng: h.lon,
    radiusDeg: 0.13,
    color: `rgba(${THERMAL_RGB},0.55)`,
    altitude: 0.002,
  };
}

/** Solid core dot only for events reliable enough to assert a location. */
export function coreDot(event: EventLite): boolean {
  return (event.reliability ?? 0) >= 0.5;
}

/** Recent events glow and decay over their first hour. */
export function recencyBoost(occurredAt: string, now: number): number {
  const ageMs = now - Date.parse(occurredAt);
  if (ageMs < 0 || ageMs > 3_600_000) return 0;
  return 1 - ageMs / 3_600_000;
}

const VISIBLE_BASE_DEG = 22;
const VISIBLE_PER_ALTITUDE_DEG = 38;

/** Rough viewport test: is the target within the cone the camera can see AND
 * is the camera already near presentation zoom? Both must hold to dequeue an
 * event without a camera move — from high altitude the whole hemisphere is
 * "on screen", but the display should still descend to the event. */
export function isPresented(pov: Pov, lat: number, lng: number, targetAltitude: number): boolean {
  return pov.altitude <= targetAltitude * 1.6 && isOnScreen(pov, lat, lng);
}

export function isOnScreen(pov: Pov, lat: number, lng: number): boolean {
  const toRad = Math.PI / 180;
  const a =
    Math.sin((lat * toRad) / 1) * Math.sin(pov.lat * toRad) +
    Math.cos(lat * toRad) * Math.cos(pov.lat * toRad) * Math.cos((lng - pov.lng) * toRad);
  const angularDeg = Math.acos(Math.min(Math.max(a, -1), 1)) / toRad;
  const visible = VISIBLE_BASE_DEG + VISIBLE_PER_ALTITUDE_DEG * Math.min(pov.altitude, 2);
  return angularDeg < visible;
}

export interface ImpactRing {
  lat: number;
  lng: number;
  maxRadiusDeg: number;
  firedAt: number;
}

export function impactRing(event: { lat: number; lon: number; geo_radius_m: number | null }): ImpactRing {
  return {
    lat: event.lat,
    lng: event.lon,
    // Sized to geo_radius_m so the animation itself communicates uncertainty.
    maxRadiusDeg: Math.max(uncertaintyRadiusDeg(event.geo_radius_m) * 1.6, 1.2),
    firedAt: Date.now(),
  };
}
