"""Which Collectives and which people a figure is about.

Reporting class answers "what kind of activity is this" and the ledger
answers "did money move". Keeping those apart is the whole point of
``classification.py``; this module is what lets a *chart* ask the first
question without ever changing the answer to the second.

Two dimensions, not one
-----------------------
A Collective has a reporting class and so does an account, and they are
independent. A test account may hold a membership in a genuine
production Collective — which is exactly the case that would otherwise
inflate production member growth with people who are not members at
all. So a population narrows on both columns, and a metric says which
of the two it honours rather than quietly honouring neither.

What "production" means here
----------------------------
Asymmetric, deliberately, because the two columns are populated
differently and the asymmetry is the honest reading of that:

* A **Collective** must be classified ``production``. ``classification``
  refuses to fold an unclassified Collective into production and this
  does not overrule it — an unclassified Collective is excluded, and the
  figure says so.
* An **account** counts unless it is explicitly ``test`` or
  ``demonstration``. Requiring a positive ``production`` class on
  accounts would drop every ordinary member who has never been
  classified, which is most of them, and would understate genuine
  membership by far more than the test accounts overstate it.

The provisional half of that is reported rather than buried: a
production figure carries how many of the accounts it counted were
unclassified, so "we are including these provisionally" stays visible at
the point the number is read.

Money is never filtered away
----------------------------
A demonstration Collective's live Stripe charge is a real financial
movement. Narrowing to production shows a *subset* of the ledger and is
labelled as one; it never becomes the ledger. The Money page therefore
defaults to ``all`` while Growth defaults to ``production`` — the
default belongs to the question being asked, not to the filter.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

from sqlalchemy import select

from app.models.platform import Space
from app.models.user import User
from app.reporting.classification import (
    ALL_CLASSES,
    DEMONSTRATION,
    PRODUCTION,
    TEST,
    UNCLASSIFIED,
    humanise,
)

#: The dimension name a metric declares to say it honours a population
#: filter. A metric without it is refused a narrowed population rather
#: than silently returning an unfiltered number under a filtered label.
DIMENSION = "reporting_class"

#: Account classes that never count as a real person in a business
#: figure. Narrower than "not production" on purpose — see the module
#: docstring on why unclassified accounts are included.
EXCLUDED_ACCOUNT_CLASSES: tuple[str, ...] = (TEST, DEMONSTRATION)


class PopulationView(str, enum.Enum):
    """The named populations a chart may ask for."""

    #: Everything. The complete ledger and the complete membership roll.
    all = "all"
    #: Genuine trade: production Collectives, excluding known test and
    #: demonstration accounts.
    production = "production"
    #: One class of Collective, for inspection. Accounts are not
    #: narrowed — the question is what happened in these Collectives.
    internal_operations = "internal_operations"
    demonstration = "demonstration"
    test = "test"
    #: Collectives an operator has not classified yet. Reported as its
    #: own population so the size of the unreviewed remainder is
    #: visible rather than inferred.
    unclassified = "unclassified"


VALID_VIEWS: tuple[str, ...] = tuple(v.value for v in PopulationView)


@dataclass(frozen=True)
class Population:
    """A population filter, plus the prose that must travel with it."""

    view: PopulationView = PopulationView.all

    @classmethod
    def parse(cls, value: str | None) -> Population:
        if value is None or value == "":
            return cls(PopulationView.all)
        try:
            return cls(PopulationView(value))
        except ValueError:
            raise UnknownPopulation(value) from None

    @property
    def is_all(self) -> bool:
        return self.view is PopulationView.all

    @property
    def label(self) -> str:
        if self.view is PopulationView.all:
            return "All activity"
        if self.view is PopulationView.production:
            return "Production"
        if self.view is PopulationView.unclassified:
            return "Unclassified"
        return humanise(self.view.value)

    @property
    def narrows_accounts(self) -> bool:
        """Whether this view excludes any account by its class."""
        return self.view is PopulationView.production

    @property
    def note(self) -> str:
        """Exactly what was included and excluded, for display."""
        if self.view is PopulationView.all:
            return (
                "Every Collective and every account, whatever its reporting "
                "class. For money this is the complete ledger — real Stripe "
                "movements from test and demonstration activity included."
            )
        if self.view is PopulationView.production:
            return (
                "Collectives classified production only, excluding accounts "
                "classified test or demonstration. Unclassified Collectives "
                "are excluded; unclassified accounts are counted "
                "provisionally and reported alongside. A subset of the "
                "ledger, not the ledger."
            )
        if self.view is PopulationView.unclassified:
            return (
                "Collectives an operator has not yet classified. Shown as "
                "its own population rather than folded into production."
            )
        return (
            f"Collectives classified {humanise(self.view.value).lower()}. "
            "Accounts are not narrowed — the question is what happened in "
            "these Collectives. Any real money here stays in the complete "
            "ledger view."
        )

    # -- SQL -------------------------------------------------------------
    #
    # Returned as SELECT statements for ``IN``/``NOT IN`` rather than as
    # joins, so a caller composes them into a query it already owns
    # without this module needing to know the shape of that query. A
    # metric over memberships and a metric over payments use the same
    # two selects against different foreign keys.

    def space_id_select(self):
        """Space ids in this population, or ``None`` for no restriction."""
        if self.view is PopulationView.all:
            return None
        if self.view is PopulationView.unclassified:
            return select(Space.id).where(Space.reporting_class.is_(None))
        if self.view is PopulationView.production:
            return select(Space.id).where(Space.reporting_class == PRODUCTION)
        return select(Space.id).where(Space.reporting_class == self.view.value)

    def excluded_account_select(self):
        """Accounts this population refuses to count, or ``None``.

        A ``NOT IN`` against a small, explicitly-classified set. Phrasing
        it as an exclusion rather than an inclusion is what keeps an
        unclassified account in the figure.
        """
        if not self.narrows_accounts:
            return None
        return select(User.id).where(
            User.reporting_class.in_(EXCLUDED_ACCOUNT_CLASSES)
        )

    def qualifiers(self) -> dict:
        """What travels beside every value computed under this filter."""
        return {
            "population": self.view.value,
            "population_label": self.label,
            "population_note": self.note,
        }


#: The unfiltered default, so callers that do not care need not say so.
ALL = Population(PopulationView.all)


class UnknownPopulation(KeyError):
    """No population is declared under that name."""


def unclassified_account_count(db, user_ids_select) -> int:
    """How many of the accounts in a figure have no reporting class.

    The provisional half of the production rule, counted rather than
    assumed. ``user_ids_select`` is a SELECT of the account ids the
    metric actually counted.
    """
    from sqlalchemy import func

    return int(
        db.execute(
            select(func.count())
            .select_from(User)
            .where(
                User.id.in_(user_ids_select),
                User.reporting_class.is_(None),
            )
        ).scalar()
        or 0
    )


def view_options() -> list[dict]:
    """The populations a control may offer, with their prose.

    Built from the enum and the shared vocabulary so a class added to
    ``classification`` appears here without a second list to update.
    """
    out = [
        {"key": PopulationView.all.value, "label": "All activity"},
        {"key": PopulationView.production.value, "label": "Production"},
    ]
    for name in ALL_CLASSES:
        if name == PRODUCTION:
            continue
        out.append({"key": name, "label": humanise(name)})
    out.append({"key": PopulationView.unclassified.value, "label": "Unclassified"})
    for option in out:
        option["note"] = Population.parse(option["key"]).note
    return out


__all__ = [
    "ALL",
    "DIMENSION",
    "EXCLUDED_ACCOUNT_CLASSES",
    "Population",
    "PopulationView",
    "UNCLASSIFIED",
    "UnknownPopulation",
    "unclassified_account_count",
    "view_options",
    "VALID_VIEWS",
]
