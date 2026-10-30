"""Assign reporting classifications — plan first, apply only on request.

Classification is an operator's judgement, so this script never decides
anything. The intended mapping is written out below, taken verbatim from
the platform owner's own message, and the script's job is to show
exactly which rows it would touch and what each would become.

``--plan`` is the default and is read-only. ``--apply`` writes the
``reporting_class`` column and nothing else: no financial record, no
payout status, no Stripe call. Every live transaction stays exactly
where it is, including those belonging to test fixtures — a class says
how to read money, never whether to count it.

Safety
------
* ``--plan`` runs in a server-enforced read-only transaction.
* ``--apply`` refuses unless every row resolves to exactly one match, so
  a renamed or duplicated Collective stops the run instead of being
  guessed at.
* ``--apply`` refuses any value the database would not accept, naming
  the migration needed, rather than coercing it to a near-enough one.
* Accounts are matched only if named here. Nothing is inferred for any
  other user, and the founder account must be given by id — there is no
  heuristic for "probably the owner".
* No email address is read or printed.

Usage
-----
    python scripts/reporting/classify.py                      # plan
    python scripts/reporting/classify.py --founder <user_id>  # plan, incl. owner
    python scripts/reporting/classify.py --apply --founder <user_id>
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import text  # noqa: E402

import app.models.community_care  # noqa: E402,F401
from app.core.database import SessionLocal, engine  # noqa: E402
from app.reporting.classification import (  # noqa: E402
    DEMONSTRATION,
    INTERNAL_OPERATIONS,
    PRODUCTION,
    SUPPORTED_CLASSES,
    TEST,
    humanise,
    is_supported,
)

# ---------------------------------------------------------------------------
# The mapping, as given. Matched on the Collective's exact name — the
# only handle available without inventing one, and every match is shown
# for confirmation before anything is written.
# ---------------------------------------------------------------------------
COLLECTIVES: dict[str, str] = {
    "EMBODY": PRODUCTION,
    "Life in Full Colour": PRODUCTION,
    "Nourish Connect Thrive": PRODUCTION,          # Kelly Hamilton — external
    "Moonlit Circle": DEMONSTRATION,
    "World Builders": INTERNAL_OPERATIONS,
    "Beach Life": TEST,
    "Tom's Test Collective": TEST,
}

#: Only these accounts, and only by name. The founder's own account is
#: supplied by id at the command line instead, because "the admin who
#: isn't a test account" is an inference and this script does not make
#: any.
ACCOUNTS: dict[str, str] = {
    "Sophie Bennett": TEST,
    "Tom Test": TEST,
}


class Row:
    def __init__(self, table, ident, label, current, proposed, extra=""):
        self.table = table
        self.id = ident
        self.label = label
        self.current = current
        self.proposed = proposed
        self.extra = extra

    @property
    def change(self) -> str:
        if self.current == self.proposed:
            return "no change"
        if not is_supported(self.proposed):
            return "BLOCKED — value not in the schema"
        return f"{self.current or 'unclassified'} → {self.proposed}"

    @property
    def blocked(self) -> bool:
        return not is_supported(self.proposed)


def _lookup(conn, table: str, name_column: str, name: str, extra_columns: str):
    rows = conn.execute(
        text(
            f"SELECT id, {name_column} AS label, reporting_class{extra_columns} "
            f"FROM {table} WHERE {name_column} = :name"
        ),
        {"name": name},
    ).fetchall()
    return rows


def collect(conn, founder_id: str | None) -> tuple[list[Row], list[str]]:
    rows: list[Row] = []
    problems: list[str] = []

    for name, proposed in COLLECTIVES.items():
        found = _lookup(conn, "spaces", "name", name, ", slug, status")
        if len(found) != 1:
            problems.append(
                f"spaces: {name!r} matched {len(found)} rows — expected exactly 1"
            )
            continue
        r = found[0]
        rows.append(
            Row("spaces", r.id, name, r.reporting_class, proposed,
                f"slug={r.slug} status={r.status}")
        )

    for name, proposed in ACCOUNTS.items():
        found = _lookup(conn, "users", "name", name, ", role")
        if len(found) != 1:
            problems.append(
                f"users: {name!r} matched {len(found)} rows — expected exactly 1"
            )
            continue
        r = found[0]
        rows.append(
            Row("users", r.id, name, r.reporting_class, proposed, f"role={r.role}")
        )

    if founder_id:
        found = conn.execute(
            text(
                "SELECT id, name AS label, reporting_class, role "
                "FROM users WHERE id = :id"
            ),
            {"id": founder_id},
        ).fetchall()
        if len(found) != 1:
            problems.append(f"users: founder id {founder_id!r} not found")
        else:
            r = found[0]
            rows.append(
                Row("users", r.id, r.label or "(no name)", r.reporting_class,
                    PRODUCTION, f"role={r.role} — founder account")
            )

    return rows, problems


def candidates(conn) -> None:
    """Admin accounts, so the founder id can be supplied rather than guessed."""
    print("\n  Admin-role accounts (pass the right id as --founder):")
    for r in conn.execute(
        text(
            "SELECT id, name, reporting_class FROM users "
            "WHERE role = 'admin' ORDER BY name"
        )
    ):
        current = r.reporting_class or "unclassified"
        print(f"    {r.id}  {(r.name or '(no name)'):24}  {current}")


def render(rows: list[Row]) -> None:
    if not rows:
        print("  (nothing matched)")
        return
    width = max(len(r.label) for r in rows)
    for table in ("spaces", "users"):
        group = [r for r in rows if r.table == table]
        if not group:
            continue
        print(f"\n  {table}:")
        for r in group:
            print(f"    {r.label.ljust(width)}  {r.change}")
            print(f"    {' ' * width}  id={r.id} {r.extra}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true",
        help="write the reporting_class column. Without it, nothing is written.",
    )
    parser.add_argument(
        "--founder", default=None,
        help="user id of the platform owner's own account, to classify as "
             "production. Omit to leave it alone.",
    )
    args = parser.parse_args()

    print("Reporting classification — plan" if not args.apply
          else "Reporting classification — APPLY")
    print(f"Schema currently accepts: {', '.join(SUPPORTED_CLASSES)}")

    with engine.connect() as conn:
        conn.execute(text("SET TRANSACTION READ ONLY"))
        rows, problems = collect(conn, args.founder)
        render(rows)
        if not args.founder:
            candidates(conn)
        conn.rollback()

    blocked = [r for r in rows if r.blocked]
    changes = [r for r in rows if not r.blocked and r.current != r.proposed]

    if problems:
        print("\n  Unresolved:")
        for p in problems:
            print(f"    - {p}")

    if blocked:
        print(
            f"\n  {len(blocked)} row(s) propose "
            f"{humanise(TEST)!r}, which the CHECK constraint from migration "
            "171 does not accept:"
        )
        for r in blocked:
            print(f"    - {r.table}: {r.label}")
        print(
            "    Widening the constraint needs a migration. Nothing is\n"
            "    coerced to a near-enough value — see the report."
        )

    print(f"\n  {len(changes)} row(s) would change, {len(blocked)} blocked.")

    if not args.apply:
        print("\nPlan only. Nothing was written.")
        return 0

    if problems or blocked:
        print(
            "\nRefusing to apply: resolve the items above first. A partial "
            "classification is worse than none, because the reporting "
            "cannot tell an unreviewed Collective from a blocked one."
        )
        return 2

    db = SessionLocal()
    try:
        for r in changes:
            db.execute(
                text(
                    f"UPDATE {r.table} SET reporting_class = :cls WHERE id = :id"
                ),
                {"cls": r.proposed, "id": r.id},
            )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    print(f"\nApplied to {len(changes)} row(s). No financial record was touched.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
