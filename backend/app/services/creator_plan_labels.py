"""Creator-facing plan labels.

``CreatorPlan.name`` and ``plan_config.PlanCapability.display_name`` are
**internal** names. For the ``pro`` tier both currently read ``"Pro"``,
which is an internal shorthand that must never appear in creator-facing
email copy — the creator-facing label for that tier is
**Creator Portfolio**.

This module is the single place that translation happens. Every
creator-facing email renders its plan label through
:func:`creator_facing_plan_label` rather than reading ``plan.name``
directly, so a plan row seeded (or re-seeded) with an internal name
cannot leak it into an inbox.

Deliberately a presentation-layer mapping, not a data migration: the
plan rows are commercial records referenced by Stripe metadata,
capability checks and admin surfaces, and renaming them is a product
decision with a much wider blast radius than email copy.
"""

from __future__ import annotations


# Internal slug → creator-facing label. Slug is the stable key; the
# name-based map below is a second net for payloads that carry only a
# display name.
_LABEL_BY_SLUG: dict[str, str] = {
    "pro": "Creator Portfolio",
}

# Internal display name → creator-facing label, matched case-insensitively.
_LABEL_BY_NAME: dict[str, str] = {
    "pro": "Creator Portfolio",
}

# Used when neither a slug nor a name resolves to anything usable.
# "Creator" is the base tier and the safest neutral noun for copy of
# the form "your Fresh Collective {label} plan".
FALLBACK_LABEL = "Creator"


def creator_facing_plan_label(
    *,
    slug: str | None = None,
    name: str | None = None,
) -> str:
    """Return the label to show a creator for this plan.

    Resolution order: explicit slug mapping, then name mapping, then the
    supplied name as-is, then :data:`FALLBACK_LABEL`. Whitespace is
    trimmed; empty strings are treated as absent.
    """
    clean_slug = (slug or "").strip().lower()
    if clean_slug and clean_slug in _LABEL_BY_SLUG:
        return _LABEL_BY_SLUG[clean_slug]

    clean_name = (name or "").strip()
    if clean_name and clean_name.lower() in _LABEL_BY_NAME:
        return _LABEL_BY_NAME[clean_name.lower()]

    return clean_name or FALLBACK_LABEL


__all__ = ["FALLBACK_LABEL", "creator_facing_plan_label"]
