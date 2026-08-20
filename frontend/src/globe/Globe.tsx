import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import GlobeGL, { GlobeMethods } from "react-globe.gl";
import { MeshPhongMaterial } from "three";
import { feature } from "topojson-client";
import type { Topology, GeometryCollection } from "topojson-specification";
import land110m from "world-atlas/land-110m.json";
import { useStore } from "../store";
import type { EventLite } from "../types";
import { CameraDirector, Pov } from "./CameraDirector";
import {
  ARC_GRADIENT,
  GlobePoint,
  ImpactRing,
  SIGNAL_RGB,
  StrikeArc,
  coreDot,
  eventPoint,
  hotspotPoint,
  recencyBoost,
  strikeArc,
} from "./layers";

const IDLE_ROTATE_SPEED = 0.35;
const RING_LIFETIME_MS = 2600;

interface GlobeViewProps {
  onUserInterrupt: () => void;
  onSelectEvent: (event: EventLite) => void;
  directorRef: React.MutableRefObject<CameraDirector | null>;
  getPovRef: React.MutableRefObject<(() => Pov) | null>;
  fireRingRef: React.MutableRefObject<((ring: ImpactRing) => void) | null>;
  idleRotate: boolean;
}

const landFeatures = (() => {
  const topo = land110m as unknown as Topology<{ land: GeometryCollection }>;
  const collection = feature(topo, topo.objects.land);
  return "features" in collection ? collection.features : [collection];
})();

const globeMaterial = new MeshPhongMaterial({ color: "#161b22", transparent: false });

