"""Request and response shapes for the Guides admin API.

Two properties are enforced here rather than in the handlers, because
a validator cannot be forgotten by a new code path:

* **Saving never publishes.** :class:`GuideUpdate` has no ``status``
  field at all. Publishing is its own endpoint, so there is no payload
  shape that could flip a draft live as a side effect of a typo fix.
* **A slug is normalised before it is compared.** Uppercase or padded
  input becomes the canonical form here, so the uniqueness check and
  the stored value can never disagree about what the slug is.
"""

from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.models.guide import GUIDE_CATEGORIES, DEFAULT_AUTHOR_NAME

#: Lowercase words joined by single hyphens. No leading, trailing or
#: doubled hyphens, so one slug has one spelling.
SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _normalise_slug(value: str) -> str:
    clean = value.strip().lower()
    if not SLUG_PATTERN.match(clean):
        raise ValueError(
            "slug must be lowercase words joined by hyphens, "
            "e.g. 'moving-your-community'",
        )
    return clean


def _validate_category(value: str) -> str:
    if value not in GUIDE_CATEGORIES:
        raise ValueError(f"category must be one of {list(GUIDE_CATEGORIES)}")
    return value


# ---------------------------------------------------------------------------
# Read models
# ---------------------------------------------------------------------------


class GuideListRow(BaseModel):
    """Row shape for the admin list page."""

    id: str
    slug: str
    title: str
    category: str
    status: str
    featured: bool
    published_at: datetime | None
    updated_at: datetime
    reading_time_minutes: int


class GuideDetail(BaseModel):
    """Everything the editor loads and saves."""

    id: str
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
    featured: bool
    status: str
    published_at: datetime | None
    reading_time_minutes: int
    cta_heading: str | None
    cta_text: str | None
    cta_label: str | None
    cta_href: str | None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Write models
# ---------------------------------------------------------------------------


class GuideCreate(BaseModel):
    """A new Guide. Always created as a draft — there is no status here."""

    title: str = Field(min_length=1, max_length=200)
    slug: str = Field(min_length=1, max_length=160)
    category: str

    @field_validator("slug")
    @classmethod
    def _valid_slug(cls, v: str) -> str:
        return _normalise_slug(v)

    @field_validator("category")
    @classmethod
    def _valid_category(cls, v: str) -> str:
        return _validate_category(v)


class GuideUpdate(BaseModel):
    """A save. Deliberately carries no ``status``.

    Every field is optional so the editor can PATCH what changed, and
    the nullable ones accept an explicit ``null`` to clear.
    """

    title: str | None = Field(default=None, min_length=1, max_length=200)
    slug: str | None = Field(default=None, min_length=1, max_length=160)
    standfirst: str | None = Field(default=None, max_length=600)
    body: str | None = None
    category: str | None = None
    hero_image_url: str | None = None
    hero_image_alt: str | None = Field(default=None, max_length=300)
    seo_title: str | None = Field(default=None, max_length=120)
    seo_description: str | None = Field(default=None, max_length=300)
    author_name: str | None = Field(default=None, min_length=1, max_length=120)
    cta_heading: str | None = Field(default=None, max_length=160)
    cta_text: str | None = Field(default=None, max_length=300)
    cta_label: str | None = Field(default=None, max_length=80)
    cta_href: str | None = None

    @field_validator("slug")
    @classmethod
    def _valid_slug(cls, v: str | None) -> str | None:
        return None if v is None else _normalise_slug(v)

    @field_validator("category")
    @classmethod
    def _valid_category(cls, v: str | None) -> str | None:
        return None if v is None else _validate_category(v)


class GuideFeature(BaseModel):
    """Feature or unfeature. One field, so the intent is explicit."""

    featured: bool


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


class GuideSettingsRead(BaseModel):
    starter_kit_url: str | None
    updated_at: datetime


class GuideSettingsUpdate(BaseModel):
    """The Creator Starter Kit link, or nothing.

    An empty string is accepted and stored as ``None`` — clearing a
    text field by selecting its contents and deleting them is how a
    person clears a text field, and it should not be an error.
    """

    starter_kit_url: str | None = Field(default=None, max_length=2048)


__all__ = [
    "GuideCreate",
    "GuideDetail",
    "GuideFeature",
    "GuideListRow",
    "GuideSettingsRead",
    "GuideSettingsUpdate",
    "GuideUpdate",
    "SLUG_PATTERN",
    "DEFAULT_AUTHOR_NAME",
]
