# Build Brief: Live Global Conflict Globe

## 0. How to use this brief

You are building a working application, not a prototype. Build it in the phases given in Section 10, and do not move to the next phase until the current one runs end to end against real data.

Hard rules for the duration of this build:

- **Never fabricate data.** Do not seed the database with invented events, do not write mock feed responses that masquerade as real ones, and do not hardcode sample conflicts to make the UI look populated. If a feed is not wired up yet, the globe shows an empty state that says so.
- **Never fabricate weapon or actor attributions.** Every weapon and actor shown in the UI traces to a specific source field or a specific extracted text span, with a confidence score attached. If confidence is below threshold, the UI says "not specified" rather than guessing.
- **Do not silently swallow ingestion errors.** A feed that fails must surface in a health endpoint and in the UI status bar.
- Ask before adding a dependency that overlaps with something already in the stack.

---

## 1. What this is

A single-page web app showing a 3D globe of the earth with live-updating conflict events plotted on it. Events come from real public data feeds, are normalized into one schema, deduplicated across sources, and enriched with extracted weapon systems and actor names.

When a new event arrives, the globe flies the camera to that location and presents a detail card about the event.

This runs locally on the developer's machine. It is a personal research tool, not a commercial product. It must respect the terms of use of every data source it touches.

---

## 2. Stack

| Layer | Choice | Notes |
|---|---|---|
| Backend | Python 3.11+, FastAPI | Async throughout |
| DB | PostgreSQL 16 + PostGIS 3.4 | Spatial indexes are non-negotiable |
| Migrations | Alembic | |
| Cache / pubsub | Redis 7 | Query cache and SSE fanout |
| Scheduler | APScheduler (in-process) | Do not reach for Celery in v1 |
| HTTP client | httpx (async) | |
| ORM | SQLAlchemy 2.x async | |
| Frontend | React 18 + Vite + TypeScript | |
| Globe | react-globe.gl (three.js) | Phase 1 through 5. Migrate to deck.gl GlobeView only if event count on screen exceeds ~50k |
| Styling | Tailwind | |
| State | Zustand | |
| Local orchestration | docker-compose | Postgres, PostGIS, Redis. App runs on host for fast reload |

---

## 3. Repository structure

```
conflict-globe/
├── docker-compose.yml
├── .env.example
├── backend/
│   ├── app/
│   │   ├── main.py                 # FastAPI app, lifespan, CORS
│   │   ├── config.py               # pydantic-settings
│   │   ├── db.py                   # async engine, session factory
│   │   ├── models/                 # SQLAlchemy models
│   │   ├── schemas/                # pydantic request/response
│   │   ├── api/
│   │   │   ├── events.py           # GET /events, GET /events/{id}
│   │   │   ├── stream.py           # GET /stream/events (SSE)
│   │   │   └── health.py           # GET /health, GET /health/feeds
│   │   ├── auth/
│   │   │   ├── manager.py          # CredentialManager (Section 5)
│   │   │   ├── providers/          # one refresh strategy per provider
│   │   │   └── cli.py              # `python -m app.auth.cli setup`
│   │   ├── ingest/
│   │   │   ├── base.py             # BaseIngester ABC
│   │   │   ├── acled.py
│   │   │   ├── gdelt.py
│   │   │   ├── firms.py
│   │   │   └── scheduler.py        # APScheduler wiring
│   │   ├── pipeline/
│   │   │   ├── normalize.py        # source payload -> UnifiedEvent
│   │   │   ├── dedupe.py           # spatial-temporal-textual clustering
│   │   │   ├── enrich.py           # weapon + actor extraction
│   │   │   └── gazetteer/
│   │   │       ├── weapons.yaml
│   │   │       └── actors.yaml
│   │   └── alembic/
│   └── tests/
└── frontend/
    └── src/
        ├── App.tsx
        ├── globe/
        │   ├── Globe.tsx
        │   ├── CameraDirector.ts   # flight choreography (Section 8)
        │   └── layers.ts
        ├── live/
        │   ├── useEventStream.ts   # SSE subscription
        │   └── EventQueue.ts       # arrival buffer + priority
        ├── ui/
        │   ├── EventCard.tsx
        │   ├── FilterPanel.tsx
        │   ├── TimeScrubber.tsx
        │   └── StatusBar.tsx
        └── store/
```

