"""Guides — the public API. No authentication, published only.

One query decides what the public may see, and every endpoint here is
built on it. That is the same arrangement ``_public_space_query``
gives the Collective endpoints, and for the same reason: a draft stays
invisible because there is one place that decides, not three that
agree today.

A draft and a slug that was never used are deliberately the same
answer — 404. Distinguishing them would tell an anonymous caller that
a Guide exists and is being worked on, which is information the
admin's draft status exists to withhold.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Query, Session

from app.core.database import get_db
from app.guides.schemas import (
    GuideArticle,
    GuideArticlePage,
    GuideCard,
    GuideIndex,
    SitemapGuide,
)
from app.models.guide import Guide, GuideSettings
from app.services.guide_body import is_permitted_image_src

router = APIRouter(prefix="/api/public/guides", tags=["guides"])

#: How many "Keep reading" cards an article offers.
RELATED_LIMIT = 3


def _published(db: Session) -> Query:
    """The only query the public surface is built on."""
    return db.query(Guide).filter(Guide.status == "published")


def _starter_kit_url(db: Session) -> str | None:
    """The Creator Starter Kit link, or nothing.

    Nothing is the shipped state, and the pages read it as "render no
    band and no sidebar card at all". A value that is not a usable
    link is reported as nothing rather than as itself, so a page
    cannot end up with a button that goes somewhere unusable — the
    admin endpoint validates on write, and this is the second check
    for a row written before that validation existed.
    """
    row = (
        db.query(GuideSettings)
        .filter(GuideSettings.id == GuideSettings.SINGLETON_ID)
        .first()
    )
    value = (row.starter_kit_url or "").strip() if row else ""
    if not value:
        return None
    if value.startswith("/") and not value.startswith("//"):
        return value
    if value.startswith("http://") or value.startswith("https://"):
        return value
    return None


def _card(guide: Guide) -> GuideCard:
    return GuideCard(
        slug=guide.slug,
        title=guide.title,
        standfirst=guide.standfirst,
        category=guide.category,
        hero_image_url=_servable_hero(guide),
        hero_image_alt=guide.hero_image_alt,
        reading_time_minutes=guide.reading_time_minutes,
        published_at=guide.published_at,
        featured=guide.featured,
    )


def _servable_hero(guide: Guide) -> str | None:
    """The hero, if the browser can actually load it.

    The body's images are filtered at save time by the sanitiser; the
    hero is a plain column and never passes through it, so the same
    rule is applied here. A hero the CSP would block is better absent
    — the card falls back to its tinted panel — than present as a
    broken image.
    """
    url = (guide.hero_image_url or "").strip()
    if not url:
        return None
    return url if is_permitted_image_src(url) else None


@router.get("", response_model=GuideIndex)
def list_guides(db: Session = Depends(get_db)) -> GuideIndex:
    """Every published Guide, newest first.

    Ordered by ``published_at`` with ``id`` as the tie-break, because
    two Guides published in the same second would otherwise swap
    places between requests and the grid would appear to shuffle.
    """
    rows = (
        _published(db)
        .order_by(Guide.published_at.desc().nullslast(), Guide.id)
        .all()
    )
    return GuideIndex(
        guides=[_card(g) for g in rows],
        starter_kit_url=_starter_kit_url(db),
    )


@router.get("/sitemap", response_model=list[SitemapGuide])
def list_sitemap_guides(db: Session = Depends(get_db)) -> list[SitemapGuide]:
    """Published Guides, for ``sitemap.xml``.

    ``updated_at`` rather than ``published_at``: a sitemap's
    ``lastModified`` should say when the page last changed, and an
    edited Guide is a changed page even though it was published
    months ago.

    Declared before ``/{slug}`` so the literal path is matched first —
    otherwise this answers as a lookup for a Guide slugged "sitemap".
    """
    rows = _published(db).order_by(Guide.published_at.desc().nullslast()).all()
    return [SitemapGuide(slug=g.slug, updated_at=g.updated_at) for g in rows]


@router.get("/{slug}", response_model=GuideArticlePage)
def get_guide(slug: str, db: Session = Depends(get_db)) -> GuideArticlePage:
    """One published Guide, plus up to three to read next.

    "Keep reading" prefers the same category and falls back to the
    rest, so a category with one Guide in it still fills the row
    rather than showing a lonely single card.
    """
    guide = _published(db).filter(Guide.slug == slug.strip().lower()).first()
    if guide is None:
        raise HTTPException(status_code=404, detail="Guide not found.")

    others = (
        _published(db)
        .filter(Guide.id != guide.id)
        .order_by(Guide.published_at.desc().nullslast(), Guide.id)
        .all()
    )
    same_category = [g for g in others if g.category == guide.category]
    rest = [g for g in others if g.category != guide.category]
    related = (same_category + rest)[:RELATED_LIMIT]

    return GuideArticlePage(
        guide=GuideArticle(
            slug=guide.slug,
            title=guide.title,
            standfirst=guide.standfirst,
            body=guide.body,
            category=guide.category,
            hero_image_url=_servable_hero(guide),
            hero_image_alt=guide.hero_image_alt,
            seo_title=guide.seo_title,
            seo_description=guide.seo_description,
            author_name=guide.author_name,
            reading_time_minutes=guide.reading_time_minutes,
            published_at=guide.published_at,
            updated_at=guide.updated_at,
            cta_heading=guide.cta_heading,
            cta_text=guide.cta_text,
            cta_label=guide.cta_label,
            cta_href=guide.cta_href,
        ),
        related=[_card(g) for g in related],
        starter_kit_url=_starter_kit_url(db),
    )
