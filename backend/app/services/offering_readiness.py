"""Can this Offering be published, and if not, what is missing?

One function, consulted twice and trusted once. The creator's editor
calls it to show a checklist; the publish endpoint calls it again and
acts on the result. **The endpoint never trusts an earlier readiness
response** — a creator could have deleted a file, or a file could have
been quarantined, between the two calls.

Shape of the answer
-------------------

A list of named requirements, each pass or fail with creator-facing
prose. Returning the whole list rather than the first failure is
deliberate: a creator who is missing three things should learn all
three at once instead of discovering them one publish attempt at a
time.

The About section is absent from this list on purpose. Rich content is
optional by product decision, so it is not a requirement and must not
appear as one — not even as a passing row, which would imply it had
been checked for adequacy.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.offering import (
    Offering,
    OfferingFile,
    OfferingFileValidationStatus as FVS,
    OfferingPricingKind,
)
from app.models.platform import Space
from app.models.user import User


@dataclass(frozen=True)
class Requirement:
    """One publication requirement and whether it is met."""

    id: str
    met: bool
    #: Shown to the creator when unmet. Plain, actionable, and never a
    #: description of a security mechanism.
    message: str

    def as_dict(self) -> dict:
        return {"id": self.id, "met": self.met, "message": self.message}


@dataclass(frozen=True)
class Readiness:
    ready: bool
    requirements: list[Requirement]

    def as_dict(self) -> dict:
        return {
            "ready": self.ready,
            "requirements": [r.as_dict() for r in self.requirements],
        }

    @property
    def unmet_ids(self) -> list[str]:
        return [r.id for r in self.requirements if not r.met]


#: Cover images that are platform-provided rather than creator-uploaded.
#:
#: Curated default covers live under the existing ``platform-artwork/``
#: prefix — the same place brand assets already live, served by the
#: existing unauthenticated route, because they are platform-owned
#: imagery shown to anyone who can see the Offering. Using that prefix
#: means default covers need **no change to media-security rules**: the
#: public read path already exists for exactly this class of asset.
#:
#: Creator-uploaded covers use the private ``offering-covers/`` prefix
#: and are gated by ``_authorise_offering_cover``.
_DEFAULT_COVER_PREFIX = "/api/uploads/platform-artwork/offering-covers/"
_UPLOADED_COVER_PREFIX = "/api/uploads/offering-covers/"


#: A curated default is a single flat filename under its prefix —
#: ``workbook.png``, not ``a/b/c.png``. Verified against the serving
#: architecture: such a key routes to the PUBLIC bucket and is served by
#: ``serve_public_upload``, the same unauthenticated route brand assets
#: already use, so no media-security rule changes to support it.
_DEFAULT_COVER_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,60}\.(png|jpg|jpeg|webp)$")

#: A creator upload is ``{offering_id}/{uuid}_{name}`` under its prefix,
#: which routes to the PRIVATE bucket and through
#: ``_authorise_offering_cover``.
_UPLOADED_COVER_PATH = re.compile(
    r"^[A-Za-z0-9_-]{1,64}/[A-Za-z0-9._-]{1,200}$"
)


def is_acceptable_cover(url: str | None) -> bool:
    """Is this a cover we are willing to publish?

    An allow-list of two shapes, not a URL validator.
    ``validate_media_url`` accepts any ``https`` URL, which is right for
    a content block and wrong here: a cover is chrome on a member-facing
    card, and letting a creator point it at an arbitrary host would mean
    an off-platform request on every page view — blocked by our CSP in
    practice, but a silently broken image is a poor way to discover that.

    The two shapes are matched precisely rather than by prefix alone, so
    a creator cannot set an arbitrary deep path under either namespace.
    What this does **not** check is existence: until the curated set
    ships there is nothing to check against. When it does, the right
    tightening is a manifest constant listing the real filenames —
    recorded here so it is a known gap rather than an oversight.
    """
    if not url:
        return False
    if url.startswith(_DEFAULT_COVER_PREFIX):
        return bool(
            _DEFAULT_COVER_NAME.match(url[len(_DEFAULT_COVER_PREFIX):])
        )
    if url.startswith(_UPLOADED_COVER_PREFIX):
        return bool(
            _UPLOADED_COVER_PATH.match(url[len(_UPLOADED_COVER_PREFIX):])
        )
    return False


def evaluate(
    db: Session, *, offering: Offering, space: Space, owner: User,
) -> Readiness:
    """Assemble the checklist. Read-only; takes no locks.

    ``owner`` is the Collective's owner rather than the caller, because
    plan eligibility follows the Collective's owner — the same reasoning
    ``guard_member_allowance`` uses when it resolves the owner's plan
    rather than the joining member's.
    """
    from app.creator.plan_guards import is_platform_owner, resolve_creator_plan

    reqs: list[Requirement] = []

    title = (offering.title or "").strip()
    reqs.append(Requirement(
        "title", bool(title),
        "Give this Offering a title.",
    ))

    summary = (offering.summary or "").strip()
    reqs.append(Requirement(
        "summary", bool(summary),
        "Add a short description — it appears on cards and listings.",
    ))

    reqs.append(Requirement(
        "cover_image", is_acceptable_cover(offering.cover_image_url),
        "Choose a cover image, or pick one of ours.",
    ))

    # Current bundle = not superseded. The same predicate member download
    # authorisation uses, so the creator is judged against what a
    # purchaser would actually receive.
    current = (
        db.query(OfferingFile)
        .filter(
            OfferingFile.offering_id == offering.id,
            OfferingFile.superseded_at.is_(None),
        )
        .all()
    )
    reqs.append(Requirement(
        "has_files", len(current) > 0,
        "Add at least one file for members to download.",
    ))

    # Every current file must have passed. Not "most", and not "the ones
    # that finished" — an Offering published with a pending file would
    # show a member a product whose download refuses them.
    unpassed = [
        f for f in current if f.validation_status != FVS.passed.value
    ]
    reqs.append(Requirement(
        "files_validated",
        len(current) > 0 and not unpassed,
        _files_message(current, unpassed),
    ))

    priced_ok, pricing_msg = _check_pricing(offering)
    reqs.append(Requirement("pricing", priced_ok, pricing_msg))

    # Plan eligibility for the chosen pricing model. Free is always
    # allowed; paid needs the commercial capability.
    plan_ok = True
    plan_msg = ""
    if offering.pricing_kind == OfferingPricingKind.one_time.value:
        if not is_platform_owner(owner):
            plan = resolve_creator_plan(owner, db)
            plan_ok = bool(plan and plan.paid_offers_enabled)
            if not plan_ok:
                name = plan.display_name if plan else "current"
                plan_msg = (
                    f"Your {name} plan doesn't include paid Offerings. "
                    "Make this one free, or upgrade to Creator."
                )
    reqs.append(Requirement("plan_allows_pricing", plan_ok, plan_msg))

    # ── Within the plan's file allowance (Phase B5) ────────────────────
    #
    # Publishing is a new action, so it is held to the *current* plan —
    # the same treatment uploading gets. A creator who downgrades keeps
    # every Offering and every file they have (nothing is deleted and no
    # purchaser loses a download), and is simply refused the next new
    # thing until they are back inside the allowance. Publishing an
    # over-allowance Offering would be exactly that next new thing.
    #
    # Already-published Offerings are untouched by this: ``evaluate`` is
    # only consulted when a creator asks to publish, never on a schedule,
    # so nothing here can retroactively unpublish anything.
    from app.services.offering_limits import bundle_usage, resolve_offering_limits

    limits = resolve_offering_limits(owner, db)
    usage = bundle_usage(db, offering=offering)
    within = not usage.over(limits)
    reqs.append(Requirement(
        "within_plan_limits",
        within,
        "" if within else (
            f"This Offering uses {usage.resources} file"
            f"{'s' if usage.resources != 1 else ''} and "
            f"{usage.bytes_used // (1024 * 1024)} MB. Your "
            f"{limits.plan_name} plan allows {limits.max_files} and "
            f"{limits.bundle_mb} MB. Remove something, or upgrade."
        ),
    ))

    return Readiness(ready=all(r.met for r in reqs), requirements=reqs)


def _files_message(current: list, unpassed: list) -> str:
    if not current:
        return "Add at least one file for members to download."
    n = len(unpassed)
    if n == 0:
        return ""
    # Deliberately does not say "scanned" or "safe" — these files have
    # had structural checks, not a malware scan.
    return (
        f"{n} file{'s' if n != 1 else ''} still "
        f"{'need' if n != 1 else 'needs'} checking, or couldn't be "
        "accepted. Open the Files tab to see which."
    )


def _check_pricing(offering: Offering) -> tuple[bool, str]:
    kind = offering.pricing_kind
    if kind is None:
        return False, "Choose whether this Offering is free or paid."
    if kind == OfferingPricingKind.free.value:
        # The CHECK constraint already forbids a positive price on a free
        # Offering; this is the readable half of the same rule.
        if offering.price_cents:
            return False, "A free Offering can't have a price."
        return True, ""
    if kind == OfferingPricingKind.one_time.value:
        if not offering.price_cents or offering.price_cents <= 0:
            return False, "Set a price for this Offering."
        return True, ""
    return False, "Choose whether this Offering is free or paid."


__all__ = [
    "Requirement",
    "Readiness",
    "evaluate",
    "is_acceptable_cover",
]
