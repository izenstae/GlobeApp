import { useEffect, useState } from "react";
import { useStore } from "../store";

/** Filters (Phase 6): category, country, actor, weapon, reliability floor.
 * Country/actor/weapon options come from /meta/filters — only vocabulary that
 * actually occurs in ingested data is ever offered. */

const CATEGORIES: [string, string][] = [
  ["airstrike", "Airstrike"],
  ["missile_strike", "Missile strike"],
  ["drone_strike", "Drone strike"],
  ["artillery", "Artillery"],
  ["ied", "IED"],
  ["small_arms", "Small arms"],
  ["ground_assault", "Ground assault"],
  ["naval", "Naval"],
  ["abduction", "Abduction"],
  ["riot", "Riot"],
  ["protest", "Protest"],
  ["other_violence", "Other violence"],
  ["non_kinetic", "Non-kinetic"],
];

const ACTOR_DEBOUNCE_MS = 400;
const WEAPONS_SHOWN = 10;

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="mb-1 font-mono text-xs uppercase tracking-wide text-faint">{children}</div>
  );
}

function CountryFilter() {
  const countryFilter = useStore((s) => s.countryFilter);
  const setCountryFilter = useStore((s) => s.setCountryFilter);
  const meta = useStore((s) => s.filterMeta);
  const [draft, setDraft] = useState("");

  const add = (name: string) => {
    const known = meta?.countries.find((c) => c.toLowerCase() === name.trim().toLowerCase());
    if (!known || countryFilter.has(known)) return;
    setCountryFilter(new Set(countryFilter).add(known));
    setDraft("");
  };
  const remove = (name: string) => {
    const next = new Set(countryFilter);
    next.delete(name);
    setCountryFilter(next);
  };

  return (
    <div>
      <SectionLabel>Country</SectionLabel>
      {countryFilter.size > 0 && (
        <div className="mb-1 flex flex-wrap gap-1">
          {[...countryFilter].map((name) => (
            <button
              key={name}
              onClick={() => remove(name)}
              aria-label={`Remove country filter ${name}`}
              className="border border-signal px-1.5 py-0.5 font-mono text-[11px] text-signal hover:bg-signal hover:text-base focus:outline-none focus:ring-1 focus:ring-signal"
            >
              {name} ✕
            </button>
          ))}
        </div>
      )}
      <input
        list="country-options"
        value={draft}
        onChange={(e) => {
          setDraft(e.target.value);
          // Datalist selection lands as a change event with the full value.
          if (meta?.countries.some((c) => c.toLowerCase() === e.target.value.toLowerCase()))
            add(e.target.value);
        }}
        onKeyDown={(e) => e.key === "Enter" && add(draft)}
        placeholder={meta && meta.countries.length > 0 ? "add a country…" : "no data yet"}
        aria-label="Add country filter"
        className="w-full border border-edge bg-base px-2 py-1 font-mono text-xs text-bone placeholder:text-faint focus:outline-none focus:ring-1 focus:ring-signal"
      />
      <datalist id="country-options">
        {meta?.countries.map((c) => <option key={c} value={c} />)}
      </datalist>
    </div>
  );
}

function ActorFilter() {
  const actorFilter = useStore((s) => s.actorFilter);
  const setActorFilter = useStore((s) => s.setActorFilter);
  const meta = useStore((s) => s.filterMeta);
  const [draft, setDraft] = useState(actorFilter);

  useEffect(() => {
    const id = window.setTimeout(() => setActorFilter(draft.trim()), ACTOR_DEBOUNCE_MS);
    return () => window.clearTimeout(id);
  }, [draft, setActorFilter]);

  // External clears ("clear all filters") reset the input too.
  useEffect(() => {
    if (actorFilter === "") setDraft((d) => (d.trim() === "" ? d : ""));
  }, [actorFilter]);

  return (
    <div>
      <SectionLabel>Actor</SectionLabel>
      <input
        list="actor-options"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        placeholder="name contains…"
        aria-label="Actor filter (substring)"
        className="w-full border border-edge bg-base px-2 py-1 font-mono text-xs text-bone placeholder:text-faint focus:outline-none focus:ring-1 focus:ring-signal"
      />
      <datalist id="actor-options">
        {meta?.actors.slice(0, 100).map((a) => <option key={a} value={a} />)}
      </datalist>
      <p className="mt-1 font-mono text-[10px] text-faint">
        matches raw and canonical names, all cluster members
      </p>
    </div>
  );
}

