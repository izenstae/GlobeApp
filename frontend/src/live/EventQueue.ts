import type { EventCategory, EventFull } from "../types";

/** Arrival buffer: three events can land in the same second, the camera can
 * only be in one place. Weighted priority; bounded depth. */

const MAX_DEPTH = 50;

const CATEGORY_SEVERITY: Record<EventCategory, number> = {
  missile_strike: 1.0,
  airstrike: 0.95,
  drone_strike: 0.9,
  artillery: 0.8,
  ied: 0.8,
  ground_assault: 0.7,
  naval: 0.7,
  small_arms: 0.55,
  abduction: 0.5,
  riot: 0.35,
  other_violence: 0.4,
  protest: 0.2,
  non_kinetic: 0.1,
};

export interface QueuedEvent {
  event: EventFull;
  enqueuedAt: number;
  priority: number;
}

export function computePriority(event: EventFull, now: number): number {
  const ageMinutes = Math.max(0, (now - Date.parse(event.occurred_at)) / 60_000);
  const recency = Math.exp(-ageMinutes / (60 * 24)); // ~day half-life
  const fatality = Math.min((event.fatalities ?? 0) / 20, 1);
  const reliability = event.reliability ?? 0.3;
  const severity = CATEGORY_SEVERITY[event.category] ?? 0.4;
  return 0.3 * recency + 0.25 * fatality + 0.2 * reliability + 0.25 * severity;
}

export class EventQueue {
  private items: QueuedEvent[] = [];
  private listeners = new Set<() => void>();

  get depth(): number {
    return this.items.length;
  }

  list(): readonly QueuedEvent[] {
    return this.items;
  }

  onChange(fn: () => void): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  private emit() {
    for (const fn of this.listeners) fn();
  }

  enqueue(event: EventFull): void {
    if (this.items.some((q) => q.event.id === event.id)) return;
    const now = Date.now();
    this.items.push({ event, enqueuedAt: now, priority: computePriority(event, now) });
    this.items.sort((a, b) => b.priority - a.priority);
    if (this.items.length > MAX_DEPTH) this.items.length = MAX_DEPTH; // drop lowest
    this.emit();
  }

  /** Pop the highest-priority event. Events already visible in the viewport are
   * dequeued without a camera move (flying to somewhere on screen looks broken):
   * `isVisible` marks those, and they are returned with `flyTo: false`. */
  dequeue(isVisible: (event: EventFull) => boolean): { event: EventFull; flyTo: boolean } | null {
    while (this.items.length > 0) {
      const next = this.items.shift()!;
      this.emit();
      return { event: next.event, flyTo: !isVisible(next.event) };
    }
    return null;
  }

  clear(): void {
    this.items = [];
    this.emit();
  }
}
