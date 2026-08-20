import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { fetchEvent, fetchEvents, fetchFeedHealth, fetchFilterMeta, fetchHotspots } from "./api";
import { CameraDirector, Pov } from "./globe/CameraDirector";
import GlobeView from "./globe/Globe";
import { ImpactRing, impactRing, isPresented, uncertaintyRadiusDeg } from "./globe/layers";
import { EventQueue } from "./live/EventQueue";
import { useEventStream } from "./live/useEventStream";
import { useStore } from "./store";
import type { EventFull, EventLite } from "./types";
import EmptyState from "./ui/EmptyState";
import EventCard from "./ui/EventCard";
import FilterPanel from "./ui/FilterPanel";
import QueueList from "./ui/QueueList";
import StatusBar from "./ui/StatusBar";
import TimeScrubber from "./ui/TimeScrubber";

const AUTO_RESUME_MS = 45_000;
const BASE_DWELL_MS = 8_000;
const MAX_DWELL_MS = 15_000;

function targetAltitude(event: EventFull): number {
  const radiusDeg = uncertaintyRadiusDeg(event.geo_radius_m);
  return Math.min(Math.max(0.3 + radiusDeg / 18, 0.32), 1.4);
}

function dwellFor(event: EventFull): number {
  const extra = Math.min((event.fatalities ?? 0) * 250, MAX_DWELL_MS - BASE_DWELL_MS);
  return BASE_DWELL_MS + extra;
}

