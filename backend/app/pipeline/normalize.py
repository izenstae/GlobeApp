"""Source payload -> UnifiedEvent. Normalize on the way in, never on the way out.

The raw payload is always retained on the event row so parsing improvements can
be replayed against history.
"""

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

# Rendering radius implied by each precision level, in meters.
PRECISION_RADIUS_M = {
    "exact": 1_000,
    "settlement": 5_000,
    "admin2": 25_000,
    "admin1": 60_000,
    "country": 250_000,
}


class UnifiedEvent(BaseModel):
    source: str
    source_event_id: str
    occurred_at: datetime
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    geo_precision: str
    geo_radius_m: int | None = None
    country: str | None = None
    admin1: str | None = None
    location_name: str | None = None
    category: str
    raw_event_type: str | None = None
    actor_a: str | None = None
    actor_b: str | None = None
    fatalities: int | None = None
    headline: str | None = None
    notes: str | None = None
    source_urls: list[str] = []
    raw_payload: dict[str, Any]

    def with_default_radius(self) -> "UnifiedEvent":
        if self.geo_radius_m is None:
            self.geo_radius_m = PRECISION_RADIUS_M[self.geo_precision]
        return self


# --------------------------------------------------------------------- ACLED

# ACLED sub_event_type -> our category. Sub-event is more specific than event_type,
# so match it first.
ACLED_SUB_EVENT_CATEGORY = {
    "air/drone strike": "airstrike",
    "shelling/artillery/missile attack": "artillery",
    "remote explosive/landmine/ied": "ied",
    "suicide bomb": "ied",
    "grenade": "other_violence",
    "chemical weapon": "other_violence",
    "abduction/forced disappearance": "abduction",
    "armed clash": "ground_assault",
    "government regains territory": "ground_assault",
    "non-state actor overtakes territory": "ground_assault",
}

ACLED_EVENT_TYPE_CATEGORY = {
    "battles": "ground_assault",
    "explosions/remote violence": "artillery",
    "violence against civilians": "other_violence",
    "protests": "protest",
    "riots": "riot",
    "strategic developments": "non_kinetic",
}

# ACLED geo_precision: 1 = coordinates of the named settlement, 2 = nearby/part
# of region, 3 = larger region or provincial capital.
ACLED_GEO_PRECISION = {1: "settlement", 2: "admin2", 3: "admin1"}


def normalize_acled(row: dict[str, Any]) -> UnifiedEvent | None:
    try:
        lat = float(row["latitude"])
        lon = float(row["longitude"])
    except (KeyError, TypeError, ValueError):
        return None  # unmappable without coordinates

    sub = str(row.get("sub_event_type", "")).strip().lower()
    ev_type = str(row.get("event_type", "")).strip().lower()
    category = ACLED_SUB_EVENT_CATEGORY.get(sub) or ACLED_EVENT_TYPE_CATEGORY.get(
        ev_type, "other_violence"
    )
    # ACLED distinguishes drone strikes only in the notes/tags; keep 'airstrike'
    # unless the sub-event carried the drone marker.
    if category == "airstrike" and "drone" in str(row.get("tags", "")).lower():
        category = "drone_strike"

    occurred = datetime.strptime(str(row["event_date"]), "%Y-%m-%d").replace(tzinfo=UTC)
    try:
        precision = ACLED_GEO_PRECISION.get(int(row.get("geo_precision", 2)), "admin2")
    except (TypeError, ValueError):
        precision = "admin2"

    fatalities = None
    try:
        fatalities = int(row["fatalities"])
    except (KeyError, TypeError, ValueError):
        pass

    return UnifiedEvent(
        source="acled",
        source_event_id=str(row["event_id_cnty"]),
        occurred_at=occurred,
        lat=lat,
        lon=lon,
        geo_precision=precision,
        country=row.get("country") or None,
        admin1=row.get("admin1") or None,
        location_name=row.get("location") or None,
        category=category,
        raw_event_type=f"{row.get('event_type', '')}/{row.get('sub_event_type', '')}",
        actor_a=row.get("actor1") or None,
        actor_b=row.get("actor2") or None,
        fatalities=fatalities,
        headline=None,
        notes=row.get("notes") or None,
        source_urls=[],
        raw_payload=row,
    ).with_default_radius()


# --------------------------------------------------------------------- GDELT

# GDELT 2.0 export.CSV column indexes (61 tab-separated columns).
G = {
    "GLOBALEVENTID": 0,
    "SQLDATE": 1,
    "Actor1Name": 6,
    "Actor2Name": 16,
    "EventCode": 26,
    "EventBaseCode": 27,
    "EventRootCode": 28,
    "NumMentions": 31,
    "NumSources": 32,
    "NumArticles": 33,
    "ActionGeo_Type": 51,
    "ActionGeo_Fullname": 52,
    "ActionGeo_CountryCode": 53,
    "ActionGeo_Lat": 56,
    "ActionGeo_Long": 57,
    "DATEADDED": 59,
    "SOURCEURL": 60,
}

# CAMEO filter: 18x assault, 19x fight, 20x unconventional mass violence,
# 145 protest with violence. Everything else is noise for this app.
GDELT_KEEP_ROOTS = {"18", "19", "20"}
GDELT_KEEP_CODES_PREFIX = ("145",)