---

## 4. Unified event schema

Every source normalizes into this on ingest. Normalize on the way in, never on the way out. Always retain the raw payload so parsing improvements can be replayed against history.

```sql
CREATE TYPE geo_precision AS ENUM ('exact', 'settlement', 'admin2', 'admin1', 'country');
CREATE TYPE event_category AS ENUM (
  'airstrike','artillery','drone_strike','missile_strike','ied','small_arms',
  'naval','ground_assault','protest','riot','abduction','other_violence','non_kinetic'
);

CREATE TABLE events (
  id                BIGSERIAL PRIMARY KEY,
  source            TEXT NOT NULL,              -- 'acled' | 'gdelt' | 'firms' | ...
  source_event_id   TEXT NOT NULL,
  cluster_id        BIGINT REFERENCES event_clusters(id),
  occurred_at       TIMESTAMPTZ NOT NULL,
  ingested_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  geom              GEOGRAPHY(POINT, 4326) NOT NULL,
  geo_precision     geo_precision NOT NULL,
  geo_radius_m      INTEGER,                    -- implied uncertainty for rendering
  country           TEXT,
  admin1            TEXT,
  location_name     TEXT,
  category          event_category NOT NULL,
  raw_event_type    TEXT,                       -- source's own label, preserved
  actor_a           TEXT,
  actor_b           TEXT,
  actor_a_canonical TEXT,                       -- mapped to ACLED actor taxonomy
  actor_b_canonical TEXT,
  fatalities        INTEGER,
  headline          TEXT,
  notes             TEXT,
  source_urls       TEXT[],
  source_count      INTEGER NOT NULL DEFAULT 1,
  reliability       REAL,                       -- 0..1, see Section 7.3
  raw_payload       JSONB NOT NULL,
  UNIQUE (source, source_event_id)
);

CREATE INDEX events_geom_idx      ON events USING GIST (geom);
CREATE INDEX events_occurred_idx  ON events (occurred_at DESC);
CREATE INDEX events_cluster_idx   ON events (cluster_id);
CREATE INDEX events_category_idx  ON events (category);

CREATE TABLE event_weapons (
  id            BIGSERIAL PRIMARY KEY,
  event_id      BIGINT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
  weapon_key    TEXT NOT NULL,     -- canonical key from gazetteer
  display_name  TEXT NOT NULL,
  category      TEXT,              -- 'ballistic_missile' | 'loitering_munition' | ...
  confidence    REAL NOT NULL,     -- 0..1
  method        TEXT NOT NULL,     -- 'source_field' | 'gazetteer' | 'ner'
  evidence_span TEXT               -- the literal text the match came from
);

CREATE TABLE event_clusters (
  id             BIGSERIAL PRIMARY KEY,
  representative BIGINT,
  first_seen     TIMESTAMPTZ NOT NULL,
  last_seen      TIMESTAMPTZ NOT NULL,
  member_count   INTEGER NOT NULL DEFAULT 1,
  centroid       GEOGRAPHY(POINT, 4326)
);
```

---

## 5. Credential manager with automatic refresh

This is a first-class subsystem, not a utility function. Build it in Phase 0 before any ingester.

### 5.1 The problem it solves

ACLED issues OAuth access tokens valid for 24 hours plus a longer-lived refresh token. Other providers use static keys that never rotate. The system must handle both behind one interface, refresh without human intervention, and survive four concurrent ingest workers all hitting expiry at the same moment.

### 5.2 Storage

```sql
CREATE TABLE api_credentials (
  provider          TEXT PRIMARY KEY,       -- 'acled' | 'firms' | ...
  auth_type         TEXT NOT NULL,          -- 'oauth_refresh' | 'static_key'
  access_token      TEXT,                   -- encrypted at rest
  refresh_token     TEXT,                   -- encrypted at rest
  access_expires_at TIMESTAMPTZ,
  refresh_expires_at TIMESTAMPTZ,
  last_refreshed_at TIMESTAMPTZ,
  refresh_failures  INTEGER NOT NULL DEFAULT 0,
  status            TEXT NOT NULL DEFAULT 'active',  -- 'active'|'degraded'|'dead'
  extra             JSONB
);
```

