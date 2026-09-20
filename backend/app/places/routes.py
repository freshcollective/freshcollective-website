"""
/api/places — the read + resolve surface for real-world Places.

Places are the geographic layer of the Discovery, Connection &
Belonging pillar (see
``docs/foundations/discovery-connection-belonging-v1.1.md``).

Endpoints:

  * ``GET  /api/places``             — list active Places (public read)
  * ``POST /api/places/lookup``      — autocomplete suggestions
                                        (Creator-only, proxied via the
                                        configured location provider)
  * ``POST /api/places/resolve``     — turn a picker selection into a
                                        stored Place row, deduplicating
                                        by provider_place_id

The whole surface is gated by ``settings.discovery_pillar_enabled``.
When the flag is off every endpoint returns 503 — matching the
convention set by Community Care — so a half-built surface can't be
discovered by accident.

Provider abstraction lives in
``app/services/location_providers/`` — see there for how to swap
away from Nominatim later.
"""

from __future__ import annotations

import math
import uuid
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.dependencies import get_creator_user
from app.core.config import settings
from app.core.database import get_db
from app.models.place import Place, SpacePlace
from app.models.platform import Event, EventSeries, Space, SpaceStatus
from app.spaces import area_policies
from app.models.user import User
from app.spaces.schemas import PublicSpaceCard
from app.services.location_providers import (
    LocationSuggestion,
    get_location_provider,
)
from app.spaces.routes import hydrate_public_space_cards


