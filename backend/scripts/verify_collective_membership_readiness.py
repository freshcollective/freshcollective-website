"""Is production ready for Collective membership payments? Read-only.

Answers the questions Stage 5A.4 could not answer from outside: which
migration the database is actually on, whether migration 190's columns
and widened constraint are really there, and what the current
Collective pricing inventory looks like.

Safe by construction
--------------------
* Every statement is a SELECT.
* The transaction is set ``READ ONLY`` before anything is read, so a
  stray write fails at the database rather than relying on this
  docstring being true. (Verified: PostgreSQL reports
  ``transaction_read_only = on`` and refuses DDL with
  ``ReadOnlySqlTransaction``.)
* Every read is wrapped in a SAVEPOINT, so a table this database does
  not have yet degrades to one "unavailable" line instead of aborting
  the transaction and crashing the report.
* No member names, emails or payment identifiers are read — rows are
  counted, never listed.
* It imports no application module that starts a background loop or
  touches Stripe. ``DATABASE_URL`` comes from the environment, which
  is where Render puts it.
* Connection failures print the error with any password redacted, so
  a copied-out shell transcript cannot leak the database credential.

Running it
----------
From the fc-api Render Shell::

    python scripts/verify_collective_membership_readiness.py

Exit code is 0 when migration 190 is present, 1 when it is not, and 2
when the database could not be read at all, so it can be read at a
glance or used in a check.
"""

import os
import re
import sys

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

EXPECTED_REVISION = "190"
EXPECTED_COLUMNS = ("payment_method_setup_session_id", "payment_method_updated_at")
EXPECTED_INTERVALS = ("month", "year", "one_time")


def _redact(message: str) -> str:
    """A connection error with the password taken out of it.

    SQLAlchemy usually masks credentials itself, but "usually" is not
    a guarantee worth making about a production database URL that
    someone may paste into a chat window.
    """
    return re.sub(r"://([^:/@\s]+):[^@\s]*@", r"://\1:***@", message)


def _at_least(revision, expected: str) -> bool:
    """Is the database on this migration or a later one?

    Compared as numbers, not as text. The revision ids here are
    zero-padded three-digit strings ("189", "190") with one historical
    exception, ``000_pre_alembic_baseline``, so a string compare is
    right today and stops being right at revision 1000 — where
    ``"1000" >= "190"`` is False and a perfectly ready database would
    be reported as not ready.
    """
    if revision is None:
        return False
    if revision.isdigit() and expected.isdigit():
        return int(revision) >= int(expected)
    return revision == expected


def main() -> int:
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL is not set — run this inside the fc-api shell")
        return 2

    try:
        engine = create_engine(url)
        connection = engine.connect()
    except SQLAlchemyError as exc:
        print(f"Could not connect: {type(exc).__name__}")
        print(_redact(str(exc).splitlines()[0] if str(exc) else ""))
        return 2

    ok = True
    with connection as conn:
        conn.execute(text("SET TRANSACTION READ ONLY"))

        def scalar(sql, **params):
            """One value, or ``None`` if that read could not run.

            The SAVEPOINT is the point: in PostgreSQL a single failed
            statement aborts the entire transaction, and the tables
            read below are exactly the ones a not-yet-migrated
            database is missing. Without this the script would die
            halfway through describing the problem it was sent to
            find.
            """
            savepoint = conn.begin_nested()
            try:
                value = conn.execute(text(sql), params).scalar()
                savepoint.commit()
                return value
            except SQLAlchemyError:
                savepoint.rollback()
                return None

        def rows(sql, **params):
            """Every row, or an empty list if that read could not run."""
            savepoint = conn.begin_nested()
            try:
                result = conn.execute(text(sql), params).all()
                savepoint.commit()
                return result
            except SQLAlchemyError:
                savepoint.rollback()
                return []

        print("=" * 58)
        print(" Collective membership — production readiness")
        print("=" * 58)

        # ── 1-2. Migration state ────────────────────────────────────
        revision = scalar("SELECT version_num FROM alembic_version")
        applied = _at_least(revision, EXPECTED_REVISION)
        print(f"\nAlembic revision          : {revision or 'unavailable'}")
        print(f"Migration {EXPECTED_REVISION} applied         : "
              f"{'YES' if applied else 'NO'}")
        ok = ok and applied

        # ── 3. Migration 190's columns ──────────────────────────────
        found = {
            row[0] for row in rows(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'collective_memberships' "
                "AND column_name = ANY(:names)",
                names=list(EXPECTED_COLUMNS),
            )
        }
        print("\nMigration 190 columns:")
        for name in EXPECTED_COLUMNS:
            present = name in found
            ok = ok and present
            print(f"  {'present' if present else 'MISSING'}  {name}")

        # ── 4. The widened interval constraint ──────────────────────
        definition = scalar(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conname = 'ck_collective_memberships_interval'"
        ) or ""
        widened = all(value in definition for value in EXPECTED_INTERVALS)
        ok = ok and widened
        print(f"\nBilling-interval CHECK    : "
              f"{'widened for one_time' if widened else 'NOT widened'}")
        if definition:
            print(f"  {definition}")

        # ── 5-7. Collective pricing inventory ───────────────────────
        total = scalar("SELECT count(*) FROM spaces")
        print(f"\nCollectives               : "
              f"{total if total is not None else 'unavailable'}")
        print("By pricing type:")
        for pricing_type, count in rows(
            "SELECT coalesce(pricing_type, '(null)') AS pricing_type, "
            "count(*) AS n FROM spaces GROUP BY 1 ORDER BY 2 DESC, 1"
        ):
            print(f"  {count:>4}  {pricing_type}")
        non_free = scalar(
            "SELECT count(*) FROM spaces "
            "WHERE pricing_type IS NOT NULL AND pricing_type <> 'free'"
        )
        print(f"Non-free Collectives      : "
              f"{non_free if non_free is not None else 'unavailable'}")

        # A transition date on a Collective nobody can pay is the one
        # combination that would pause members with nothing to buy.
        # Both the settings route and the sweep refuse it; this is the
        # read-only check that none predates those guards.
        stranded = scalar(
            "SELECT count(*) FROM spaces "
            "WHERE paid_membership_effective_at IS NOT NULL "
            "AND (pricing_type IS NULL OR pricing_type NOT IN "
            "('paid_monthly','paid_annual','paid_one_time'))"
        )
        if stranded is None:
            print("Unpayable transition dates: unavailable "
                  "(column not present on this database)")
        else:
            print(f"Unpayable transition dates: {stranded}"
                  f"{'  <-- investigate' if stranded else ''}")
            ok = ok and not stranded

        # ── 8-9. Agreements ─────────────────────────────────────────
        agreements = scalar("SELECT count(*) FROM collective_memberships")
        if agreements is None:
            print("\nMembership agreements     : unavailable "
                  "(table not present on this database)")
        else:
            print(f"\nMembership agreements     : {agreements}")
            for status, count in rows(
                "SELECT status, count(*) FROM collective_memberships "
                "GROUP BY 1 ORDER BY 2 DESC"
            ):
                print(f"  {count:>4}  {status}")
            live = scalar(
                "SELECT count(*) FROM collective_memberships "
                "WHERE status IN ('active','past_due','cancel_scheduled')"
            )
            print(f"Live paid agreements      : "
                  f"{live if live is not None else 'unavailable'}")

        print("\n" + "-" * 58)
        print("READY — migration 190 is applied" if ok
              else "NOT READY — see the lines marked above")
        print("-" * 58)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