function WeaponFilter() {
  const weaponFilter = useStore((s) => s.weaponFilter);
  const setWeaponFilter = useStore((s) => s.setWeaponFilter);
  const meta = useStore((s) => s.filterMeta);
  const weapons = meta?.weapons ?? [];

  const toggle = (key: string) => {
    const next = new Set(weaponFilter);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    setWeaponFilter(next);
  };

  return (
    <div>
      <SectionLabel>Weapon</SectionLabel>
      {weapons.length === 0 ? (
        <p className="font-mono text-[10px] text-faint">no weapons extracted yet</p>
      ) : (
        <div className="space-y-0.5">
          {weapons.slice(0, WEAPONS_SHOWN).map((w) => (
            <label key={w.weapon_key} className="flex items-center gap-1.5 text-muted">
              <input
                type="checkbox"
                checked={weaponFilter.has(w.weapon_key)}
                onChange={() => toggle(w.weapon_key)}
                className="accent-[#d98e32]"
              />
              <span className="text-xs">{w.display_name}</span>
              <span className="ml-auto font-mono text-[10px] text-faint">{w.event_count}</span>
            </label>
          ))}
        </div>
      )}
    </div>
  );
}

export default function FilterPanel() {
  const [open, setOpen] = useState(false);
  const categoryFilter = useStore((s) => s.categoryFilter);
  const setCategoryFilter = useStore((s) => s.setCategoryFilter);
  const minReliability = useStore((s) => s.minReliability);
  const setMinReliability = useStore((s) => s.setMinReliability);
  const countryFilter = useStore((s) => s.countryFilter);
  const setCountryFilter = useStore((s) => s.setCountryFilter);
  const actorFilter = useStore((s) => s.actorFilter);
  const setActorFilter = useStore((s) => s.setActorFilter);
  const weaponFilter = useStore((s) => s.weaponFilter);
  const setWeaponFilter = useStore((s) => s.setWeaponFilter);

  const toggle = (key: string) => {
    const next = new Set(categoryFilter);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    setCategoryFilter(next);
  };

  const active =
    categoryFilter.size > 0 ||
    minReliability > 0 ||
    countryFilter.size > 0 ||
    actorFilter.trim().length > 0 ||
    weaponFilter.size > 0;

  const clearAll = () => {
    setCategoryFilter(new Set());
    setMinReliability(0);
    setCountryFilter(new Set());
    setActorFilter("");
    setWeaponFilter(new Set());
  };

  return (
    <div className="pointer-events-auto absolute left-4 top-4 z-20 w-64">
      <button
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="border border-edge bg-panel/95 px-3 py-1.5 font-mono text-xs text-muted hover:text-bone focus:outline-none focus:ring-1 focus:ring-signal"
      >
        filters {active ? "· active" : ""}
      </button>
      {open && (
        <div className="mt-1 max-h-[calc(100vh-12rem)] space-y-4 overflow-y-auto border border-edge bg-panel/95 p-3 text-sm">
          <div>
            <SectionLabel>Category</SectionLabel>
            <div className="grid grid-cols-2 gap-x-2 gap-y-1">
              {CATEGORIES.map(([key, label]) => (
                <label key={key} className="flex items-center gap-1.5 text-muted">
                  <input
                    type="checkbox"
                    checked={categoryFilter.size === 0 || categoryFilter.has(key)}
                    onChange={() => toggle(key)}
                    className="accent-[#d98e32]"
                  />
                  <span className="text-xs">{label}</span>
                </label>
              ))}
            </div>
            <p className="mt-1 font-mono text-[10px] text-faint">
              all checked = no filter
            </p>
          </div>
          <CountryFilter />
          <ActorFilter />
          <WeaponFilter />
          <div>
            <SectionLabel>
              Reliability floor: <span className="text-bone">{minReliability.toFixed(2)}</span>
            </SectionLabel>
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={minReliability}
              onChange={(e) => setMinReliability(Number(e.target.value))}
              className="w-full accent-[#d98e32]"
              aria-label="Minimum reliability"
            />
          </div>
          {active && (
            <button
              onClick={clearAll}
              className="border border-edge px-2 py-1 font-mono text-xs text-muted hover:text-bone focus:outline-none focus:ring-1 focus:ring-signal"
            >
              clear all filters
            </button>
          )}
        </div>
      )}
    </div>
  );
}