router = APIRouter(prefix="/api/places", tags=["places"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class PlaceSummary(BaseModel):
    """Public shape for a Place.

    Includes curated artwork fields when set. Discover Places
    prefers ``hero_artwork_url`` over the deterministic atmosphere
    fallback; when it is ``None``, the client falls back to the
    per-slug gradient. The focal point governs cropped renderings
    (CSS ``object-position``) so meaningful subjects stay in-frame.

    Also carries a small "what's happening here" summary — the
    admin-authored blurb, an aggregate theme list from linked
    active Collectives, and counts — so a Discover Places card can
    render without a second round-trip. Nothing here reveals the
    identity of individual Collectives; that's the /discover-places
    detail page's job (not built yet).
    """

    model_config = {"from_attributes": True}

    id: str
    slug: str
    name: str
    country_code: str
    region: str | None
    hero_artwork_url: str | None
    artwork_alt_text: str | None
    artwork_focal_x: float
    artwork_focal_y: float
    blurb: str | None
    themes: list[str]
    collective_count: int
    upcoming_gathering_count: int


class PlaceSeries(BaseModel):
    """One member-facing Gathering Series, standing in for all of its
    upcoming occurrences on a Place page.

    EMBODY's Term 4 is thirty sessions. Rendered individually they were
    thirty near-identical cards reading "Mondays - Term 4",
    "Thursdays - Term 4" — activity presented as noise. One card that
    says what the Series is, when it runs and how often it meets is the
    same information, legible.

    Grouping is by ``Event.series_id`` — the semantic membership the
    model documents — never by ``recurrence_series_id``, which only
    records that some rows were bulk-created together. EMBODY's Term 4
    is one Series but three recurrence batches (Mondays, Thursdays,
    Saturdays); grouping by provenance would have produced three cards
    that mean nothing to a member.

    Every field is derived from the *eligible* occurrences only, so a
    Series can never widen what a Place page shows. See
    ``get_place`` for the eligibility rule.
    """

    id: str
    slug: str
    title: str
    space_slug: str
    space_name: str
    # First and last eligible upcoming occurrence — the window a
    # visitor can actually still join, not the Series' own declared
    # window, which may have started in the past.
    first_starts_at: datetime
    last_starts_at: datetime
    occurrence_count: int
    # "Mon & Thu 6pm · Sat 9am", in the Collective's timezone. None
    # when the pattern is too irregular to summarise.
    schedule_summary: str | None
    # Taken from the earliest eligible occurrence; a Series that mixes
    # formats or venues is described by the one a visitor meets first.
    gathering_type: str | None
    attendance_format: str | None
    venue_name: str | None
    cover_image_url: str | None
    collective_primary_colour: str | None
    collective_accent_colour: str | None


class PlaceGathering(BaseModel):
    """Member-safe public projection of an upcoming Gathering on a
    Physical Location detail page. Never exposes venue address or
    private access instructions — those are enrolment-gated on the
    Gathering's own detail page.

    Carries the parent Collective's Colour Palette hexes (primary +
    accent) so Gathering cards can visually inherit the Collective's
    personality without a second round-trip. This encodes the
    platform rule: Places have identity, Collectives have
    personality, Gatherings inherit their Collective's personality.
    In FC's seeded palettes, ``primary`` is the deep saturated
    emphasis hex (used for borders / titles); ``accent`` is the warm
    complementary hex (used for the background wash). Both null when
    the Collective has no palette assigned — the client falls back
    to a neutral rendering.
    """

    id: str
    title: str
    space_slug: str
    space_name: str
    starts_at: datetime
    ends_at: datetime | None
    gathering_type: str
    attendance_format: str        # online | in_person | hybrid
    venue_name: str | None        # coarse locality only — never the address
    booking_access_type: str
    capacity: int | None
    ticket_price_cents: int | None
    ticket_currency: str | None
    thumbnail_url: str | None
    collective_primary_colour: str | None  # deep emphasis hex — border + title
    collective_accent_colour: str | None   # warm complement — background wash


class PlaceDetail(BaseModel):
    """Full public detail for a single Physical Location — powers the
    /discover-places/{slug} member page. Bundles the location's own
    payload, the list of Collectives that belong here (in the same
    ``PublicSpaceCard`` shape the Explore Collectives listing uses,
    so both pages render with the same card component), and the
    upcoming Gatherings that are eligible for members to see.

    Admin-only fields never leak: ``admin_note``, coordinates,
    ``provider_place_id`` and status are all absent."""

    id: str
    slug: str
    name: str
    country_code: str
    region: str | None
    hero_artwork_url: str | None
    artwork_alt_text: str | None
    artwork_focal_x: float
    artwork_focal_y: float
    blurb: str | None
    themes: list[str]
    collective_count: int
    upcoming_gathering_count: int
    collectives: list[PublicSpaceCard]
    # Series first, then the gatherings that belong to no Series. The
    # client merges the two and sorts by next occurrence; they are
    # returned separately because they render as different cards and
    # because the split is a server-side decision — a Series only
    # groups when it is published, so a card can never link to a page
    # that 404s.
    upcoming_series: list[PlaceSeries]
    upcoming_gatherings: list[PlaceGathering]


class LookupRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=200)


class LookupResult(BaseModel):
    """One suggestion row the picker renders."""

    provider_place_id: str
    display: str
    name: str
    region: str
    country: str
    country_code: str
    latitude: float
    longitude: float

    @classmethod
    def from_suggestion(cls, s: LocationSuggestion) -> "LookupResult":
        return cls(
            provider_place_id=s.provider_place_id,
            display=s.display,
            name=s.name,
            region=s.region,
            country=s.country,
            country_code=s.country_code,
            latitude=s.latitude,
            longitude=s.longitude,
        )


class LookupResponse(BaseModel):
    results: list[LookupResult]


class ResolveRequest(BaseModel):
    """The picker's canonical id is enough — the provider is
    re-queried server-side to get the authoritative payload. The
    client cannot spoof a Place's name or coordinates."""

    provider_place_id: str = Field(..., min_length=1, max_length=200)


class ResolveResponse(BaseModel):
    """The Place row that was found or created."""

    model_config = {"from_attributes": True}

    id: str
    slug: str
    name: str
    country_code: str
    region: str | None
    latitude: float | None
    longitude: float | None
    timezone: str | None
    provider_place_id: str | None
    created: bool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ensure_discovery_flag_on() -> None:
    """Refuse when the Discovery pillar is not yet enabled."""
    if not settings.discovery_pillar_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Discovery is not yet enabled on this deployment.",
        )


# ---------------------------------------------------------------------------
# Series schedule summary
# ---------------------------------------------------------------------------

# Weekday order for rendering, Monday first.
_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

# Above this many distinct time-of-day groups the summary stops being a
# summary. A Series that meets at five different times is better
# described by its own Schedule page than by a string on a card.
_MAX_SCHEDULE_GROUPS = 3

# Safety bound on how many upcoming occurrences one Place page scans to
# build its Series summaries. Far above real volumes; present so a data
# accident cannot turn a page render into an unbounded query.
_MAX_UPCOMING_SCANNED = 500

