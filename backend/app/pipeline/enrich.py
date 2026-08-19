"""Weapon and actor extraction.

Stage 1 (gazetteer): word-boundary alias matching over headline + notes, emitted
with method='gazetteer', confidence=0.85, and the literal evidence span. Never
presented as confirmed fact — the UI qualifies anything below 0.6 as "possible".

Stage 2 (NER): a fine-tuned WEAPON-entity transformer is the designed extension
point (method='ner' with model confidence). It is NOT implemented here: training
it requires a hand-corrected corpus that cannot be conjured honestly in-repo.
extract_weapons() is the seam where its hits would merge with gazetteer hits.

Actors: ACLED's actor names are the canonical vocabulary. Other sources map on
via a seed alias file, then fuzzy match; unmapped actors keep their raw string
and a NULL canonical column (rendered as unmapped, never dropped).
"""

import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path

import yaml
from rapidfuzz import fuzz, process
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, EventWeapon

logger = logging.getLogger(__name__)

GAZETTEER_DIR = Path(__file__).parent / "gazetteer"
GAZETTEER_CONFIDENCE = 0.85
EVIDENCE_CONTEXT_CHARS = 60
ACTOR_FUZZY_THRESHOLD = 88.0
ACTOR_VOCAB_TTL_SECONDS = 600


@dataclass(frozen=True)
class WeaponEntry:
    key: str
    display_name: str
    category: str | None
    pattern: re.Pattern[str]


def _compile_weapons() -> list[WeaponEntry]:
    entries = []
    with open(GAZETTEER_DIR / "weapons.yaml", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    for item in raw:
        aliases = sorted((str(a) for a in item["aliases"]), key=len, reverse=True)
        # Word-boundary guard against substring collisions ("grad" in "Belgrade").
        # \b fails around Cyrillic and hyphens, so use explicit non-word lookarounds.
        alternation = "|".join(re.escape(a) for a in aliases)
        pattern = re.compile(rf"(?<![\w-])(?:{alternation})(?![\w-])", re.IGNORECASE | re.UNICODE)
        entries.append(
            WeaponEntry(
                key=item["key"],
                display_name=item["display_name"],
                category=item.get("category"),
                pattern=pattern,
            )
        )
    return entries


def _load_actor_aliases() -> dict[str, str]:
    with open(GAZETTEER_DIR / "actors.yaml", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return {str(k).strip().lower(): str(v) for k, v in raw.items()}


_WEAPONS: list[WeaponEntry] | None = None
_ACTOR_ALIASES: dict[str, str] | None = None
_actor_vocab: tuple[float, list[str]] = (0.0, [])


def weapons_gazetteer() -> list[WeaponEntry]:
    global _WEAPONS
    if _WEAPONS is None:
        _WEAPONS = _compile_weapons()
    return _WEAPONS


def actor_aliases() -> dict[str, str]:
    global _ACTOR_ALIASES
    if _ACTOR_ALIASES is None:
        _ACTOR_ALIASES = _load_actor_aliases()
    return _ACTOR_ALIASES


def extract_weapons(event_text: str) -> list[dict]:
    """Pure extraction: gazetteer hits with evidence spans. One hit per weapon key."""
    hits: dict[str, dict] = {}
    for entry in weapons_gazetteer():
        match = entry.pattern.search(event_text)
        if match is None:
            continue
        start = max(0, match.start() - EVIDENCE_CONTEXT_CHARS)
        end = min(len(event_text), match.end() + EVIDENCE_CONTEXT_CHARS)
        hits[entry.key] = {
            "weapon_key": entry.key,
            "display_name": entry.display_name,
            "category": entry.category,
            "confidence": GAZETTEER_CONFIDENCE,
            "method": "gazetteer",
            "evidence_span": event_text[start:end].strip(),
        }
    return list(hits.values())


async def acled_actor_vocabulary(session: AsyncSession) -> list[str]:
    """Distinct ACLED actor names, cached briefly; the canonical vocabulary."""
    global _actor_vocab
    stamp, vocab = _actor_vocab
    if vocab and time.monotonic() - stamp < ACTOR_VOCAB_TTL_SECONDS:
        return vocab
    rows = await session.execute(
        text(
            "SELECT DISTINCT actor FROM ("
            "  SELECT actor_a AS actor FROM events WHERE source = 'acled'"
            "  UNION SELECT actor_b FROM events WHERE source = 'acled'"
            ") t WHERE actor IS NOT NULL"
        )
    )
    vocab = [r[0] for r in rows]
    _actor_vocab = (time.monotonic(), vocab)
    return vocab


def canonicalize_actor(raw: str | None, vocabulary: list[str]) -> str | None:
    if not raw or not raw.strip():
        return None
    key = raw.strip().lower()
    alias_hit = actor_aliases().get(key)
    if alias_hit:
        return alias_hit
    if not vocabulary:
        return None
    best = process.extractOne(raw, vocabulary, scorer=fuzz.token_set_ratio)
    if best and best[1] >= ACTOR_FUZZY_THRESHOLD:
        return best[0]
    return None  # unmapped: raw string is kept on the event, flagged by NULL canonical


async def enrich_event(session: AsyncSession, event: Event) -> None:
    """Weapon extraction + actor canonicalization for one event, in place."""
    event_text = " ".join(part for part in (event.headline, event.notes) if part)
    if event_text.strip():
        for hit in extract_weapons(event_text):
            session.add(EventWeapon(event_id=event.id, **hit))

    if event.source == "acled":
        # ACLED is the canonical vocabulary; its names map to themselves.
        event.actor_a_canonical = event.actor_a
        event.actor_b_canonical = event.actor_b
    else:
        vocabulary = await acled_actor_vocabulary(session)
        event.actor_a_canonical = canonicalize_actor(event.actor_a, vocabulary)
        event.actor_b_canonical = canonicalize_actor(event.actor_b, vocabulary)