Encrypt `access_token` and `refresh_token` with Fernet, keyed by `CREDENTIAL_ENCRYPTION_KEY` from the environment. The environment holds exactly one long-lived secret (the encryption key). Rotating tokens live in the database, because a value that changes every 24 hours does not belong in a .env file.

### 5.3 CredentialManager interface

```python
class CredentialManager:
    async def get_token(self, provider: str) -> str:
        """Return a valid token, refreshing first if needed. Never returns expired."""

    async def force_refresh(self, provider: str) -> str:
        """Refresh immediately regardless of expiry. Called by the 401 handler."""

    async def register(self, provider: str, **initial_credentials) -> None:
        """First-time setup. Performs initial token exchange and persists."""
```

### 5.4 Refresh behaviour, three layers

**Layer 1, proactive.** An APScheduler job runs every 15 minutes. For each active `oauth_refresh` credential where `access_expires_at - now() < 2 hours`, refresh it. In steady state this means the token is never actually expired when an ingester asks for it.

**Layer 2, reactive.** All outbound provider calls go through a shared httpx client with a response hook. On a 401 or 403, the hook calls `force_refresh(provider)` and retries the original request exactly once. If the retry also fails with 401, raise and mark the credential degraded. One retry, never a loop.

**Layer 3, concurrency guard.** Both paths acquire a Postgres advisory lock before refreshing:

```python
async with session.begin():
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
        {"key": f"cred_refresh:{provider}"},
    )
    # Re-read the row inside the lock. Another worker may have just refreshed.
    cred = await self._load(session, provider)
    if cred.access_expires_at > now() + timedelta(minutes=5):
        return decrypt(cred.access_token)   # someone else did the work
    # ... perform refresh, persist, return
```

The re-read inside the lock is the part that matters. Without it you serialize the stampede but still perform four redundant refreshes, and if the provider rotates refresh tokens, three of those four now hold a dead refresh token.

### 5.5 Refresh token rotation

Assume the provider may return a **new refresh token** alongside the new access token. Always persist whatever comes back. Never assume the stored refresh token survives a refresh. This is the single most common cause of an auth system that works for three days and then dies silently.

### 5.6 Failure escalation

- Refresh fails once: log warning, increment `refresh_failures`, retry with exponential backoff (30s, 2m, 8m).
- Three consecutive failures: set `status = 'degraded'`, emit to `/health/feeds`, show a persistent warning in the frontend status bar naming the provider.
- Refresh token itself expired or rejected: set `status = 'dead'`, stop retrying, and surface a message telling the user to re-run the setup CLI. Do not spam the provider.
- In all failure cases the app **keeps serving cached and historical data**. A dead credential degrades one feed, it does not take down the globe.

### 5.7 Setup CLI

```
python -m app.auth.cli setup --provider acled
python -m app.auth.cli status
python -m app.auth.cli refresh --provider acled
```

`setup` prompts for whatever that provider needs, performs the initial exchange to confirm the credentials actually work, and persists. It fails loudly if the exchange does not succeed, rather than storing credentials it has never validated.

`status` prints a table: provider, status, minutes until access expiry, last refresh, consecutive failures.

---

## 6. Ingesters

Each ingester subclasses `BaseIngester` and implements `fetch(since) -> list[RawRecord]`. Base class handles auth, retry, rate limiting, watermarking, and handing records to the pipeline. Every ingester records a high-water mark so restarts resume rather than re-pull.

### 6.1 ACLED

- Curated conflict events with lat/long, dated, named actors, fatality counts, and a free-text `notes` field.
- Register at the ACLED Access Portal to obtain a key. Use an institutional email address, which confers a higher access tier than a personal one.
- OAuth token-based auth for programmatic access. Access token expires in 24 hours, so this is the primary consumer of Section 5.
- Default row limit is 5000 per request. Paginate with the page parameter and always apply date filters rather than pulling wholesale.
- Cadence: every 6 hours, requesting events with `event_date` in the trailing 14 days (ACLED revises records after publication, so re-pulling a window and upserting is correct).
- This is your highest-quality source. Its actor names become the canonical actor taxonomy that other sources map onto.
- **Attribution is mandatory under their terms of use.** Render a visible ACLED credit in the UI footer. Do not redistribute the raw dataset.

