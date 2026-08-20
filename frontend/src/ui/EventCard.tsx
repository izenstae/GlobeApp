import { useState } from "react";
import type { EventFull, Weapon } from "../types";

/** Detail card (brief §8.6). Weapons always carry their confidence qualifier
 * and expand to the literal evidence span they were extracted from. Nothing is
 * presented as more certain than the pipeline can defend. */

const CATEGORY_LABEL: Record<string, string> = {
  airstrike: "Airstrike",
  artillery: "Artillery / shelling",
  drone_strike: "Drone strike",
  missile_strike: "Missile strike",
  ied: "IED / explosive",
  small_arms: "Small arms",
  naval: "Naval",
  ground_assault: "Ground assault",
  protest: "Protest",
  riot: "Riot",
  abduction: "Abduction",
  other_violence: "Violence",
  non_kinetic: "Non-kinetic",
};

const PRECISION_LABEL: Record<string, string> = {
  exact: "exact coordinates",
  settlement: "settlement-level precision",
  admin2: "district-level precision",
  admin1: "province-level precision",
  country: "country-level precision only",
};

function relativeTime(iso: string): string {
  const deltaMs = Date.now() - Date.parse(iso);
  const minutes = Math.round(deltaMs / 60_000);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours} h ago`;
  return `${Math.round(hours / 24)} d ago`;
}

function utc(iso: string): string {
  return new Date(iso).toISOString().replace("T", " ").slice(0, 16) + " UTC";
}

function outlet(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

function WeaponRow({ weapon }: { weapon: Weapon }) {
  const [expanded, setExpanded] = useState(false);
  const qualifier =
    weapon.confidence >= 0.6 ? `reported (${weapon.method})` : "possible — low confidence";
  return (
    <li className="border-l-2 border-edge pl-2">
      <button
        className="w-full text-left hover:text-bone focus:outline-none focus:ring-1 focus:ring-signal"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
      >
        <span className={weapon.confidence >= 0.6 ? "text-bone" : "text-muted italic"}>
          {weapon.display_name}
        </span>
        <span className="ml-2 font-mono text-xs text-faint">
          {qualifier} · {weapon.confidence.toFixed(2)}
        </span>
      </button>
      {expanded && weapon.evidence_span && (
        <blockquote className="mt-1 border-l border-faint pl-2 font-mono text-xs text-muted">
          “…{weapon.evidence_span}…”
        </blockquote>
      )}
      {expanded && !weapon.evidence_span && (
        <p className="mt-1 font-mono text-xs text-faint">no evidence span recorded</p>
      )}
    </li>
  );
}

function ActorLine({ raw, canonical }: { raw: string | null; canonical: string | null }) {
  if (!raw && !canonical) return null;
  return (
    <div>
      <span className="text-bone">{canonical ?? raw}</span>
      {!canonical && raw && (
        <span className="ml-2 font-mono text-xs text-faint">unmapped source string</span>
      )}
      {canonical && raw && raw !== canonical && (
        <div className="font-mono text-xs text-faint">source: “{raw}”</div>
      )}
    </div>
  );
}

export default function EventCard({
  event,
  onClose,
}: {
  event: EventFull;
  onClose: () => void;
}) {
  return (
    <aside
      className="card-in pointer-events-auto absolute right-4 top-4 z-20 max-h-[calc(100vh-8rem)] w-96 overflow-y-auto border border-edge bg-panel/95 p-4 text-sm shadow-xl"
      role="dialog"
      aria-label={`Event detail: ${CATEGORY_LABEL[event.category] ?? event.category}`}
    >
      <div className="flex items-start justify-between">
        <div>
          <div className="text-base font-medium text-bone">
            {CATEGORY_LABEL[event.category] ?? event.category}
          </div>
          <div className="font-mono text-xs text-muted" title={utc(event.occurred_at)}>
            {relativeTime(event.occurred_at)} · {utc(event.occurred_at)}
          </div>
        </div>
        <button
          onClick={onClose}
          aria-label="Close event card"
          className="ml-2 px-2 text-muted hover:text-bone focus:outline-none focus:ring-1 focus:ring-signal"
        >
          ✕
        </button>
      </div>

      <div className="mt-3">
        <div className="text-bone">
          {event.location_name ? `near ${event.location_name}` : "location unnamed"}
          {event.country ? `, ${event.country}` : ""}
        </div>
        <div className="font-mono text-xs text-muted">
          {PRECISION_LABEL[event.geo_precision]}
          {event.geo_radius_m ? ` (±${Math.round(event.geo_radius_m / 1000)} km)` : ""}
        </div>
        <div className="font-mono text-xs text-faint">
          {event.lat.toFixed(4)}, {event.lon.toFixed(4)}
        </div>
      </div>

      {event.origin_country && (
        <div className="mt-3">
          <div className="text-xs uppercase tracking-wide text-faint">
            Launch origin — inferred
          </div>
          <div className="text-muted italic">{event.origin_country}</div>
          <div className="font-mono text-xs text-faint">
            country-level inference from actor attribution
            {event.origin_confidence !== null &&
              ` · confidence ${event.origin_confidence.toFixed(2)}`}
          </div>
        </div>
      )}

      {(event.actor_a || event.actor_b) && (
        <div className="mt-3 space-y-1">
          <div className="text-xs uppercase tracking-wide text-faint">Actors</div>
          <ActorLine raw={event.actor_a} canonical={event.actor_a_canonical} />
          <ActorLine raw={event.actor_b} canonical={event.actor_b_canonical} />
        </div>
      )}

      <div className="mt-3">
        <div className="text-xs uppercase tracking-wide text-faint">Weapons</div>
        {event.weapons.length > 0 ? (
          <ul className="mt-1 space-y-2">
            {event.weapons.map((w) => (
              <WeaponRow key={w.weapon_key} weapon={w} />
            ))}
          </ul>
        ) : (
          <div className="text-muted">not specified</div>
        )}
      </div>

      {event.fatalities !== null && (
        <div className="mt-3">
          <span className="text-xs uppercase tracking-wide text-faint">Fatalities </span>
          <span className="font-mono text-bone">{event.fatalities}</span>
        </div>
      )}

      <div className="mt-3" title={event.reliability_explanation ?? "single source"}>
        <span className="text-xs uppercase tracking-wide text-faint">Reliability </span>
        <span className="font-mono text-bone">
          {event.reliability !== null ? event.reliability.toFixed(2) : "—"}
        </span>
        {event.thermal_corroborated && (
          <span className="ml-2 border border-thermal px-1 font-mono text-xs text-bone">
            thermal signature corroborated
          </span>
        )}
        {event.reliability_explanation && (
          <div className="font-mono text-xs text-muted">{event.reliability_explanation}</div>
        )}
      </div>

      {event.notes && <p className="mt-3 text-muted">{event.notes}</p>}

      {event.source_urls.length > 0 && (
        <div className="mt-3">
          <div className="text-xs uppercase tracking-wide text-faint">
            Sources ({event.source_count})
          </div>
          <ul className="mt-1 space-y-0.5">
            {event.source_urls.slice(0, 12).map((url) => (
              <li key={url}>
                <a
                  href={url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="font-mono text-xs text-muted underline decoration-faint hover:text-signal"
                >
                  {outlet(url)}
                </a>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="mt-3 font-mono text-xs text-faint">
        via {event.sources.join(", ")} · event #{event.id}
        {event.cluster_id !== null && ` · cluster #${event.cluster_id}`}
      </div>
    </aside>
  );
}