export default function App() {
  const queue = useMemo(() => new EventQueue(), []);
  useEventStream(queue);

  const directorRef = useRef<CameraDirector | null>(null);
  const getPovRef = useRef<(() => Pov) | null>(null);
  const fireRingRef = useRef<((ring: ImpactRing) => void) | null>(null);
  const dwellTimer = useRef<number | null>(null);
  const stepping = useRef(false);
  const [announcement, setAnnouncement] = useState("");

  const liveMode = useStore((s) => s.liveMode);
  const resumeAt = useStore((s) => s.resumeAt);
  const queueDepth = useStore((s) => s.queueDepth);
  const selected = useStore((s) => s.selected);
  const showHotspots = useStore((s) => s.showHotspots);
  const replaceEvents = useStore((s) => s.replaceEvents);
  const countryFilter = useStore((s) => s.countryFilter);
  const actorFilter = useStore((s) => s.actorFilter);
  const weaponFilter = useStore((s) => s.weaponFilter);
  const setFilterMeta = useStore((s) => s.setFilterMeta);
  const select = useStore((s) => s.select);
  const setFeeds = useStore((s) => s.setFeeds);
  const setHotspots = useStore((s) => s.setHotspots);
  const pauseLive = useStore((s) => s.pauseLive);
  const resumeLive = useStore((s) => s.resumeLive);
  const setResumeAt = useStore((s) => s.setResumeAt);
  const setQueueOpen = useStore((s) => s.setQueueOpen);

  // ---------------------------------------------------------- initial loads

  // Events load whenever a server-side filter changes (country/actor/weapon
  // need data the light rows don't carry, so the server does the matching).
  useEffect(() => {
    fetchEvents({
      country: [...countryFilter],
      actor: actorFilter || undefined,
      weapon: [...weaponFilter],
    })
      .then(replaceEvents)
      .catch(() => {});
  }, [countryFilter, actorFilter, weaponFilter, replaceEvents]);

  useEffect(() => {
    const health = () => fetchFeedHealth().then(setFeeds).catch(() => {});
    health();
    const id = window.setInterval(health, 30_000);
    return () => window.clearInterval(id);
  }, [setFeeds]);

  useEffect(() => {
    const meta = () => fetchFilterMeta().then(setFilterMeta).catch(() => {});
    meta();
    const id = window.setInterval(meta, 5 * 60_000);
    return () => window.clearInterval(id);
  }, [setFilterMeta]);

  useEffect(() => {
    if (!showHotspots) return;
    fetchHotspots().then(setHotspots).catch(() => {});
    const id = window.setInterval(
      () => fetchHotspots().then(setHotspots).catch(() => {}),
      10 * 60_000,
    );
    return () => window.clearInterval(id);
  }, [showHotspots, setHotspots]);

  // ------------------------------------------------------------ live camera

  const presentEvent = useCallback(
    (event: EventFull, flew: boolean) => {
      fireRingRef.current?.(impactRing(event));
      // Card slides in after the ring fires.
      window.setTimeout(() => select(event), flew ? 150 : 0);
      setAnnouncement(
        `New event: ${event.category} ${
          event.location_name ? `near ${event.location_name}` : ""
        } ${event.country ?? ""}`.trim(),
      );
    },
    [select],
  );

  const stepQueue = useCallback(async () => {
    if (stepping.current) return;
    const director = directorRef.current;
    const getPov = getPovRef.current;
    if (!director || !getPov) return;
    if (useStore.getState().liveMode !== "live") return;

    const next = queue.dequeue((event) =>
      isPresented(getPov(), event.lat, event.lon, targetAltitude(event)),
    );
    if (!next) return;
    stepping.current = true;

    if (next.flyTo) {
      const result = await director.flyTo({
        lat: next.event.lat,
        lng: next.event.lon,
        altitude: targetAltitude(next.event),
      });
      if (result === "cancelled") {
        stepping.current = false;
        return;
      }
    }
    presentEvent(next.event, next.flyTo);

    dwellTimer.current = window.setTimeout(() => {
      dwellTimer.current = null;
      stepping.current = false;
      void stepQueue();
    }, dwellFor(next.event));
  }, [queue, presentEvent]);

  useEffect(() => {
    if (liveMode === "live" && queueDepth > 0) void stepQueue();
  }, [liveMode, queueDepth, stepQueue]);

  // ---------------------------------------------------------- user interrupt

  const handleInterrupt = useCallback(() => {
    // Immediately cancel the flight and suspend live mode. Not optional.
    directorRef.current?.cancel();
    if (dwellTimer.current !== null) {
      window.clearTimeout(dwellTimer.current);
      dwellTimer.current = null;
    }
    stepping.current = false;
    pauseLive();
    // While scrubbing history there is no auto-resume countdown: yanking the
    // timeline back to live mid-examination would be a surprise.
    if (useStore.getState().scrubEnd === null) {
      setResumeAt(Date.now() + AUTO_RESUME_MS);
    }
  }, [pauseLive, setResumeAt]);

  // Auto-resume with a visible countdown so it is never a surprise.
  useEffect(() => {
    if (liveMode !== "paused" || resumeAt === null) return;
    const id = window.setInterval(() => {
      const remaining = resumeAt - Date.now();
      if (remaining <= 0) resumeLive();
      else setResumeAt(resumeAt); // trigger countdown rerender
    }, 500);
    return () => window.clearInterval(id);
  }, [liveMode, resumeAt, resumeLive, setResumeAt]);

  const handleResume = useCallback(() => {
    resumeLive();
  }, [resumeLive]);

  // ------------------------------------------------------------- selection

  const handleSelectEvent = useCallback(
    (event: EventLite) => {
      handleInterrupt();
      fetchEvent(event.id)
        .then(select)
        .catch(() => {});
    },
    [handleInterrupt, select],
  );

  const handleJumpTo = useCallback(
    (eventId: number) => {
      setQueueOpen(false);
      fetchEvent(eventId)
        .then((event) => {
          select(event);
          void directorRef.current?.flyTo({
            lat: event.lat,
            lng: event.lon,
            altitude: targetAltitude(event),
          });
        })
        .catch(() => {});
    },
    [select, setQueueOpen],
  );

  const idleRotate = liveMode === "live" && queueDepth === 0 && !stepping.current;

  return (
    <div className="relative h-screen w-screen overflow-hidden bg-base font-ui text-bone">
      <GlobeView
        onUserInterrupt={handleInterrupt}
        onSelectEvent={handleSelectEvent}
        directorRef={directorRef}
        getPovRef={getPovRef}
        fireRingRef={fireRingRef}
        idleRotate={idleRotate}
      />
      <EmptyState />
      <FilterPanel />
      <TimeScrubber />
      {selected && <EventCard event={selected} onClose={() => select(null)} />}
      <QueueList queue={queue} onJumpTo={handleJumpTo} />
      <StatusBar
        onResume={handleResume}
        onToggleQueue={() => setQueueOpen(!useStore.getState().queueOpen)}
      />
      {/* Screen-reader mirror of globe activity */}
      <div aria-live="polite" className="sr-only">
        {announcement}
      </div>
    </div>
  );
}