GDELT_CODE_CATEGORY = [
    ("1831", "ied"),
    ("1832", "ied"),
    ("1833", "ied"),
    ("183", "ied"),
    ("181", "abduction"),
    ("193", "small_arms"),
    ("194", "artillery"),
    ("195", "airstrike"),
    ("196", "other_violence"),
    ("145", "riot"),
]

# ActionGeo_Type: 1 country, 2 US state, 3 US city, 4 world city, 5 world state.
GDELT_GEO_PRECISION = {1: "country", 2: "admin1", 3: "settlement", 4: "settlement", 5: "admin1"}


def _gdelt_category(code: str, root: str) -> str:
    for prefix, category in GDELT_CODE_CATEGORY:
        if code.startswith(prefix):
            return category
    if root == "19":
        return "ground_assault"
    return "other_violence"


def normalize_gdelt(cols: list[str]) -> UnifiedEvent | None:
    if len(cols) < 61:
        return None
    code = cols[G["EventCode"]].strip()
    root = cols[G["EventRootCode"]].strip()
    if root not in GDELT_KEEP_ROOTS and not code.startswith(GDELT_KEEP_CODES_PREFIX):
        return None
    try:
        lat = float(cols[G["ActionGeo_Lat"]])
        lon = float(cols[G["ActionGeo_Long"]])
    except ValueError:
        return None
    try:
        geo_type = int(cols[G["ActionGeo_Type"]])
    except ValueError:
        geo_type = 1
    if geo_type == 0:
        return None  # no georeference at all

    occurred = datetime.strptime(cols[G["SQLDATE"]], "%Y%m%d").replace(tzinfo=UTC)
    fullname = cols[G["ActionGeo_Fullname"]]
    parts = [p.strip() for p in fullname.split(",")] if fullname else []
    url = cols[G["SOURCEURL"]].strip()

    raw_payload = {name: cols[idx] for name, idx in G.items()}
    return UnifiedEvent(
        source="gdelt",
        source_event_id=cols[G["GLOBALEVENTID"]],
        occurred_at=occurred,
        lat=lat,
        lon=lon,
        geo_precision=GDELT_GEO_PRECISION.get(geo_type, "country"),
        country=parts[-1] if parts else None,
        admin1=parts[1] if len(parts) == 3 else None,
        location_name=parts[0] if parts else None,
        category=_gdelt_category(code, root),
        raw_event_type=code,
        actor_a=cols[G["Actor1Name"]] or None,
        actor_b=cols[G["Actor2Name"]] or None,
        fatalities=None,  # GDELT does not code fatalities reliably
        headline=None,
        notes=None,
        source_urls=[url] if url else [],
        raw_payload=raw_payload,
    ).with_default_radius()


# ---------------------------------------------------------------------- UCDP

# UCDP GED where_prec: 1 exact location, 2 within ~25km, 3 second-order admin,
# 4 first-order admin, 5 linear feature / between points, 6 country, 7 event in
# international waters or airspace.
UCDP_WHERE_PRECISION = {
    1: "settlement",
    2: "admin2",
    3: "admin2",
    4: "admin1",
    5: "admin1",
    6: "country",
    7: "country",
}

# type_of_violence: 1 state-based armed conflict, 2 non-state conflict,
# 3 one-sided violence against civilians. UCDP does not code the kinetic mode,
# so the category stays generic and the raw label is preserved.
UCDP_VIOLENCE_TYPE = {1: "state-based conflict", 2: "non-state conflict", 3: "one-sided violence"}
UCDP_VIOLENCE_CATEGORY = {1: "ground_assault", 2: "ground_assault", 3: "other_violence"}


def normalize_ucdp(row: dict[str, Any]) -> UnifiedEvent | None:
    try:
        lat = float(row["latitude"])
        lon = float(row["longitude"])
        event_id = row["id"]
    except (KeyError, TypeError, ValueError):
        return None

    date_raw = str(row.get("date_start", ""))[:10]
    try:
        occurred = datetime.strptime(date_raw, "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError:
        return None

    try:
        violence_type = int(row.get("type_of_violence", 0))
    except (TypeError, ValueError):
        violence_type = 0
    category = UCDP_VIOLENCE_CATEGORY.get(violence_type, "other_violence")

    try:
        precision = UCDP_WHERE_PRECISION.get(int(row.get("where_prec", 4)), "admin1")
    except (TypeError, ValueError):
        precision = "admin1"

    fatalities = None
    try:
        fatalities = int(row["best"])  # UCDP best (most likely) estimate
    except (KeyError, TypeError, ValueError):
        pass

    return UnifiedEvent(
        source="ucdp",
        source_event_id=str(event_id),
        occurred_at=occurred,
        lat=lat,
        lon=lon,
        geo_precision=precision,
        country=row.get("country") or None,
        admin1=row.get("adm_1") or None,
        location_name=row.get("where_coordinates") or None,
        category=category,
        raw_event_type=UCDP_VIOLENCE_TYPE.get(violence_type),
        actor_a=row.get("side_a") or None,
        actor_b=row.get("side_b") or None,
        fatalities=fatalities,
        headline=row.get("dyad_name") or None,
        notes=row.get("source_headline") or None,
        source_urls=[],
        raw_payload=row,
    ).with_default_radius()
