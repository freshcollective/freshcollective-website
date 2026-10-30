"""What kind of activity a Collective or an account represents.

Reporting classification answers a question the ledger cannot: whether a
real financial movement was production trade, an internal operation, a
demonstration, or a test. Every one of those can involve live Stripe
charges, so the money is never excluded on the strength of a class — the
class only says how to *read* it.

Assigned by an operator, never inferred
---------------------------------------
Nothing here looks at a Collective's name. A Collective called "Beach
Life" might be production and one called "Nourish Connect Thrive" might
be a fixture; only the person who runs the platform knows. So the column
stays NULL until it is set deliberately, and reporting counts NULL as
``unclassified`` rather than folding it into production — otherwise the
review would be pointless.

Why the vocabulary lives here
-----------------------------
It was declared twice: once in migration 171's CHECK constraint and once
as a literal tuple inside the outstanding-payouts breakdown. That is the
same shape of duplication that let the member transaction type set drift
and hid EMBODY from every revenue metric. One definition, imported.
"""

from __future__ import annotations

#: Genuine trade with members. Fresh Collective's real business.
PRODUCTION = "production"
#: Fresh Collective running itself — the World Builders governance
#: Collective, for instance. Real, but not trade.
INTERNAL_OPERATIONS = "internal_operations"
#: A Collective that exists to be shown to people. Its charges may be
#: real; its activity is not a customer relationship.
DEMONSTRATION = "demonstration"
#: A fixture. An account or Collective used to exercise the platform,
#: including through live Stripe keys. The money moved and stays in
#: every total; it is simply not somebody else's business.
TEST = "test"

#: The values the CHECK constraint on ``spaces.reporting_class`` and
#: ``users.reporting_class`` accepts. ``TEST`` was added by migration
#: 173 after classifying the real inventory showed three were not enough:
#: mapping a fixture onto ``internal_operations`` would have made the
#: World Builders governance Collective unreadable, and onto
#: ``demonstration`` would have done the same to Moonlit Circle.
SUPPORTED_CLASSES: tuple[str, ...] = (
    PRODUCTION,
    INTERNAL_OPERATIONS,
    DEMONSTRATION,
    TEST,
)

#: Every class the reporting knows about. Identical to
#: :data:`SUPPORTED_CLASSES` while the schema and the vocabulary agree —
#: kept as a separate name so a future class can be declared and
#: reported on before the migration that stores it, rather than a
#: breakdown silently dropping the category.
ALL_CLASSES: tuple[str, ...] = SUPPORTED_CLASSES

#: How an unset column is reported. Not a class — the absence of one.
UNCLASSIFIED = "unclassified"


def is_supported(value: str) -> bool:
    """Whether the database will currently accept this value."""
    return value in SUPPORTED_CLASSES


def humanise(value: str) -> str:
    """``internal_operations`` → ``Internal operations``."""
    words = value.replace("_", " ")
    return words[:1].upper() + words[1:]