# How many individual (series-less) Gatherings a Place page lists.
# Series collapse to one card each, so this bounds only the long tail.
_MAX_STANDALONE_SHOWN = 20


def _time_label(moment: datetime) -> str:
    """``6pm`` / ``9:30am`` — minutes only when they carry information."""
    hour = moment.hour % 12 or 12
    suffix = "am" if moment.hour < 12 else "pm"
    if moment.minute:
        return f"{hour}:{moment.minute:02d}{suffix}"
    return f"{hour}{suffix}"


def schedule_summary(starts: list[datetime], timezone_name: str | None) -> str | None:
    """A compact "when does this meet" line, e.g. ``Mon & Thu 6pm · Sat 9am``.

    Built from the eligible occurrences themselves rather than from a
    stored recurrence rule, because the eligible set is what the member
    will actually be able to attend — a cancelled Monday does not
    belong in the pattern.

    Times are rendered in the **Collective's** timezone. A Gathering in
    South Croydon reads "6pm" to everyone, which is what the Collective
    means by it, rather than shifting for whoever is looking.

    Returns ``None`` when there is nothing useful to say: no
    occurrences, or so many distinct times that the line would be
    longer than the card.
    """
    if not starts:
        return None
    try:
        tz = ZoneInfo(timezone_name or "UTC")
    except Exception:  # noqa: BLE001 — a bad tz string must not break a page
        tz = ZoneInfo("UTC")

    # starts_at is stored naive-UTC throughout this codebase.
    local = [s.replace(tzinfo=UTC).astimezone(tz) for s in starts]

    by_time: dict[str, set[int]] = {}
    for moment in local:
        by_time.setdefault(_time_label(moment), set()).add(moment.weekday())
    if len(by_time) > _MAX_SCHEDULE_GROUPS:
        return None

    # Order groups by their earliest weekday so the line reads
    # chronologically across the week.
    groups = sorted(by_time.items(), key=lambda kv: min(kv[1]))
    parts = []
    for label, weekdays in groups:
        names = " & ".join(_WEEKDAYS[d] for d in sorted(weekdays))
        parts.append(f"{names} {label}")
    return " · ".join(parts)


