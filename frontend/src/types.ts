export type GeoPrecision = "exact" | "settlement" | "admin2" | "admin1" | "country";

export type EventCategory =
  | "airstrike"
  | "artillery"
  | "drone_strike"
  | "missile_strike"
  | "ied"
  | "small_arms"
  | "naval"
  | "ground_assault"
  | "protest"
  | "riot"
  | "abduction"
  | "other_violence"
  | "non_kinetic";

/** Light row from GET /events for globe plotting. */
export interface EventLite {
  id: number;
  cluster_id: number | null;
  source: string;
  occurred_at: string;
  category: EventCategory;
  geo_precision: GeoPrecision;
  geo_radius_m: number | null;
  country: string | null;
  location_name: string | null;
  fatalities: number | null;
  reliability: number | null;
  headline: string | null;
  source_count: number;
  thermal_corroborated: boolean;
  lat: number;
  lon: number;
}

export interface Weapon {
  weapon_key: string;
  display_name: string;
  category: string | null;
  confidence: number;
  method: "source_field" | "gazetteer" | "ner";
  evidence_span: string | null;
}

export interface ClusterMember {
  id: number;
  source: string;
  source_event_id: string;
  occurred_at: string;
  category: string;
  actor_a: string | null;
  actor_b: string | null;
  fatalities: number | null;
  headline: string | null;
  source_urls: string[] | null;
}

/** Full payload: SSE message body and GET /events/{id}. */
export interface EventFull extends EventLite {
  sources: string[];
  ingested_at: string | null;
  admin1: string | null;
  raw_event_type: string | null;
  actor_a: string | null;
  actor_b: string | null;
  actor_a_canonical: string | null;
  actor_b_canonical: string | null;
  notes: string | null;
  source_urls: string[];
  reliability_explanation: string | null;
  weapons: Weapon[];
  members?: ClusterMember[];
}

export interface FeedHealth {
  source: string;
  watermark: string | null;
  last_success_at: string | null;
  last_attempt_at: string | null;
  last_error: string | null;
  consecutive_failures: number;
  records_ingested: number;
  credential_status: "active" | "degraded" | "dead" | null;
}

export interface Hotspot {
  id: number;
  satellite: string;
  acquired_at: string;
  lat: number;
  lon: number;
  brightness: number | null;
  frp: number | null;
  confidence: string | null;
}
