import { Quaternion, Vector3 } from "three";

/** Flight choreography (brief §8.3):
 *  1. pull back  — altitude eases out to ~2.5x over 400ms
 *  2. rotate     — great-circle quaternion slerp (never naive lat/lng lerp,
 *                  which wobbles near the poles); 900–2200ms by angular
 *                  distance, easeInOutCubic
 *  3. descend    — 600ms ease-in to target zoom, overlapping the last 200ms
 *                  of rotation
 * Any user input cancels instantly with no snap-back: the camera simply stays
 * where the interrupted frame left it.
 */

export interface Pov {
  lat: number;
  lng: number;
  altitude: number;
}

const PULLBACK_MS = 400;
const ROTATE_MIN_MS = 900;
const ROTATE_MAX_MS = 2200;
const DESCEND_MS = 600;
const DESCEND_OVERLAP_MS = 200;
const PULLBACK_FACTOR = 2.5;
const MAX_ALTITUDE = 3.2;

export type FlightResult = "completed" | "cancelled";

function easeInOutCubic(t: number): number {
  return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
}

function toVector(lat: number, lng: number): Vector3 {
  const phi = (90 - lat) * (Math.PI / 180);
  const theta = (lng + 180) * (Math.PI / 180);
  return new Vector3(
    -Math.sin(phi) * Math.cos(theta),
    Math.cos(phi),
    Math.sin(phi) * Math.sin(theta),
  );
}

function toLatLng(v: Vector3): { lat: number; lng: number } {
  const lat = 90 - Math.acos(v.y / v.length()) * (180 / Math.PI);
  const lng = ((270 + Math.atan2(v.x, v.z) * (180 / Math.PI)) % 360) - 180;
  return { lat, lng };
}

export class CameraDirector {
  private raf: number | null = null;
  private cancelFlight: (() => void) | null = null;

  constructor(
    private getPov: () => Pov,
    private setPov: (pov: Pov) => void,
    private prefersReducedMotion: () => boolean,
  ) {}

  get flying(): boolean {
    return this.raf !== null;
  }

  cancel(): void {
    if (this.raf !== null) cancelAnimationFrame(this.raf);
    this.raf = null;
    this.cancelFlight?.();
    this.cancelFlight = null;
  }

  flyTo(target: Pov): Promise<FlightResult> {
    this.cancel();

    if (this.prefersReducedMotion()) {
      // Reduced motion: hard cut. The feature still works, it just does not move.
      this.setPov(target);
      return Promise.resolve("completed");
    }

    const start = this.getPov();
    const v0 = toVector(start.lat, start.lng);
    const v1 = toVector(target.lat, target.lng);
    const angle = v0.angleTo(v1);
    const rotateMs =
      ROTATE_MIN_MS + (ROTATE_MAX_MS - ROTATE_MIN_MS) * Math.min(angle / Math.PI, 1);
    const rotation = new Quaternion().setFromUnitVectors(v0, v1);
    const identity = new Quaternion();

    const pulledAltitude = Math.min(
      Math.max(start.altitude * PULLBACK_FACTOR, target.altitude),
      MAX_ALTITUDE,
    );
    const rotateStart = PULLBACK_MS;
    const descendStart = rotateStart + rotateMs - DESCEND_OVERLAP_MS;
    const total = descendStart + DESCEND_MS;

    return new Promise<FlightResult>((resolve) => {
      this.cancelFlight = () => resolve("cancelled");
      const t0 = performance.now();

      const frame = (now: number) => {
        const t = now - t0;

        let altitude: number;
        if (t < rotateStart) {
          altitude =
            start.altitude +
            (pulledAltitude - start.altitude) * easeInOutCubic(Math.min(t / PULLBACK_MS, 1));
        } else if (t < descendStart) {
          altitude = pulledAltitude;
        } else {
          altitude =
            pulledAltitude +
            (target.altitude - pulledAltitude) *
              easeInOutCubic(Math.min((t - descendStart) / DESCEND_MS, 1));
        }

        const rotateT = Math.min(Math.max((t - rotateStart) / rotateMs, 0), 1);
        const q = identity.clone().slerp(rotation, easeInOutCubic(rotateT));
        const position = toLatLng(v0.clone().applyQuaternion(q));

        this.setPov({ ...position, altitude });

        if (t >= total) {
          this.raf = null;
          this.cancelFlight = null;
          this.setPov(target);
          resolve("completed");
          return;
        }
        this.raf = requestAnimationFrame(frame);
      };
      this.raf = requestAnimationFrame(frame);
    });
  }
}