def _slugify(name: str, country_code: str) -> str:
    """Derive a URL-safe slug from a Place name.

    Kept deterministic and readable — "Byron Bay, AU" → "byron-bay".
    Collisions are handled by ``_resolve_slug`` at insert time.
    """
    base = "".join(
        c.lower() if c.isalnum() else "-"
        for c in name.strip()
    )
    # Collapse runs of dashes, strip edges.
    while "--" in base:
        base = base.replace("--", "-")
    return base.strip("-") or country_code.lower()


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance between two lat/lng points, in kilometres.
    Sufficient precision for the picker-to-Place absorption radius —
    Places are curated at city / broad-region granularity, not to the
    metre."""
    r = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# Radius within which a picker suggestion is treated as "the same
# discovery area" as an existing active Place. Chosen to cover a metro
# region's Nominatim variants (Melbourne, City of Melbourne, Greater
# Melbourne all resolve to the curated Melbourne) without swallowing
# nearby distinct cities. Editorial Places are city-scale, so ~25 km
# is a comfortable metro radius and well short of the next city.
PLACE_ABSORPTION_RADIUS_KM = 25.0


def _find_absorbing_active_place(
    db: Session,
    *,
    lat: float | None,
    lng: float | None,
    country_code: str | None,
    radius_km: float = PLACE_ABSORPTION_RADIUS_KM,
) -> Place | None:
    """Return the active Place whose curated area absorbs a picker
    coordinate — the closest active Place within ``radius_km`` in the
    same country, or None if nothing is near enough.

    Why: the picker's provider (Nominatim) exposes multiple OSM
    features for the same city (e.g. Melbourne, City of Melbourne,
    Greater Melbourne). Deduplicating on ``provider_place_id`` alone
    means a Creator who happens to pick a different variant creates
    a fresh draft that a World Management admin then has to merge
    into the curated Melbourne. The intent of Discover Places is that
    a Creator's link to an approved discovery area should be
    automatic — no admin step should sit between saving a location
    and appearing on the location detail page. This absorbing lookup
    closes that gap while still deferring genuinely new cities /
    regions to admin curation (draft rows) as before.
    """
    if lat is None or lng is None or not country_code:
        return None
    candidates = db.execute(
        select(Place).where(
            Place.status == "active",
            Place.country_code == country_code.upper(),
            Place.latitude.isnot(None),
            Place.longitude.isnot(None),
        )
    ).scalars().all()
    best: Place | None = None
    best_km = radius_km
    for p in candidates:
        # Narrowed above; the isnot(None) filter keeps the type checker
        # happy at runtime — assert them so mypy-style intent is clear.
        assert p.latitude is not None and p.longitude is not None
        km = _haversine_km(lat, lng, p.latitude, p.longitude)
        if km < best_km:
            best = p
            best_km = km
    return best


def _resolve_slug(db: Session, base_slug: str) -> str:
    """Find a free slug. Appends ``-2``, ``-3``... on collision.

    Rare in practice — cities that share a name across countries
    would collide (e.g. Melbourne AU vs Melbourne US), and this
    ensures the second one gets ``melbourne-2`` rather than
    failing. Deduplication by provider_place_id happens above this;
    slug collision is only reached for genuinely different Places
    that share a name.
    """
    if not db.execute(select(Place).where(Place.slug == base_slug)).scalar_one_or_none():
        return base_slug
    n = 2
    while True:
        candidate = f"{base_slug}-{n}"
        if not db.execute(select(Place).where(Place.slug == candidate)).scalar_one_or_none():
            return candidate
        n += 1


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("", response_model=list[PlaceSummary])

def _space_gatherings_are_public():
    """SQL mirror of ``area_policies.resolve_policies(...)['gatherings']
    == 'public'``.

    The default is ``members``, so a Collective that has never
    configured its areas — ``area_policies IS NULL`` — is *not* public
    here. Expressed in SQL rather than Python because this runs inside
    an aggregate over every Place at once; ``area_policies.py`` stays
    the authority on what the values mean, and this must be kept in
    step with it. One shape, checked by test.
    """
    from sqlalchemy import text as _text
    return _text(
        "spaces.area_policies IS NOT NULL "
        "AND spaces.area_policies -> 'areas' ->> 'gatherings' = 'public'"
    )


def list_places(db: Session = Depends(get_db)) -> list[PlaceSummary]:
    """List every active Place with a small activity summary.

    Draft, hidden, and archived Places never appear here — only
    ``active`` rows. No pagination — Places are editorial and rare;
    the list is expected to stay small enough for a single response
    for a long time. When that changes, extend the shape.
    """
    _ensure_discovery_flag_on()

    places = db.execute(
        select(Place)
        .where(Place.status == "active")
        .order_by(Place.name)
    ).scalars().all()

    if not places:
        return []

    place_ids = [p.id for p in places]

    # Active Collective count per Place — one aggregate query.
    count_rows = db.execute(
        select(SpacePlace.place_id, func.count(Space.id))
        .join(Space, Space.id == SpacePlace.space_id)
        .where(
            SpacePlace.place_id.in_(place_ids),
            Space.status == SpaceStatus.active,
        )
        .group_by(SpacePlace.place_id)
    ).all()
    counts_by_place: dict[str, int] = {pid: int(c) for pid, c in count_rows}

    # Themes aggregated from linked active Collectives — dedup +
    # preserve first-appearance order for stability. Fetched in one
    # query so we don't do N+1.
    theme_rows = db.execute(
        select(SpacePlace.place_id, Space.themes)
        .join(Space, Space.id == SpacePlace.space_id)
        .where(
            SpacePlace.place_id.in_(place_ids),
            Space.status == SpaceStatus.active,
        )
    ).all()
    themes_by_place: dict[str, list[str]] = {pid: [] for pid in place_ids}
    for place_id, themes in theme_rows:
        seen = set(themes_by_place[place_id])
        for t in themes or []:
            if t and t not in seen:
                themes_by_place[place_id].append(t)
                seen.add(t)

    # Upcoming published gatherings per Place — Events on linked
    # active Collectives with ``starts_at`` in the future.
    now = datetime.utcnow()
    # Counted the same way the detail page lists them, or the card
    # advertises "6 upcoming gatherings" for a Place whose Gatherings
    # are all behind a members-only door — a number that is itself a
    # disclosure, and a promise the next click cannot keep.
    gather_rows = db.execute(
        select(SpacePlace.place_id, func.count(Event.id))
        .join(Space, Space.id == SpacePlace.space_id)
        .join(Event, Event.space_id == Space.id)
        .where(
            SpacePlace.place_id.in_(place_ids),
            Space.status == SpaceStatus.active,
            Event.is_published.is_(True),
            Event.starts_at > now,
            _space_gatherings_are_public(),
        )
        .group_by(SpacePlace.place_id)
    ).all()
    upcoming_by_place: dict[str, int] = {pid: int(c) for pid, c in gather_rows}

    return [
        PlaceSummary(
            id=p.id,
            slug=p.slug,
            name=p.name,
            country_code=p.country_code,
            region=p.region,
            hero_artwork_url=p.hero_artwork_url,
            artwork_alt_text=p.artwork_alt_text,
            artwork_focal_x=p.artwork_focal_x,
            artwork_focal_y=p.artwork_focal_y,
            blurb=p.blurb,
            themes=themes_by_place.get(p.id, []),
            collective_count=counts_by_place.get(p.id, 0),
            upcoming_gathering_count=upcoming_by_place.get(p.id, 0),
        )
        for p in places
    ]


@router.get("/{slug}", response_model=PlaceDetail)
def get_place(slug: str, db: Session = Depends(get_db)) -> PlaceDetail:
    """Public detail for a single active Physical Location.

    Draft, hidden, and archived Locations 404 here — the same rule
    the list surface uses. The payload bundles the Location's own
    public fields, the Collectives that belong here (rendered with
    the same ``PublicSpaceCard`` shape as Explore Collectives so
    the same card component can be reused visually), and the
    upcoming public / effectively-public Gatherings on those
    Collectives.
    """
    _ensure_discovery_flag_on()

    place = db.execute(
        select(Place).where(Place.slug == slug, Place.status == "active")
    ).scalar_one_or_none()
    if place is None:
        raise HTTPException(status_code=404, detail="Physical Location not found.")

    # Linked Collectives — same public filter as /api/public/spaces
    # (active + public + not auto-grant). ``hydrate_public_space_cards``
    # produces the identical shape the Explore listing uses.
    linked_spaces = db.execute(
        select(Space)
        .join(SpacePlace, SpacePlace.space_id == Space.id)
        .where(
            SpacePlace.place_id == place.id,
            Space.status == SpaceStatus.active,
            Space.is_public.is_(True),
            Space.auto_grant_role.is_(None),
        )
        .order_by(Space.created_at)
    ).scalars().all()
    collectives = hydrate_public_space_cards(list(linked_spaces), db)

    # Upcoming gatherings — published, future, and either explicitly
    # public or effectively public (``paid_separately`` tickets show
    # up on the paid Gathering surface for anyone). The same rule the
    # Space events endpoint applies for anonymous callers.
    gatherings: list[PlaceGathering] = []
    upcoming_series: list[PlaceSeries] = []
    # Discover Places is an anonymous public surface, so it may only
    # show Gatherings from Collectives whose Gatherings area is public.
    # Without this it is a back door: a Collective that set Gatherings
    # to members-only would still have its schedule listed here, which
    # is exactly the leak the area policy exists to close. Resolved in
    # Python from a column already loaded — no extra query.
    gatherings_public_spaces = [
        sp for sp in linked_spaces
        if area_policies.resolve_policies(sp.area_policies).get(
            area_policies.AREA_GATHERINGS,
        ) == area_policies.POLICY_PUBLIC
    ]
    if gatherings_public_spaces:
        space_by_id = {sp.id: sp for sp in gatherings_public_spaces}
        # Per-Collective palette hexes so each Gathering card can inherit
        # its parent Collective's personality. One aggregate lookup keyed
        # by ``colour_story_key`` — avoids N+1 for pages where several
        # Collectives share the same palette. Primary drives the deep
        # border + title; accent drives the warm background wash.
        from app.models.platform import ColourStory
        palette_keys = {
            s.colour_story_key for s in linked_spaces if s.colour_story_key
        }
        palette_by_key: dict[str, tuple[str | None, str | None]] = {}
        if palette_keys:
            cs_rows = db.execute(
                select(ColourStory).where(ColourStory.key.in_(palette_keys))
            ).scalars().all()
            for cs in cs_rows:
                pal = cs.palette or {}
                palette_by_key[cs.key] = (pal.get("primary"), pal.get("accent"))
        palette_by_space: dict[str, tuple[str | None, str | None]] = {
            s.id: palette_by_key.get(s.colour_story_key or "", (None, None))
            for s in linked_spaces
        }
        now = datetime.utcnow()
        # Every eligible upcoming occurrence, not a page of them: the
        # Series summaries below (window, count, schedule) are only
        # true if they see the whole set. The cap is a safety bound far
        # above any real Place — EMBODY's busiest term is ~30 — so that
        # a data accident cannot turn this into an unbounded scan.
        event_rows = db.execute(
            select(Event)
            .where(
                Event.space_id.in_(list(space_by_id.keys())),
                Event.is_published.is_(True),
                Event.starts_at > now,
                Event.status == "active",
                (Event.is_public.is_(True)) | (Event.booking_access_type == "paid_separately"),
            )
            .order_by(Event.starts_at)
            .limit(_MAX_UPCOMING_SCANNED)
        ).scalars().all()

        # Which Series may legitimately stand in for their occurrences.
        # Only published ones: the member-facing Series page 404s on
        # anything else (see ``_get_published_series``), so grouping
        # under a draft or archived Series would hand a visitor a card
        # that leads nowhere. Occurrences of an unpublished Series stay
        # eligible in their own right and simply render individually.
        series_ids = {e.series_id for e in event_rows if e.series_id}
        published_series: dict[str, EventSeries] = {}
        if series_ids:
            published_series = {
                row.id: row
                for row in db.execute(
                    select(EventSeries).where(
                        EventSeries.id.in_(series_ids),
                        EventSeries.status == "published",
                    )
                ).scalars().all()
            }

        grouped: dict[str, list[Event]] = {}
        standalone: list[Event] = []
        for e in event_rows:
            if e.series_id and e.series_id in published_series:
                grouped.setdefault(e.series_id, []).append(e)
            else:
                standalone.append(e)

        for series_id, occurrences in grouped.items():
            series = published_series[series_id]
            # ``event_rows`` is ordered by starts_at, so the first
            # occurrence is the soonest and the last is the furthest out.
            first, last = occurrences[0], occurrences[-1]
            space = space_by_id[first.space_id]
            upcoming_series.append(PlaceSeries(
                id=series.id,
                slug=series.slug,
                title=series.title,
                space_slug=space.slug,
                space_name=space.name,
                first_starts_at=first.starts_at,
                last_starts_at=last.starts_at,
                occurrence_count=len(occurrences),
                schedule_summary=schedule_summary(
                    [o.starts_at for o in occurrences], space.timezone,
                ),
                gathering_type=first.gathering_type,
                attendance_format=first.attendance_format,
                venue_name=first.venue_name,
                cover_image_url=series.cover_image_url,
                collective_primary_colour=palette_by_space.get(space.id, (None, None))[0],
                collective_accent_colour=palette_by_space.get(space.id, (None, None))[1],
            ))
        upcoming_series.sort(key=lambda x: x.first_starts_at)

        gatherings = [
            PlaceGathering(
                id=e.id,
                title=e.title,
                space_slug=space_by_id[e.space_id].slug,
                space_name=space_by_id[e.space_id].name,
                starts_at=e.starts_at,
                ends_at=e.ends_at,
                gathering_type=e.gathering_type,
                attendance_format=e.attendance_format,
                # venue_name is the coarse locality (e.g. "Private
                # residence · South Croydon"); the full address stays
                # gated on the Gathering's own detail page.
                venue_name=e.venue_name,
                booking_access_type=e.booking_access_type,
                capacity=e.capacity,
                ticket_price_cents=e.ticket_price_cents,
                ticket_currency=e.ticket_currency,
                thumbnail_url=e.thumbnail_url,
                collective_primary_colour=palette_by_space.get(e.space_id, (None, None))[0],
                collective_accent_colour=palette_by_space.get(e.space_id, (None, None))[1],
            )
            for e in standalone[:_MAX_STANDALONE_SHOWN]
        ]

    # Aggregate themes + counts identical to the list endpoint so the
    # detail card header can display the same numbers.
    seen: set[str] = set()
    theme_order: list[str] = []
    for s in linked_spaces:
        for t in s.themes or []:
            if t and t not in seen:
                seen.add(t)
                theme_order.append(t)
    upcoming_all_count = db.execute(
        select(func.count(Event.id)).where(
            Event.space_id.in_([s.id for s in linked_spaces]) if linked_spaces else False,
            Event.is_published.is_(True),
            Event.starts_at > datetime.utcnow(),
        )
    ).scalar_one() if linked_spaces else 0

    return PlaceDetail(
        id=place.id,
        slug=place.slug,
        name=place.name,
        country_code=place.country_code,
        region=place.region,
        hero_artwork_url=place.hero_artwork_url,
        artwork_alt_text=place.artwork_alt_text,
        artwork_focal_x=place.artwork_focal_x,
        artwork_focal_y=place.artwork_focal_y,
        blurb=place.blurb,
        themes=theme_order,
        collective_count=len(linked_spaces),
        upcoming_gathering_count=int(upcoming_all_count),
        collectives=collectives,
        upcoming_series=upcoming_series,
        upcoming_gatherings=gatherings,
    )


@router.post("/lookup", response_model=LookupResponse)
async def lookup_places(
    payload: LookupRequest,
    _user: User = Depends(get_creator_user),
) -> LookupResponse:
    """Autocomplete for the Place & Feel picker.

    Creator-only. The response never touches the database — it is a
    thin proxy to the configured provider. The client posts what the
    Creator picked back to ``/resolve`` when they select a row.
    """
    _ensure_discovery_flag_on()

    provider = get_location_provider()
    suggestions = await provider.search(payload.query, limit=6)
    return LookupResponse(
        results=[LookupResult.from_suggestion(s) for s in suggestions]
    )


@router.post("/resolve", response_model=ResolveResponse)
async def resolve_place(
    payload: ResolveRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_creator_user),
) -> ResolveResponse:
    """Turn a picker selection into a persisted Place row.

    Idempotent by ``provider_place_id``: if a Place with the same
    provider id already exists, return it. Otherwise, re-fetch the
    canonical suggestion from the provider (so the client cannot lie
    about name or coordinates) and create the Place **as a draft**.

    Draft status is deliberate: the provider result may be at any
    granularity (a suburb, a venue, an obscure hamlet), but
    Discover Places is a curated surface for **broad discovery
    areas** (see ``app.models.place``). Marking picker-created rows
    as ``draft`` means:

      * a Creator's Collective can still be linked to the Place
        immediately (SpacePlace is orthogonal to status);
      * Discover Places never surfaces the row until an admin
        reviews it and either promotes it to ``active`` (with the
        broad name they want members to see), merges it into an
        existing broader Place, or leaves it as draft.

    The public-facing name is therefore always an admin decision,
    never a raw provider payload.
    """
    _ensure_discovery_flag_on()

    existing = db.execute(
        select(Place).where(Place.provider_place_id == payload.provider_place_id)
    ).scalar_one_or_none()
    if existing is not None:
        return _to_response(existing, created=False)

    provider = get_location_provider()
    suggestion = await provider.fetch(payload.provider_place_id)
    if suggestion is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="That place could not be resolved. Please pick again.",
        )

    # Absorb into an existing active Place if the picker landed inside
    # a curated discovery area. This makes the "Creator selects an
    # approved active Physical Location → appears on Discover Places
    # without admin intervention" flow work regardless of which
    # Nominatim variant the Creator happens to click.
    absorbed = _find_absorbing_active_place(
        db,
        lat=suggestion.latitude,
        lng=suggestion.longitude,
        country_code=suggestion.country_code,
    )
    if absorbed is not None:
        return _to_response(absorbed, created=False)

    place = Place(
        id=f"place_{uuid.uuid4().hex[:12]}",
        slug=_resolve_slug(db, _slugify(suggestion.name, suggestion.country_code)),
        name=suggestion.name,
        country_code=suggestion.country_code or "??",
        region=suggestion.region or None,
        latitude=suggestion.latitude,
        longitude=suggestion.longitude,
        timezone=suggestion.timezone,
        provider_place_id=suggestion.provider_place_id,
        status="draft",
    )
    db.add(place)
    db.commit()
    db.refresh(place)
    return _to_response(place, created=True)


def _to_response(place: Place, *, created: bool) -> ResolveResponse:
    return ResolveResponse(
        id=place.id,
        slug=place.slug,
        name=place.name,
        country_code=place.country_code,
        region=place.region,
        latitude=place.latitude,
        longitude=place.longitude,
        timezone=place.timezone,
        provider_place_id=place.provider_place_id,
        created=created,
    )
