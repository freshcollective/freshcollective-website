"""Who currently participates in Ways to Connect, and who ever chose to.

Written for one decision: the feature launched default-on, and we want
it to be opt-in. That means deciding what to do with the accounts whose
``users.ways_to_connect_enabled`` is already ``true``.

**The short answer this script exists to make concrete: a ``true`` value
cannot be read as consent.** The column is NOT NULL and was added with
``server_default=true`` (migration 138), deliberately without a
"hasn't decided" third state, so every account that existed then — and
every account created since — arrived at ``true`` without being asked.
There is no audit row, no settings-change event, and no consent record
for this field anywhere in the schema.

``users.updated_at`` cannot stand in for one either. It is
``onupdate=func.now()`` on the whole row, so it moves when a name,
bio, suspension, email verification or password changes. A member who
edited their bio looks identical to one who touched this toggle. The
script reports it anyway, as a strict **upper bound** on how many
accounts could conceivably have been near a deliberate choice — it is a
ceiling, never a count of consents.

The one value that *is* trustworthy is ``false``. Nothing in the
codebase writes ``false`` except the member's own PATCH of
``/api/auth/profile``, so every ``false`` is a deliberate opt-out and
must be preserved by any reset.

**Read-only. This script has no ``--apply`` and writes nothing.** The
reset it informs is a separate, approved step.

Usage:

    cd backend
    .venv/bin/python scripts/ways_to_connect_participation_audit.py

Runtime config (least-privilege, matches the reconcilers):

  * ``FC_SERVICE_ROLE=job``  — skips web-only Settings validators.
  * ``DATABASE_URL``         — same DB as fc-api.

Exit codes:
    0  ran successfully
    1  unexpected error
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("FC_SERVICE_ROLE", "job")

from sqlalchemy import func, select  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.models.user import User  # noqa: E402

log = logging.getLogger("wtc_participation_audit")


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(message)s", stream=sys.stdout,
    )
    db = SessionLocal()
    try:
        total = db.scalar(select(func.count()).select_from(User)) or 0

        def count(*where) -> int:
            return db.scalar(
                select(func.count()).select_from(User).where(*where)
            ) or 0

        opted_in = count(User.ways_to_connect_enabled.is_(True))
        opted_out = count(User.ways_to_connect_enabled.is_(False))

        # Ordinary members are what a reset would touch. Platform Owner
        # and admin accounts are listed separately: owner access is a QA
        # concern and admin status is not consent either, so they are
        # reported rather than quietly swept in or quietly exempted.
        admins_in = count(
            User.ways_to_connect_enabled.is_(True), User.role == "admin",
        )
        creators_in = count(
            User.ways_to_connect_enabled.is_(True), User.role == "creator",
        )
        members_in = count(
            User.ways_to_connect_enabled.is_(True), User.role == "user",
        )

        # Strict ceiling, not a count. See the module docstring.
        touched_ceiling = count(
            User.ways_to_connect_enabled.is_(True),
            User.updated_at > User.created_at,
        )

        log.info("Ways to Connect — participation audit (read-only)")
        log.info("=" * 56)
        log.info("total accounts                     %6d", total)
        log.info("")
        log.info("ways_to_connect_enabled = true     %6d", opted_in)
        log.info("  of which role='user'             %6d", members_in)
        log.info("  of which role='creator'          %6d", creators_in)
        log.info("  of which role='admin'            %6d", admins_in)
        log.info("ways_to_connect_enabled = false    %6d", opted_out)
        log.info("")
        log.info("DELIBERATE CHOICES IDENTIFIABLE")
        log.info("  deliberate opt-outs (false)      %6d", opted_out)
        log.info("    Trustworthy: nothing writes false except the")
        log.info("    member's own profile PATCH. Preserve these.")
        log.info("  deliberate opt-ins               %6s", "none")
        log.info("    Not distinguishable. No audit row, no settings")
        log.info("    event, no consent record for this field, and the")
        log.info("    column has no 'hasn't decided' state.")
        log.info("")
        log.info("  upper bound on accounts whose row was")
        log.info("  ever updated at all (CEILING, not a")
        log.info("  count of consents)               %6d", touched_ceiling)
        log.info("    users.updated_at is onupdate on the whole row, so")
        log.info("    a bio edit or a verification moves it too.")
        log.info("")
        log.info("A RESET WOULD AFFECT")
        log.info("  accounts moving true -> false    %6d", opted_in)
        log.info("  accounts left untouched (already")
        log.info("  false, a deliberate opt-out)     %6d", opted_out)
        log.info("")
        log.info("Nothing was written. This script has no --apply.")
        return 0
    except Exception:
        log.exception("participation audit failed")
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
