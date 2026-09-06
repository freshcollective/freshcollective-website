#!/usr/bin/env python
"""One-shot maintenance script — grant prod Lindsey explicit Creator
Studio management access to the platform-owned World Builders Space.

Background: the World Builders selective importer deliberately did
not create a SpaceMembership for Lindsey, on the assumption that the
``auto_grant_role='creator'`` contract would produce one. That
assumption was wrong on two counts:

  1. The auto-grant reconciler creates a ``SpaceRole.learner``
     membership (member-side access), not creator/moderator. The
     Creator-Studio endpoint /api/creator/spaces only lists Spaces
     where the user is the owner OR holds an active creator/moderator
     membership.
  2. Prod Lindsey's role is ``admin``, not ``creator``, so the
     reconciler's ``Space.auto_grant_role == user.role`` filter
     never matches — no row is created for her at all.

This script fixes the gap by inserting exactly ONE
``SpaceMembership(role=creator, status=active, source='migration')``
row for (prod-Lindsey, prod-World-Builders). Nothing else is
touched — creator_id stays NULL (platform-owned contract), the
auto-grant contract for future creators is unchanged, and no
pathway/media/R2 content is modified.

Immune to the auto-grant reconciler: the reconciler only touches
rows with ``source='auto_role'`` (creator_eligibility.py:22-23,
208-216). A ``source='migration'`` row is invisible to it.

Usage — dry-run:
    .venv/bin/python -m scripts.grant_wb_creator_membership

Usage — commit:
    .venv/bin/python -m scripts.grant_wb_creator_membership --commit

Required env vars (for --commit):
    DATABASE_URL           local dev DB (already in backend/.env)
    PROD_DATABASE_URL      prod DB (Render fc-db External Connection
                           String — NEVER commit to .env)
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

try:
    from dotenv import load_dotenv
    load_dotenv(BACKEND_DIR / ".env")
except ImportError:
    pass

import app.main  # noqa: F401,E402

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

from app.models.platform import (  # noqa: E402
    Space,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)
from app.models.user import User  # noqa: E402


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TARGET_SPACE_SLUG = "world-builders"
TARGET_USER_EMAIL = "lindsey@hilliard.net.au"

# What the platform contract on World Builders must look like for
# this script to run. Any deviation → refuse rather than guess.
EXPECTED_CREATOR_ID = None            # platform-owned
EXPECTED_AUTO_GRANT_ROLE = "creator"

# The exact shape of the row we will insert.
NEW_MEMBERSHIP_ROLE = SpaceRole.creator
NEW_MEMBERSHIP_STATUS = SpaceMembershipStatus.active
NEW_MEMBERSHIP_SOURCE = "migration"

log = logging.getLogger("grant_wb_creator_membership")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class MaintenanceContext:
    local_session: Session
    prod_session: Session
    prod_user_id: str
    prod_space_id: str
    commit: bool
    yes_i_am_sure: bool


# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------


class PreflightError(RuntimeError):
    """A preflight check failed — script must not proceed to writes."""


def preflight(args: argparse.Namespace) -> MaintenanceContext:
    """Validate both DBs are distinct + expected, resolve prod Lindsey
    by email, resolve prod World Builders by slug, assert its platform
    contract, and refuse if the target membership already exists."""
    local_url = os.environ.get("DATABASE_URL")
    if not local_url:
        raise PreflightError("DATABASE_URL is not set (need local dev DB).")
    prod_url = os.environ.get("PROD_DATABASE_URL")
    if not prod_url:
        raise PreflightError(
            "PROD_DATABASE_URL is not set — export it from the Render "
            "fc-db External Connection String for this shell only."
        )
    if _same_db(local_url, prod_url):
        raise PreflightError(
            "DATABASE_URL and PROD_DATABASE_URL resolve to the same "
            "host+database. Refusing to run."
        )

    log.info("Connecting to local DB %s", _sanitised_url(local_url))
    local_engine = create_engine(local_url, future=True)
    local_session = sessionmaker(bind=local_engine, future=True)()
    local_session.execute(select(1)).scalar_one()

    log.info("Connecting to prod DB %s", _sanitised_url(prod_url))
    prod_engine = create_engine(prod_url, future=True)
    prod_session = sessionmaker(bind=prod_engine, future=True)()
    prod_session.execute(select(1)).scalar_one()

    prod_user_id, prod_space_id = _resolve_and_check(prod_session)
    _refuse_if_membership_exists(prod_session, prod_user_id, prod_space_id)

    return MaintenanceContext(
        local_session=local_session,
        prod_session=prod_session,
        prod_user_id=prod_user_id,
        prod_space_id=prod_space_id,
        commit=args.commit,
        yes_i_am_sure=args.yes_i_am_sure,
    )


def _resolve_and_check(prod_session: Session) -> tuple[str, str]:
    """Look up prod Lindsey (by email) and prod World Builders (by
    slug). Refuse if either is missing, or if the platform contract
    on World Builders has drifted from the expected shape."""
    user = prod_session.query(User).filter(
        User.email == TARGET_USER_EMAIL
    ).first()
    if user is None:
        raise PreflightError(
            f"Prod user with email {TARGET_USER_EMAIL!r} not found."
        )

    space = prod_session.query(Space).filter(
        Space.slug == TARGET_SPACE_SLUG
    ).first()
    if space is None:
        raise PreflightError(
            f"Prod Space with slug {TARGET_SPACE_SLUG!r} not found. "
            "This maintenance script only runs against the seeded "
            "platform-owned World Builders."
        )

    if space.creator_id != EXPECTED_CREATOR_ID:
        raise PreflightError(
            f"Prod Space {TARGET_SPACE_SLUG!r} has "
            f"creator_id={space.creator_id!r}, expected "
            f"{EXPECTED_CREATOR_ID!r} (platform-owned). Refusing — "
            "this script assumes the platform contract."
        )
    if space.auto_grant_role != EXPECTED_AUTO_GRANT_ROLE:
        raise PreflightError(
            f"Prod Space {TARGET_SPACE_SLUG!r} has "
            f"auto_grant_role={space.auto_grant_role!r}, expected "
            f"{EXPECTED_AUTO_GRANT_ROLE!r}. Refusing — this script "
            "assumes the platform contract."
        )

    return user.id, space.id


def _refuse_if_membership_exists(
    prod_session: Session, user_id: str, space_id: str,
) -> None:
    """A (user_id, space_id) UNIQUE constraint exists on
    space_memberships. Refuse loudly if a row is already present —
    this script does not modify or replace existing memberships."""
    existing = prod_session.query(SpaceMembership).filter(
        SpaceMembership.user_id == user_id,
        SpaceMembership.space_id == space_id,
    ).first()
    if existing is not None:
        raise PreflightError(
            f"A SpaceMembership already exists for prod Lindsey on "
            f"World Builders (id={existing.id}, role={existing.role!r}, "
            f"status={existing.status!r}, source={existing.source!r}). "
            "This script is insert-only and does not modify existing "
            "rows — investigate before retrying."
        )


def _same_db(url_a: str, url_b: str) -> bool:
    a = urlparse(url_a); b = urlparse(url_b)
    return (a.hostname, a.port, a.path) == (b.hostname, b.port, b.path)


def _sanitised_url(url: str) -> str:
    p = urlparse(url)
    host = p.hostname or "?"
    port = f":{p.port}" if p.port else ""
    return f"{p.scheme}://{p.username or '?'}@{host}{port}{p.path}"


# ---------------------------------------------------------------------------
# Summary / confirmation
# ---------------------------------------------------------------------------


def print_summary(ctx: MaintenanceContext) -> None:
    mode = "COMMIT" if ctx.commit else "DRY RUN — no writes will occur"
    print("=" * 74)
    print(f"World Builders creator-membership grant — {mode}")
    print("=" * 74)
    print(f"  Prod user (Lindsey):     id={ctx.prod_user_id}")
    print(f"    email:                 {TARGET_USER_EMAIL}")
    print(f"  Prod Space (World Builders): id={ctx.prod_space_id}")
    print(f"    slug:                  {TARGET_SPACE_SLUG!r}")
    print(f"    creator_id (expected): {EXPECTED_CREATOR_ID!r}  "
          "→ platform-owned, will remain NULL")
    print(f"    auto_grant_role (expected): {EXPECTED_AUTO_GRANT_ROLE!r}  "
          "→ platform contract, will remain 'creator'")
    print()
    print("Would INSERT (single transaction):")
    print(f"  SpaceMembership          1 row")
    print(f"    user_id:               {ctx.prod_user_id}")
    print(f"    space_id:              {ctx.prod_space_id}")
    print(f"    role:                  {NEW_MEMBERSHIP_ROLE.value!r}")
    print(f"    status:                {NEW_MEMBERSHIP_STATUS.value!r}")
    print(f"    source:                {NEW_MEMBERSHIP_SOURCE!r}  "
          "(explicitly NOT 'auto_role' — invisible to the reconciler)")
    print()
    print("What is NOT touched:")
    print("  - Space.creator_id (stays NULL — platform-owned)")
    print("  - Space.auto_grant_role (stays 'creator')")
    print("  - Any World Builders pathway / step / block / about-block")
    print("  - Any CreatorMediaAsset, SpaceResource, or R2 object")
    print("  - Any other SpaceMembership row (auto_role or otherwise)")
    print()


def confirm_interactive() -> None:
    print("Type 'y' to commit to prod, anything else to abort: ",
          end="", flush=True)
    ans = sys.stdin.readline().strip().lower()
    if ans != "y":
        raise SystemExit("Aborted by operator.")


# ---------------------------------------------------------------------------
# Insert (single transaction) — no commit inside; caller wraps.
# ---------------------------------------------------------------------------


def insert_membership(
    prod_session: Session,
    prod_user_id: str,
    prod_space_id: str,
) -> str:
    """Insert the single membership row and return its new id.

    Refetches Space + checks the (user_id, space_id) UNIQUE key one
    more time immediately before insert — defends against any drift
    that snuck in between preflight and commit (concurrent admin
    activity, another run of this script, etc.)."""
    fresh_space = prod_session.query(Space).filter(
        Space.id == prod_space_id
    ).first()
    if fresh_space is None:
        raise RuntimeError(
            f"Prod Space id={prod_space_id!r} disappeared between "
            "preflight and insert."
        )
    if fresh_space.creator_id != EXPECTED_CREATOR_ID:
        raise RuntimeError(
            f"Drift: Space.creator_id={fresh_space.creator_id!r} at "
            f"insert time, expected {EXPECTED_CREATOR_ID!r}. Refusing."
        )
    if fresh_space.auto_grant_role != EXPECTED_AUTO_GRANT_ROLE:
        raise RuntimeError(
            f"Drift: Space.auto_grant_role={fresh_space.auto_grant_role!r} "
            f"at insert time, expected {EXPECTED_AUTO_GRANT_ROLE!r}. "
            "Refusing."
        )

    existing = prod_session.query(SpaceMembership).filter(
        SpaceMembership.user_id == prod_user_id,
        SpaceMembership.space_id == prod_space_id,
    ).first()
    if existing is not None:
        raise RuntimeError(
            f"Drift: a SpaceMembership was created between preflight "
            f"and insert (id={existing.id}). Refusing."
        )

    new_id = str(uuid4())
    prod_session.add(SpaceMembership(
        id=new_id,
        user_id=prod_user_id,
        space_id=prod_space_id,
        role=NEW_MEMBERSHIP_ROLE,
        status=NEW_MEMBERSHIP_STATUS,
        source=NEW_MEMBERSHIP_SOURCE,
    ))
    prod_session.flush()
    log.info("SpaceMembership inserted (id=%s)", new_id)
    return new_id


# ---------------------------------------------------------------------------
# Verification (post-commit)
# ---------------------------------------------------------------------------


def verify(ctx: MaintenanceContext, new_membership_id: str) -> None:
    """Prove every promised invariant on prod. Raises on any drift."""
    mems = ctx.prod_session.query(SpaceMembership).filter(
        SpaceMembership.user_id == ctx.prod_user_id,
        SpaceMembership.space_id == ctx.prod_space_id,
    ).all()
    if len(mems) != 1:
        raise RuntimeError(
            f"VERIFY: expected exactly 1 Lindsey/WB membership, "
            f"found {len(mems)}."
        )
    m = mems[0]
    if m.id != new_membership_id:
        raise RuntimeError(
            f"VERIFY: membership id={m.id!r} != freshly inserted "
            f"{new_membership_id!r}."
        )
    if m.role != NEW_MEMBERSHIP_ROLE:
        raise RuntimeError(
            f"VERIFY: role={m.role!r}, expected {NEW_MEMBERSHIP_ROLE!r}."
        )
    if m.status != NEW_MEMBERSHIP_STATUS:
        raise RuntimeError(
            f"VERIFY: status={m.status!r}, "
            f"expected {NEW_MEMBERSHIP_STATUS!r}."
        )
    if m.source != NEW_MEMBERSHIP_SOURCE:
        raise RuntimeError(
            f"VERIFY: source={m.source!r}, "
            f"expected {NEW_MEMBERSHIP_SOURCE!r}."
        )

    space = ctx.prod_session.query(Space).filter(
        Space.id == ctx.prod_space_id
    ).first()
    if space is None:
        raise RuntimeError("VERIFY: prod Space disappeared.")
    if space.creator_id != EXPECTED_CREATOR_ID:
        raise RuntimeError(
            f"VERIFY: Space.creator_id={space.creator_id!r}, "
            f"expected {EXPECTED_CREATOR_ID!r}. Platform-owned "
            "contract was disturbed."
        )
    if space.auto_grant_role != EXPECTED_AUTO_GRANT_ROLE:
        raise RuntimeError(
            f"VERIFY: Space.auto_grant_role={space.auto_grant_role!r}, "
            f"expected {EXPECTED_AUTO_GRANT_ROLE!r}. Auto-grant "
            "contract was disturbed."
        )

    log.info(
        "Verification: ✓ exactly one creator/active/'migration' "
        "membership; Space.creator_id remains NULL; "
        "auto_grant_role remains 'creator'."
    )


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Grant prod Lindsey explicit Creator-Studio access "
                    "to the platform-owned World Builders Space.",
    )
    p.add_argument("--commit", action="store_true",
                   help="Actually write to prod. Default is dry-run.")
    p.add_argument("--yes-i-am-sure", action="store_true",
                   help="Skip the interactive confirmation prompt.")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s  %(message)s",
    )
    args = parse_args(argv)

    try:
        ctx = preflight(args)
    except PreflightError as e:
        print(f"PREFLIGHT: {e}", file=sys.stderr)
        return 2

    print_summary(ctx)

    if not ctx.commit:
        print("Dry-run complete. Pass --commit to actually grant.")
        return 0

    if not ctx.yes_i_am_sure:
        confirm_interactive()

    try:
        new_id = insert_membership(
            ctx.prod_session, ctx.prod_user_id, ctx.prod_space_id,
        )
        ctx.prod_session.commit()
    except Exception as e:
        ctx.prod_session.rollback()
        print(f"\nWRITE FAILED: {e}", file=sys.stderr)
        print("Rollback complete. Prod DB unchanged.", file=sys.stderr)
        return 4

    try:
        verify(ctx, new_id)
    except Exception as e:
        print(f"\nVERIFY FAILED (commit already landed): {e}",
              file=sys.stderr)
        return 5

    print()
    print("=" * 74)
    print("GRANT COMPLETE — prod Lindsey now has creator/active "
          "membership on World Builders.")
    print("=" * 74)
    return 0


if __name__ == "__main__":
    sys.exit(main())
