"""Public response shapes for Guides.

Narrower than the admin shapes on purpose. A public payload carries
what the page renders and nothing else — no ``status``, because every
row here is published by construction, and no ``created_at``, because
nothing shows it. A field that is not returned cannot be leaked by a
future template that happens to print the whole object.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class GuideCard(BaseModel):
    """One Guide as it appears in a list or a grid."""

    slug: str
    title: str
    standfirst: str
    category: str
    hero_image_url: str | None
    hero_image_alt: str | None
    reading_time_minutes: int
    published_at: datetime | None
    featured: bool


class GuideArticle(BaseModel):
    """One Guide as it appears on its own page."""

    slug: str
    title: str
    standfirst: str
    body: str
    category: str
    hero_image_url: str | None
    hero_image_alt: str | None
    seo_title: str | None
    seo_description: str | None
    author_name: str
    reading_time_minutes: int
    published_at: datetime | None
    updated_at: datetime
    cta_heading: str | None
    cta_text: str | None
    cta_label: str | None
    cta_href: str | None


class GuideIndex(BaseModel):
    """Everything ``/guides`` needs, in one request.

    ``starter_kit_url`` travels with the content rather than sitting
    behind a second endpoint, so the page never renders once without
    the band and then again with it.
    """

    guides: list[GuideCard]
    starter_kit_url: str | None


class GuideArticlePage(BaseModel):
    """Everything ``/guides/{slug}`` needs, in one request."""

    guide: GuideArticle
    related: list[GuideCard]
    starter_kit_url: str | None


class SitemapGuide(BaseModel):
    """One published Guide, for the sitemap.

    Two fields, matching ``SitemapCollective``: a sitemap needs a URL
    and a date, and anything more would be a payload to keep in step
    with a page nobody reads.
    """

    slug: str
    updated_at: datetime


__all__ = [
    "GuideArticle",
    "GuideArticlePage",
    "GuideCard",
    "GuideIndex",
    "SitemapGuide",
]