### 6.2 GDELT

- The live firehose. Machine-coded global news events, georeferenced to city level, refreshed every 15 minutes, 100+ languages.
- Two access paths. Prefer pulling the 15-minute CSV update files directly (no key, no quota) over BigQuery for the live loop. Keep BigQuery in reserve for historical backfill, where the free tier covers 1TB/month.
- Cadence: every 15 minutes, aligned to the publish schedule with a 2 minute lag.
- Filter hard on CAMEO codes in the 18x and 19x ranges (assault, fight, use of unconventional mass violence) plus 145 (protest with violence). Ingesting all of GDELT unfiltered will bury the signal.
- **Quality caveat that must be reflected in the UI:** GDELT mixes reliable outlets with questionable ones, and is prone to duplicate reports, circular reporting, and events resting on a single obscure source. A GDELT-only event with `source_count = 1` must render visibly lower-confidence than a corroborated one. This is what the `reliability` field is for.

### 6.3 NASA FIRMS

- Satellite thermal anomaly detections (VIIRS and MODIS). Free API key, no OAuth. Refreshed several times daily.
- This is an **independent physical-evidence layer**, not a conflict feed. A FIRMS hotspot is a heat signature, which may be a strike, a wildfire, a gas flare, or an industrial process.
- Never promote a FIRMS detection to an event on its own. Its only jobs are (a) rendering as a separate, visually distinct overlay the user can toggle, and (b) corroboration: if a hotspot falls within 5km and 6 hours of a reported kinetic event, raise that event's reliability score and mark it "thermal signature corroborated" in the detail card.
- This corroboration feature is the thing that differentiates this app from every other conflict map. Build it properly.

### 6.4 UCDP GED (optional, Phase 6)

Monthly candidate releases from Uppsala. Highest precision, not live. Use as a historical baseline and as a periodic accuracy check against what your own pipeline produced for the same period.

---

## 7. Pipeline

### 7.1 Deduplication

The hardest unglamorous problem in the build. One airstrike is reported by a dozen outlets and coded by GDELT as a dozen distinct events.

Cluster at ingest, not at query time. Two events join the same cluster when all of the following hold:

1. Great-circle distance under `max(10km, geo_radius_m of the less precise event)`
2. `occurred_at` within 6 hours
3. Category compatible (use a small compatibility matrix, not string equality: `airstrike` and `missile_strike` are compatible, `airstrike` and `protest` are not)
4. Text similarity of headline plus notes above 0.55 by token-set ratio, **or** both actor pairs match after canonicalization

Write `cluster_id` on the event row. Set the cluster representative to the member with the highest source reliability, tie-broken by earliest `occurred_at`. Increment `source_count` on the representative.

The API serves clusters by default, with individual member events available on drill-down. The globe plots one dot per cluster.

### 7.2 Weapon and actor extraction

No structured feed carries a clean weapon field. This is an extraction problem, in two stages.

**Stage 1, gazetteer.** Build `weapons.yaml` mapping canonical keys to alias lists, covering designation variants, NATO reporting names, and transliterations. One entry looks like:

```yaml
- key: iskander_m
  display_name: 9K720 Iskander-M
  category: ballistic_missile
  aliases: [iskander, iskander-m, 9k720, ss-26, ss-26 stone, искандер]
```

Run case-insensitive alias matching over `headline + notes + fetched article text`. Emit matches with `method='gazetteer'`, `confidence=0.85`, and the matched span in `evidence_span`. Guard against substring collisions with word-boundary matching.

**Stage 2, NER.** Fine-tune a small transformer for a `WEAPON` entity type to catch what the gazetteer misses. Bootstrap the training set by using gazetteer hits as weak labels over a large article corpus, then hand-correct a few hundred examples. Emit with `method='ner'` and the model's own confidence.