export default function GlobeView({
  onUserInterrupt,
  onSelectEvent,
  directorRef,
  getPovRef,
  fireRingRef,
  idleRotate,
}: GlobeViewProps) {
  const globeRef = useRef<GlobeMethods | undefined>(undefined);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const events = useStore((s) => s.events);
  const hotspots = useStore((s) => s.hotspots);
  const showHotspots = useStore((s) => s.showHotspots);
  const categoryFilter = useStore((s) => s.categoryFilter);
  const minReliability = useStore((s) => s.minReliability);
  const sinceHours = useStore((s) => s.sinceHours);
  const scrubEnd = useStore((s) => s.scrubEnd);
  const showArcs = useStore((s) => s.showArcs);
  const [rings, setRings] = useState<ImpactRing[]>([]);
  const [tick, setTick] = useState(0);
  const [size, setSize] = useState({ w: window.innerWidth, h: window.innerHeight });

  // Refresh once a minute so recency glow decays without live traffic.
  useEffect(() => {
    const id = window.setInterval(() => setTick((t) => t + 1), 60_000);
    return () => window.clearInterval(id);
  }, []);

  useEffect(() => {
    const onResize = () =>
      setSize({
        w: containerRef.current?.clientWidth ?? window.innerWidth,
        h: containerRef.current?.clientHeight ?? window.innerHeight,
      });
    onResize();
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  const filteredEvents = useMemo(() => {
    void tick;
    // The visible window ends at the scrub position (or now when live) and
    // spans the selected window length backwards from there.
    const end = scrubEnd ?? Date.now();
    const start = end - sinceHours * 3_600_000;
    const rows: EventLite[] = [];
    for (const event of events.values()) {
      if (categoryFilter.size > 0 && !categoryFilter.has(event.category)) continue;
      if ((event.reliability ?? 0) < minReliability) continue;
      const occurred = Date.parse(event.occurred_at);
      if (occurred < start || occurred > end) continue;
      rows.push(event);
    }
    return rows;
  }, [events, categoryFilter, minReliability, sinceHours, scrubEnd, tick]);

  const arcs = useMemo(() => {
    if (!showArcs) return [];
    const rows: StrikeArc[] = [];
    for (const event of filteredEvents) {
      const arc = strikeArc(event);
      if (arc) rows.push(arc);
    }
    return rows;
  }, [filteredEvents, showArcs]);

  const points = useMemo(() => {
    const rows: GlobePoint[] = filteredEvents.map(eventPoint);
    if (showHotspots) for (const h of hotspots) rows.push(hotspotPoint(h));
    return rows;
  }, [filteredEvents, hotspots, showHotspots]);

  const coreDots = useMemo(() => {
    void tick;
    const now = Date.now();
    return filteredEvents
      .filter(coreDot)
      .map((event) => ({
        lat: event.lat,
        lng: event.lon,
        event,
        glow: recencyBoost(event.occurred_at, now),
      }));
  }, [filteredEvents, tick]);

  useEffect(() => {
    const globe = globeRef.current;
    if (!globe) return;
    getPovRef.current = () => globe.pointOfView() as Pov;
    directorRef.current = new CameraDirector(
      () => globe.pointOfView() as Pov,
      (pov) => globe.pointOfView(pov, 0),
      () => window.matchMedia("(prefers-reduced-motion: reduce)").matches,
    );
    fireRingRef.current = (ring) => {
      setRings((current) => [...current, ring]);
      window.setTimeout(
        () => setRings((current) => current.filter((r) => r !== ring)),
        RING_LIFETIME_MS,
      );
    };
  }, [directorRef, getPovRef, fireRingRef]);

  // Idle slow rotation is the only ambient motion, and only when live and idle.
  useEffect(() => {
    const controls = globeRef.current?.controls();
    if (!controls) return;
    controls.autoRotate = idleRotate;
    controls.autoRotateSpeed = IDLE_ROTATE_SPEED;
  }, [idleRotate]);

  // Any drag, scroll, or click cancels the flight and suspends live mode.
  useEffect(() => {
    const node = containerRef.current;
    if (!node) return;
    const interrupt = () => onUserInterrupt();
    node.addEventListener("pointerdown", interrupt);
    node.addEventListener("wheel", interrupt, { passive: true });
    return () => {
      node.removeEventListener("pointerdown", interrupt);
      node.removeEventListener("wheel", interrupt);
    };
  }, [onUserInterrupt]);

  const handlePointClick = useCallback(
    (point: object) => {
      const p = point as GlobePoint;
      if (p.kind === "event" && p.event) onSelectEvent(p.event);
    },
    [onSelectEvent],
  );

  return (
    <div ref={containerRef} className="absolute inset-0">
      <GlobeGL
        ref={globeRef}
        width={size.w}
        height={size.h}
        backgroundColor="#14181d"
        globeMaterial={globeMaterial}
        showAtmosphere={true}
        atmosphereColor="#3a4656"
        atmosphereAltitude={0.12}
        showGraticules={true}
        polygonsData={landFeatures}
        polygonCapColor={() => "#232b35"}
        polygonSideColor={() => "rgba(0,0,0,0)"}
        polygonStrokeColor={() => "#2e3946"}
        polygonAltitude={0.002}
        pointsData={points}
        pointLat={(d) => (d as GlobePoint).lat}
        pointLng={(d) => (d as GlobePoint).lng}
        pointColor={(d) => (d as GlobePoint).color}
        pointRadius={(d) => (d as GlobePoint).radiusDeg}
        pointAltitude={(d) => (d as GlobePoint).altitude}
        pointsMerge={false}
        onPointClick={handlePointClick}
        labelsData={coreDots}
        labelLat={(d) => (d as { lat: number }).lat}
        labelLng={(d) => (d as { lng: number }).lng}
        labelText={() => ""}
        labelDotRadius={(d) => 0.22 + 0.25 * (d as { glow: number }).glow}
        labelColor={(d) =>
          `rgba(${SIGNAL_RGB},${(0.75 + 0.25 * (d as { glow: number }).glow).toFixed(2)})`
        }
        labelAltitude={0.006}
        arcsData={arcs}
        arcStartLat={(d) => (d as StrikeArc).startLat}
        arcStartLng={(d) => (d as StrikeArc).startLng}
        arcEndLat={(d) => (d as StrikeArc).endLat}
        arcEndLng={(d) => (d as StrikeArc).endLng}
        arcColor={() => ARC_GRADIENT}
        arcStroke={0.32}
        arcAltitudeAutoScale={0.35}
        arcDashLength={0.035}
        arcDashGap={0.02}
        arcDashAnimateTime={0}
        ringsData={rings}
        ringLat={(d) => (d as ImpactRing).lat}
        ringLng={(d) => (d as ImpactRing).lng}
        ringMaxRadius={(d) => (d as ImpactRing).maxRadiusDeg}
        ringColor={() => (t: number) => `rgba(${SIGNAL_RGB},${(1 - t).toFixed(2)})`}
        ringPropagationSpeed={1.6}
        ringRepeatPeriod={RING_LIFETIME_MS + 400}
        ringAltitude={0.006}
      />
    </div>
  );
}
