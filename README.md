# conflict-globe

A single-page web app showing a 3D globe with live-updating conflict events.
Events come from real public data feeds, are normalized into one schema,
deduplicated across sources, and enriched with extracted weapon systems and
actor names. When a new event arrives, the camera flies to it and presents a
detail card. A personal research tool that runs locally; not a product.

The app's honest subject is *uncertainty in reporting*: every marker renders at
its true reported precision, reliability scores are always visible, and every
extracted weapon traces to the literal text span it came from. Nothing is ever
fabricated to make the globe look populated — an empty globe tells you which
feeds are connected and why the rest are not.

Full design and requirements: [docs/BUILD_BRIEF.md](docs/BUILD_BRIEF.md).

## Data sources and licensing

| Source | What it provides | Terms |
|---|---|---|
| [ACLED](https://acleddata.com) | Curated conflict events: coordinates, dates, actors, fatalities | [ACLED Terms of Use](https://acleddata.com/terms-of-use/). Attribution required; redistribution of the dataset prohibited. Register at the ACLED Access Portal for credentials. |
| [GDELT](https://www.gdeltproject.org) | Machine-coded global news events, refreshed every 15 minutes | [GDELT Terms](https://www.gdeltproject.org/about.html). Open for research use; no key required for the 15-minute update files. |
| [NASA FIRMS](https://firms.modaps.eosdis.nasa.gov) | Satellite thermal anomaly detections (VIIRS) | [NASA Earthdata citation policy](https://www.earthdata.nasa.gov/engage/open-data-services-software-policies). Free API key. |
| [UCDP GED](https://ucdp.uu.se) | Uppsala's curated georeferenced event dataset (monthly candidate releases) | [UCDP terms](https://ucdp.uu.se/downloads/). Free API, no key. Historical baseline + accuracy check, not live. |

**Conflict event data © ACLED, used under their Terms of Use.** The running app
carries this attribution in its footer, as their terms require.

**No credentials and no source data are stored in this repository.** The
`.gitignore` excludes `.env`, `data/`, CSV/TSV/parquet exports, and database
dumps precisely because ACLED's terms prohibit redistributing their dataset and
because this repo is public. Do not add exceptions.

## Architecture

- **Backend** — Python 3.11, FastAPI (async), PostgreSQL 16 + PostGIS, Redis,
  APScheduler, SQLAlchemy 2 async, Alembic.
  - `app/auth/` — credential manager: encrypted-at-rest tokens, proactive
    refresh 2h before expiry, reactive single-retry on 401, Postgres advisory
    locking against refresh stampedes, refresh-token rotation, failure
    escalation (`active` → `degraded` → `dead`).
  - `app/ingest/` — per-source ingesters with high-water marks; failures
    surface in `/health/feeds`, never silently.
  - `app/pipeline/` — normalization into a unified event schema,
    spatial-temporal-textual dedup clustering at ingest, weapon gazetteer
    extraction with evidence spans, actor canonicalization onto the ACLED
    vocabulary, FIRMS thermal corroboration, cluster reliability scoring, and
    cross-border strike-origin inference (country-level, from state-actor
    attribution, with method and confidence stored on the record).
  - `GET /analysis/ucdp` — coverage comparison of the live pipeline's output
    against the UCDP GED baseline for a month (matched = pipeline event within
    25 km and ±1 day of a UCDP event; criteria stated in the response).
- **Frontend** — React 18 + Vite + TypeScript, Tailwind, Zustand,
  react-globe.gl. SSE live stream, client-side priority queue, quaternion-slerp
  camera choreography, full user-interrupt control, `prefers-reduced-motion`
  support. Analysis surface: time scrubber with playback, filters by category /
  country / actor / weapon / reliability floor, and dashed cross-border strike
  arcs (origins are labeled country-level inferences, toggleable in the status
  bar).

## Local setup

```bash
# 1. Databases
docker compose up -d

# 2. Backend
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

cp ../.env.example .env
# generate the one long-lived secret (encrypts stored API tokens):
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# put that value in .env as CREDENTIAL_ENCRYPTION_KEY

alembic upgrade head

# 3. Credentials (GDELT and UCDP need none; ACLED and FIRMS are optional but recommended)
python -m app.auth.cli setup --provider acled
python -m app.auth.cli setup --provider firms
python -m app.auth.cli status

# 4. Run
uvicorn app.main:app --port 8000          # backend + ingest scheduler
cd ../frontend && npm install && npm run dev  # frontend on :5173
```

GDELT begins ingesting within 15 minutes with no credentials. Feed health is
at `http://localhost:8000/health/feeds` and in the app's status bar.

## Tests

```bash
cd backend && pytest        # needs the docker compose Postgres running
```

Every test that touches a provider mocks the HTTP layer; the suite never makes
a live call to ACLED, GDELT, or NASA.

## Phase status (build brief §10)

| Phase | Status |
|---|---|
| 0 — Skeleton and credentials | ✅ complete, incl. the five required credential tests |
| 1 — Static render | ✅ render path proven (bbox `/events` endpoint + globe) |
| 2 — Live ingestion | ✅ ACLED + GDELT ingesters, watermarks, `/health/feeds` |
| 3 — Deduplication | ✅ clustering at ingest, clusters served by default |
| 4 — Live camera | ✅ SSE, queue, CameraDirector, interrupt, reduced-motion |
| 5 — Enrichment | ✅ FIRMS corroboration, weapon gazetteer, reliability (NER stage is a documented extension point, not yet trained) |
| 6 — Analysis surface | ✅ scrubber playback, category/country/actor/weapon/reliability filters, cross-border strike arcs, UCDP baseline + `/analysis/ucdp` |

The one open extension point is the Stage-2 NER weapon extractor (brief §7.2):
training it honestly requires a hand-corrected corpus, so `extract_weapons()`
remains the documented seam where its hits would merge with gazetteer hits.

## License

MIT — see [LICENSE](LICENSE). **The license covers this repository's code
only.** The data the app ingests and displays remains under each provider's own
terms (see table above) and is not part of this codebase.