Surface confidence in the UI. Below 0.6 renders as "possible" with a visual qualifier. Never present an extracted weapon as confirmed fact.

**Actors:** ACLED already supplies clean actor names. Use ACLED's actor list as the canonical vocabulary, and fuzzy-map GDELT's messier actor strings onto it. Unmapped actors keep their raw string and are flagged unmapped rather than dropped.

### 7.3 Reliability score

A 0 to 1 composite, computed at cluster level, exposed in the API and rendered in the UI:

- Source count and diversity (three outlets carry more weight than three copies of one wire story, so deduplicate by root domain first)
- Source tier (ACLED weighted highest, GDELT records from established outlets in the middle, GDELT records from unrecognized domains lowest)
- Geographic precision (exact coordinates over country centroid)
- FIRMS thermal corroboration (a meaningful bump)
- Internal consistency (do the sources agree on fatality count and actors)

Do not hide the number. An analyst-grade tool shows its work.

---

## 8. Frontend: the live camera choreography

This is the signature feature. It has to feel like a newsroom situation display, not like a screensaver.

### 8.1 Transport

`GET /stream/events` is a Server-Sent Events endpoint. Backend publishes to a Redis channel when a new cluster is created or an existing cluster's `source_count` increases materially. SSE, not WebSocket: the flow is one-directional and SSE reconnects for free.

Each SSE message carries the full event payload so the card can render without a follow-up fetch.

### 8.2 EventQueue

New events land in a client-side priority queue rather than triggering an immediate camera move. Priority is a weighted blend of recency, fatality count, reliability, and category severity. The queue exists because three events can arrive in the same second, and the camera can only be in one place.

Queue behaviour:
- Maximum depth 50, drop lowest priority on overflow
- Badge in the status bar showing pending count, clickable to open a list
- Events already visible in the current viewport are marked and dequeued without a camera move, since flying to somewhere already on screen looks broken

### 8.3 CameraDirector

The flight itself, on dequeue:

1. **Pull back.** Ease camera altitude out to roughly 2.5x current over 400ms. Gives visual context for where you are leaving.
2. **Rotate.** Interpolate along the great circle from current lat/long to target using quaternion slerp, not naive lat/long lerp, which produces a wobbly path near the poles. Duration scales with angular distance: 900ms minimum, 2200ms maximum, `easeInOutCubic`.
3. **Descend.** Ease altitude in to the target zoom over 600ms, overlapping the last 200ms of rotation so the two blend.
4. **Impact.** A ring pulse animates outward from the point on arrival, sized to `geo_radius_m` so the animation itself communicates location uncertainty.
5. **Card in.** The detail card slides in from the right, 250ms, after the ring fires.
6. **Dwell.** Hold for 8 seconds by default, scaled up for high-fatality events. Then advance to the next queued event, or return to idle slow-rotation if the queue is empty.

The marker persists on the globe after the camera departs. Recent events glow and decay over their first hour.

### 8.4 User interrupt

Any drag, scroll, or click on the globe **immediately cancels the current flight and suspends live mode.** This is not optional. An app that fights the user for camera control is unusable.

On suspend: the status bar swaps to "Live paused, N events waiting" with a resume button. Resume replays the highest-priority queued event. Live mode also auto-resumes after 45 seconds of no interaction, with a visible countdown so it is never a surprise.

### 8.5 Accessibility

Respect `prefers-reduced-motion`: skip the flight entirely, hard-cut the camera to the target, fade the card in. The feature still works, it just does not move. Card content is reachable by keyboard, the queue is a focusable list, and the globe canvas has a live-region text mirror announcing new events for screen readers.

### 8.6 The event card

Content, in order:

- Category and time (relative, with absolute on hover)
- Location name and country, with a precision qualifier when it is not exact ("near Kharkiv, settlement-level precision")
- Actors, showing canonical names with raw source strings underneath when they differ
- Weapons, each with its confidence qualifier and, on expand, the evidence span it was extracted from
- Fatalities, when reported
- Reliability score with a plain-language explanation on hover ("4 independent sources, thermal corroboration")
- Source links, listed by outlet, opening in a new tab
- FIRMS corroboration badge when present

