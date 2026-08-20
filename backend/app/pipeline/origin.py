"""Strike-origin inference for cross-border arc rendering (Phase 6).

The brief calls for arcs "where origin is known". No feed carries a launch
coordinate, so the only origin this pipeline will assert is a country-level
derivation with its method on the record:

  the source attributed the strike (airstrike / drone_strike / missile_strike)
  to a named state force — ACLED-style "Military Forces of X" — and X differs
  from the country the strike landed in. Origin = X's centroid, precision =
  'country', method = 'actor_country_inference', confidence = 0.5.

Everything weaker than that (non-state actors, unattributed strikes, domestic
strikes, countries missing from the centroid table) gets no origin at all. The
UI renders the arc dashed with the qualifier, never as a tracked trajectory.
"""

import re
from functools import lru_cache
from pathlib import Path

import yaml

from app.models import Event

CENTROIDS_PATH = Path(__file__).parent / "gazetteer" / "country_centroids.yaml"

# Only long-range remote-strike categories: an arc from a country centroid for
# artillery or ground combat would imply reach the data does not support.
ARC_CATEGORIES = {"airstrike", "drone_strike", "missile_strike"}

ORIGIN_METHOD = "actor_country_inference"
ORIGIN_CONFIDENCE = 0.5

# ACLED state-force convention, e.g. "Military Forces of Russia (2000-)" or
# "Military Forces of Russia (2000-) Air Force". Parentheticals are stripped
# first; trailing branch words are trimmed until the centroid table matches.
_STATE_FORCE_RE = re.compile(r"^(?:Military|Police) Forces of (?:the )?(.+)$", re.IGNORECASE)


@lru_cache
def country_centroids() -> dict[str, tuple[str, float, float]]:
    """lowercase name -> (display name, lat, lon)."""
    with open(CENTROIDS_PATH, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return {
        str(name).strip().lower(): (str(name).strip(), float(v[0]), float(v[1]))
        for name, v in raw.items()
    }


def state_actor_country(actor: str | None) -> str | None:
    """Country name (centroid-table key, lowercase) for an ACLED state force,
    or None when the actor is not a recognizable state force."""
    if not actor:
        return None
    cleaned = re.sub(r"\([^)]*\)", " ", actor).strip()
    match = _STATE_FORCE_RE.match(cleaned)
    if match is None:
        return None
    words = match.group(1).split()
    centroids = country_centroids()
    # Trim trailing branch qualifiers ("... Air Force") until the table matches.
    while words:
        candidate = " ".join(words).strip().lower()
        if candidate in centroids:
            return candidate
        words.pop()
    return None


def infer_origin(event: Event) -> None:
    """Populate origin fields in place when the inference rule holds; otherwise
    leave them NULL. Idempotent: recomputes from current actor/category state."""
    event.origin_geom = None
    event.origin_precision = None
    event.origin_country = None
    event.origin_method = None
    event.origin_confidence = None

    if event.category not in ARC_CATEGORIES or not event.country:
        return
    # actor_a is the initiator in ACLED coding; canonical name when mapped.
    origin = state_actor_country(event.actor_a_canonical or event.actor_a)
    if origin is None or origin == event.country.strip().lower():
        return
    display, lat, lon = country_centroids()[origin]
    event.origin_geom = f"SRID=4326;POINT({lon} {lat})"
    event.origin_precision = "country"
    event.origin_country = display
    event.origin_method = ORIGIN_METHOD
    event.origin_confidence = ORIGIN_CONFIDENCE