---

## 9. Design direction

The instinct here is dark-mode-with-red-dots, which is what every conflict map on the internet already looks like. Resist the default.

**Direction:** instrument panel, not war room. The reference is scientific telemetry and seismographic recording, not military HUD. This app's honest subject is *uncertainty in reporting*, and the design should say that. Red-alert aesthetics imply a confidence the underlying data does not have.

- **Palette:** deep desaturated slate base (not black), a bone-white foreground, and a single restrained signal color for active events. Reserve saturation entirely for encoding reliability: high-confidence events render solid, low-confidence render as an unfilled ring. Color carries information, never decoration.
- **Type:** a technical grotesque for the interface and a monospace for all coordinates, timestamps, and identifiers. Timestamps are always monospace and always UTC with local on hover. Data that could be copied into a spreadsheet should look like data.
- **Signature element:** the uncertainty radius. Every marker's footprint is drawn at its true reported precision, so a country-centroid event is a large soft disc and an exact-coordinate event is a tight point. The globe visibly shows you how much it does not know. Nothing else on screen should compete with this.
- **Motion:** the camera flight is the entire motion budget. Everything else is still. No ambient particles, no pulsing UI chrome, no decorative arcs.
- **Empty and error states:** an empty globe says which feeds are connected and when each last returned data. A dead credential says which provider and what command fixes it. Errors are specific and actionable, never vague and never apologetic.

---

## 10. Phasing

Each phase ends in something runnable. Do not proceed on a broken phase.

**Phase 0 — Skeleton and credentials.** docker-compose up brings up Postgres/PostGIS and Redis. Alembic migrations create the schema. CredentialManager fully implemented with all three refresh layers, advisory locking, rotation handling, and the setup CLI. Tests cover: proactive refresh fires at the right threshold, 401 triggers exactly one retry, concurrent refresh requests result in exactly one provider call, a rotated refresh token is persisted, and a dead credential degrades without crashing the app.

**Phase 1 — Static render.** Globe renders. Backend serves a bbox-filtered `/events` endpoint from a one-time ACLED CSV bulk load. Proves the render path with real data.

**Phase 2 — Live ingestion.** ACLED and GDELT ingesters running on schedule through CredentialManager. Normalization into the unified schema. Watermarking and upserts. `/health/feeds` reports per-source last-success and record counts.

**Phase 3 — Deduplication.** Clustering implemented and backfilled over existing rows. API serves clusters. Verify by hand against a known multi-reported incident that it collapses to one marker.

**Phase 4 — Live camera.** SSE endpoint, EventQueue, CameraDirector, event card, user interrupt, reduced-motion path. The feature from Section 8, complete.

**Phase 5 — Enrichment.** FIRMS ingester and corroboration matching. Weapon gazetteer and extraction. Reliability scoring. Confidence surfaced throughout the UI.

**Phase 6 — Analysis surface.** Time scrubber with playback. Filters by category, actor, weapon, country, reliability floor. Arc rendering for cross-border strikes where origin is known. UCDP baseline comparison.

---

## 11. Acceptance criteria

- Leave the app running unattended for 72 hours. The ACLED token refreshes automatically at least twice, no manual intervention occurs, and no gap appears in ingested data.
- Kill the ACLED credential mid-run. The app degrades to GDELT plus FIRMS, shows a specific warning naming the provider and the fix, and continues serving.
- A known incident reported by 8+ outlets renders as exactly one marker with `source_count` of 8.
- Grabbing the globe during a camera flight stops it instantly, with no snap-back and no fight for control.
- Every weapon shown in the UI can be traced, in two clicks, to the literal text span it was extracted from.
- No event renders at a precision higher than its source supports.
- ACLED attribution is visible in the running app.

---

## 12. Repository and version control

**Remote:** `https://github.com/izenstae/GlobeApp`
**Default branch:** `main`
**Current state:** one commit, README only. This brief is the first real content.

### 12.1 This repository is public

Two consequences that change how the build works, both non-negotiable.

**Credentials.** `CREDENTIAL_ENCRYPTION_KEY` is a Fernet key that decrypts every stored API token. GitHub's secret scanner does not recognize Fernet keys, so nothing will stop you committing it. Generate it locally, keep it in `.env`, and confirm `.env` is gitignored before the first commit that touches the auth subsystem.

**Data.** ACLED's terms of use restrict redistribution of their dataset. Committing an ACLED CSV export, a database dump, or a seeded fixture containing real ACLED records to a public repository is redistribution. Gitignore `data/`, `*.csv`, and any dump artifacts from the first commit onward, and never add an exception. The same caution applies to bulk GDELT extracts.

If you would rather not carry that discipline, flip the repo to private. Nothing in the build requires it to be public.

### 12.2 .gitignore

Commit this before anything else.

```gitignore
# Secrets
.env
.env.local
.env.*.local
*.key
*.pem
credentials.json

# Source data (see 12.1 - redistribution restrictions)
data/
*.csv
*.tsv
*.parquet
dumps/
*.sql.gz

# Python
__pycache__/
*.py[cod]
.venv/
venv/
.pytest_cache/
.ruff_cache/
.mypy_cache/
*.egg-info/

# Node
node_modules/
dist/
.vite/
*.tsbuildinfo

# Models
models/*.bin
models/*.safetensors
*.pt

# OS / editor
.DS_Store
.idea/
.vscode/
```

`.env.example` is committed, and contains variable names with placeholder values only. Never a real value, not even an expired one.

### 12.3 Branch and commit strategy

One branch per phase from Section 10, merged by PR into `main`:

```
phase-0/credentials
phase-1/static-render
phase-2/live-ingestion
phase-3/deduplication
phase-4/live-camera
phase-5/enrichment
phase-6/analysis-surface
```

Conventional commits (`feat:`, `fix:`, `chore:`, `docs:`, `test:`). Each PR description states which acceptance criteria from Section 11 it satisfies and which remain open. Squash on merge so `main` reads as one commit per phase.

Do not commit directly to `main` after the initial scaffold. The PR boundary is where you review your own work, which is the point.

### 12.4 Pre-commit hooks

Install `pre-commit` and wire it in Phase 0:

- `ruff` (lint and format, Python)
- `prettier` + `eslint` (frontend)
- `gitleaks` (secret detection, runs before every commit)
- A custom hook rejecting any staged file over 5MB, which catches accidental data commits

`gitleaks` is the one that actually earns its keep here. It fires before the secret reaches the remote, where a rewrite is easy. GitHub's scanner fires after, where it is not.

### 12.5 CI

`.github/workflows/ci.yml`, triggered on push and PR:

1. Spin up Postgres 16 + PostGIS as a service container
2. Run `alembic upgrade head` against it, verifying migrations apply from empty
3. `ruff check` and `mypy`
4. `pytest` including the CredentialManager concurrency tests from Phase 0
5. Frontend typecheck and build
6. `gitleaks` scan across the diff

Every test that touches a provider mocks the HTTP layer. CI must never make a live call to ACLED, GDELT, or NASA, both because it will be flaky and because it burns quota against a shared key.

Enable **secret scanning** and **push protection** in the repo settings. Both are free on public repositories and take one click each.

### 12.6 README

Rewrite the placeholder README to cover:

- What the app does, with a screenshot or short capture once Phase 4 lands
- Data sources with links, and a plain statement of each one's licensing terms
- The ACLED attribution required by their terms of use
- Local setup: docker-compose, migrations, `python -m app.auth.cli setup --provider acled`, running both servers
- An explicit note that no credentials or source data are stored in the repository
- Current phase status against Section 10

Add a LICENSE. MIT for your own code is fine, but state clearly in the README that the license covers the code only and not the data, which remains under each provider's terms.

### 12.7 Initial push sequence

```bash
git clone https://github.com/izenstae/GlobeApp.git
cd GlobeApp
# .gitignore FIRST, before any other file exists
git add .gitignore && git commit -m "chore: add gitignore"
# then this brief, then scaffold, then phase branches
```

Ordering matters. Adding `.gitignore` in the same commit as your first `.env` does not protect you.
