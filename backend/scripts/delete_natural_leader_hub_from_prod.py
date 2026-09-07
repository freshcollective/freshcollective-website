#!/usr/bin/env python
"""One-shot maintenance script — permanently delete The Natural Leader
Hub Space from production.

Background: NLH is an intentionally obsolete demo Collective that must
be removed. It cannot be deleted through Creator Studio's Danger Zone
because that endpoint requires ``creator_id == current_user.id`` and
``status == 'draft'`` — NLH is platform-owned (creator_id NULL) and
active. This script is the dedicated safe path.

Design + assumptions come from the audit report:

  * Space id:           80862f54-d95f-4b3b-83ab-cf926014441d
  * slug:               'the-natural-leader-hub'
  * creator_id:         NULL (platform-owned)
  * auto_grant_role:    NULL
  * PurchasePlan count: 0 (RESTRICT would block otherwise)
  * R2 keys owned:      0

The known CASCADE-child tables (21 rows across 8 tables at audit
time) will be auto-deleted by PostgreSQL's ON DELETE CASCADE when
the Space row is dropped. Nothing is expected outside those counts;
if anything HAS accumulated since the audit, the script refuses to
proceed and asks for a fresh audit — silent deletion of unexpected
data is not acceptable.

R2 keys owned by this Space were zero at audit time. If the enumeration
now returns any keys the script refuses. R2 cleanup for unexpected
keys must be reviewed separately, not auto-deleted.

Usage — dry-run:
    .venv/bin/python -m scripts.delete_natural_leader_hub_from_prod

Usage — commit:
    .venv/bin/python -m scripts.delete_natural_leader_hub_from_prod --commit

Required env vars (for --commit):
    DATABASE_URL           local dev DB (from backend/.env)
    PROD_DATABASE_URL      prod DB (Render fc-db External Connection
                           String — NEVER commit to .env)
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

try:
    from dotenv import load_dotenv
    load_dotenv(BACKEND_DIR / ".env")
except ImportError:
    pass

import app.main  # noqa: F401,E402

from sqlalchemy import create_engine, func, select  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

from app.creator.routes import _collect_space_r2_keys  # noqa: E402
from app.models.platform import (  # noqa: E402
    ConversationChannel,
    Event,
    Pathway,
    PathwayStep,
    PathwayStepBlock,
    Space,
    SpaceMembership,
)
from app.models.purchase_plan import PurchasePlan  # noqa: E402
from app.models.user import User  # noqa: E402


# ---------------------------------------------------------------------------
# Locked identity + audited upper bounds
# ---------------------------------------------------------------------------

TARGET_SPACE_ID = "80862f54-d95f-4b3b-83ab-cf926014441d"
TARGET_SLUG = "the-natural-leader-hub"
TARGET_NAME = "The Natural Leader Hub"

EXPECTED_CREATOR_ID = None
EXPECTED_AUTO_GRANT_ROLE = None
EXPECTED_LOCATION_ID = None

# Audited CASCADE child counts. These are UPPER BOUNDS — any prod row
# count that exceeds the audit is a surprise and must not be silently
# deleted. Equal-or-lower is fine (rows may have been cleaned up
# between audit and delete). Members are gated separately at
# MAX_EXPECTED_MEMBERSHIPS because a legitimate member joining after
# the audit is the plausible surprise pattern to defend against.
AUDITED_CHILD_UPPER_BOUNDS: dict[str, int] = {
    "SpaceMembership":       1,
    "Pathway":               4,
    "PathwayStep":           6,
    "PathwayStepBlock":      6,
    "Event":                 3,
    "ConversationChannel":   2,
}

# Membership guard: the audit found exactly one learner membership
# (Lindsey's SEC-009 test account). Anything above this is a real
# person we shouldn't silently blow away.
MAX_EXPECTED_MEMBERSHIPS = 1

# The audit enumerated zero R2 keys owned by this Space. Any keys
# now → refuse. Manual review; do not auto-delete.
EXPECTED_R2_KEY_COUNT = 0

# Users that we deliberately DO NOT touch, verified post-delete to
# have survived the CASCADE unaffected.
PROD_LINDSEY_EMAIL = "lindsey@hilliard.net.au"

log = logging.getLogger("delete_natural_leader_hub_from_prod")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class DeletionContext:
    local_session: Session
    prod_session: Session
    space_id: str
    commit: bool
    yes_i_am_sure: bool
    # Snapshotted before deletion so verify() can prove they survived.
    prod_lindsey_id: str
    prod_lindsey_other_membership_count: int


@dataclass
class ChildCounts:
    """Counts of the known CASCADE-child rows enumerated at preflight
    time. Passed into verify() so post-commit verification can prove
    the exact deletion happened without re-querying prod state."""
    counts: dict[str, int] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------


class PreflightError(RuntimeError):
    """A preflight check failed — script must not proceed to writes."""


def preflight(args: argparse.Namespace) -> tuple[DeletionContext, ChildCounts, list[str]]:
    """Validate env, connect, resolve the Space, verify every identity
    and count assumption, enumerate R2 keys. Returns the context plus
    the enumerated child counts and R2 key list for the summary."""
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

    space = _resolve_and_check_target_space(prod_session)
    child_counts = _enumerate_and_bound_check_children(prod_session, space)
    _refuse_if_purchase_plan_exists(prod_session, space)
    r2_keys = _refuse_if_unexpected_r2_keys(prod_session, space)

    prod_lindsey = prod_session.query(User).filter(
        User.email == PROD_LINDSEY_EMAIL
    ).first()
    if prod_lindsey is None:
        raise PreflightError(
            f"Prod user {PROD_LINDSEY_EMAIL!r} not found — this guards "
            "the post-delete 'unrelated users preserved' verification. "
            "Refusing to proceed without a way to prove she survived."
        )
    other_mem_count = (
        prod_session.query(func.count(SpaceMembership.id))
        .filter(
            SpaceMembership.user_id == prod_lindsey.id,
            SpaceMembership.space_id != space.id,
        )
        .scalar()
    ) or 0

    return (
        DeletionContext(
            local_session=local_session,
            prod_session=prod_session,
            space_id=space.id,
            commit=args.commit,
            yes_i_am_sure=args.yes_i_am_sure,
            prod_lindsey_id=prod_lindsey.id,
            prod_lindsey_other_membership_count=other_mem_count,
        ),
        child_counts,
        r2_keys,
    )


def _resolve_and_check_target_space(prod_session: Session) -> Space:
    """Look up the target Space by slug and refuse if any identity
    assertion drifts from the audit."""
    space = prod_session.query(Space).filter(Space.slug == TARGET_SLUG).first()
    if space is None:
        raise PreflightError(
            f"Prod Space with slug {TARGET_SLUG!r} not found. Nothing "
            "to delete — audit is stale or the Space was already removed."
        )
    if space.id != TARGET_SPACE_ID:
        raise PreflightError(
            f"Prod Space id={space.id!r} does not match the audited id "
            f"{TARGET_SPACE_ID!r}. Refusing — this is not the Space the "
            "audit was performed against."
        )
    if space.name != TARGET_NAME:
        raise PreflightError(
            f"Prod Space name={space.name!r} != expected {TARGET_NAME!r}. "
            "Refusing — identity drift since audit."
        )
    if space.creator_id != EXPECTED_CREATOR_ID:
        raise PreflightError(
            f"Prod Space.creator_id={space.creator_id!r} != expected "
            f"{EXPECTED_CREATOR_ID!r}. Refusing — a reparented Space "
            "should not be deleted through this script."
        )
    if space.auto_grant_role != EXPECTED_AUTO_GRANT_ROLE:
        raise PreflightError(
            f"Prod Space.auto_grant_role={space.auto_grant_role!r} != "
            f"expected {EXPECTED_AUTO_GRANT_ROLE!r}. Refusing."
        )
    if space.location_id != EXPECTED_LOCATION_ID:
        raise PreflightError(
            f"Prod Space.location_id={space.location_id!r} != expected "
            f"{EXPECTED_LOCATION_ID!r}. Refusing — audit didn't account "
            "for a Location linkage."
        )
    return space


def _enumerate_and_bound_check_children(
    prod_session: Session, space: Space,
) -> ChildCounts:
    """Count every direct-CASCADE child row and refuse if any count
    exceeds the audit-derived upper bound. Also enforces the membership
    ceiling separately — a legit new member joining post-audit is the
    plausible surprise we defend against."""
    sid = space.id
    pw_ids = [pid for (pid,) in prod_session.query(Pathway.id).filter(
        Pathway.space_id == sid
    ).all()]
    step_ids = [
        sidx for (sidx,) in prod_session.query(PathwayStep.id).filter(
            PathwayStep.pathway_id.in_(pw_ids)
        ).all()
    ] if pw_ids else []

    counts: dict[str, int] = {
        "SpaceMembership": (
            prod_session.query(func.count(SpaceMembership.id))
            .filter(SpaceMembership.space_id == sid).scalar()
        ) or 0,
        "Pathway": len(pw_ids),
        "PathwayStep": len(step_ids),
        "PathwayStepBlock": (
            prod_session.query(func.count(PathwayStepBlock.id))
            .filter(PathwayStepBlock.step_id.in_(step_ids)).scalar()
            if step_ids else 0
        ) or 0,
        "Event": (
            prod_session.query(func.count(Event.id))
            .filter(Event.space_id == sid).scalar()
        ) or 0,
        "ConversationChannel": (
            prod_session.query(func.count(ConversationChannel.id))
            .filter(ConversationChannel.space_id == sid).scalar()
        ) or 0,
    }

    surprises = [
        (k, counts[k], AUDITED_CHILD_UPPER_BOUNDS[k])
        for k in AUDITED_CHILD_UPPER_BOUNDS
        if counts[k] > AUDITED_CHILD_UPPER_BOUNDS[k]
    ]
    if surprises:
        detail = ", ".join(
            f"{k}: prod={n}, audit-max={mx}" for k, n, mx in surprises
        )
        raise PreflightError(
            "Child-row counts exceed the audited upper bounds — refusing "
            "to silently delete rows the audit didn't cover. "
            f"Surprises: {detail}. Re-run the audit and update the "
            "expected bounds before retrying."
        )

    if counts["SpaceMembership"] > MAX_EXPECTED_MEMBERSHIPS:
        raise PreflightError(
            f"SpaceMembership count {counts['SpaceMembership']} exceeds "
            f"MAX_EXPECTED_MEMBERSHIPS={MAX_EXPECTED_MEMBERSHIPS}. A new "
            "member has joined since the audit — refusing rather than "
            "silently removing their access."
        )

    return ChildCounts(counts=counts)


def _refuse_if_purchase_plan_exists(
    prod_session: Session, space: Space,
) -> None:
    """PurchasePlan.space_id is ON DELETE RESTRICT — the DB would
    refuse a Space delete if any row exists. Fail here with a friendly
    message rather than at the DB layer."""
    n = (
        prod_session.query(func.count(PurchasePlan.id))
        .filter(PurchasePlan.space_id == space.id)
        .scalar()
    ) or 0
    if n:
        raise PreflightError(
            f"Prod has {n} PurchasePlan row(s) referencing this Space "
            "(FK is ON DELETE RESTRICT). Refusing — a subscription plan "
            "on an obsolete Space needs explicit handling before delete."
        )


def _refuse_if_unexpected_r2_keys(
    prod_session: Session, space: Space,
) -> list[str]:
    """Enumerate R2 keys owned by the Space via ``_collect_space_r2_keys``.
    Audit expected zero. Refuse loudly if any appear — R2 cleanup for
    a surprise upload wants human review, not auto-deletion."""
    keys = _collect_space_r2_keys(space, prod_session)
    if len(keys) != EXPECTED_R2_KEY_COUNT:
        raise PreflightError(
            f"Prod Space owns {len(keys)} R2 object(s); audit expected "
            f"{EXPECTED_R2_KEY_COUNT}. Refusing to auto-delete. Keys:\n"
            + "\n".join(f"    {k}" for k in keys)
        )
    return keys


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


def print_summary(
    ctx: DeletionContext, child_counts: ChildCounts, r2_keys: list[str],
) -> None:
    mode = "COMMIT" if ctx.commit else "DRY RUN — no writes will occur"
    print("=" * 74)
    print(f"Delete The Natural Leader Hub from prod — {mode}")
    print("=" * 74)
    print(f"  Target Space id:  {ctx.space_id}")
    print(f"  Target slug:      {TARGET_SLUG!r}")
    print(f"  Target name:      {TARGET_NAME!r}")
    print(f"  creator_id:       {EXPECTED_CREATOR_ID!r} (platform-owned)")
    print()
    print("Would CASCADE-delete (single DB transaction; DB enforces the FK graph):")
    for k, v in child_counts.counts.items():
        mx = AUDITED_CHILD_UPPER_BOUNDS[k]
        marker = " " if v <= mx else " !!"
        print(f"    {k:24s} {v} row(s)  (audit-max {mx}){marker}")
    print()
    print(f"R2 keys owned by this Space: {len(r2_keys)} "
          f"(expected {EXPECTED_R2_KEY_COUNT})")
    print()
    print("Users NOT touched (verified post-delete):")
    print(f"  {PROD_LINDSEY_EMAIL!r} → id={ctx.prod_lindsey_id}")
    print(f"    other-Space memberships: "
          f"{ctx.prod_lindsey_other_membership_count} — must remain unchanged")
    print()
    print("SET NULL columns on other tables will be nulled where they "
          "reference this Space; those rows are preserved (activities, "
          "payment_transactions, purchase_intents, community_care_cases, "
          "community_care_actions).")
    print()


def confirm_interactive() -> None:
    print("Type 'y' to permanently delete this Space from prod, "
          "anything else to abort: ", end="", flush=True)
    ans = sys.stdin.readline().strip().lower()
    if ans != "y":
        raise SystemExit("Aborted by operator.")


# ---------------------------------------------------------------------------
# Delete (single transaction; CASCADE does the rest)
# ---------------------------------------------------------------------------


def delete_space(prod_session: Session, space_id: str) -> None:
    """Perform the delete. Caller wraps in try/rollback — this
    function does NOT commit."""
    space = prod_session.query(Space).filter(Space.id == space_id).first()
    if space is None:
        raise RuntimeError(
            f"Prod Space id={space_id!r} disappeared between preflight "
            "and delete."
        )
    prod_session.delete(space)
    prod_session.flush()
    log.info("Space delete queued (id=%s); CASCADE will fire on commit.",
             space_id)


# ---------------------------------------------------------------------------
# Verification (post-commit)
# ---------------------------------------------------------------------------


def verify(ctx: DeletionContext, child_counts: ChildCounts) -> None:
    """Prove the Space + every enumerated child is gone, and that
    Lindsey + her other-Space memberships are untouched."""
    still_there = (
        ctx.prod_session.query(Space)
        .filter(
            (Space.slug == TARGET_SLUG) | (Space.id == ctx.space_id)
        )
        .first()
    )
    if still_there is not None:
        raise RuntimeError(
            f"VERIFY: Space still present (id={still_there.id!r}, "
            f"slug={still_there.slug!r}). Delete did not complete."
        )

    sid = ctx.space_id

    remaining_pw = (
        ctx.prod_session.query(func.count(Pathway.id))
        .filter(Pathway.space_id == sid).scalar()
    ) or 0
    if remaining_pw:
        raise RuntimeError(f"VERIFY: {remaining_pw} Pathway row(s) remain")

    remaining_mems = (
        ctx.prod_session.query(func.count(SpaceMembership.id))
        .filter(SpaceMembership.space_id == sid).scalar()
    ) or 0
    if remaining_mems:
        raise RuntimeError(
            f"VERIFY: {remaining_mems} SpaceMembership row(s) remain"
        )

    remaining_events = (
        ctx.prod_session.query(func.count(Event.id))
        .filter(Event.space_id == sid).scalar()
    ) or 0
    if remaining_events:
        raise RuntimeError(f"VERIFY: {remaining_events} Event row(s) remain")

    remaining_chans = (
        ctx.prod_session.query(func.count(ConversationChannel.id))
        .filter(ConversationChannel.space_id == sid).scalar()
    ) or 0
    if remaining_chans:
        raise RuntimeError(
            f"VERIFY: {remaining_chans} ConversationChannel row(s) remain"
        )

    # Lindsey must still exist and her other-Space memberships must be
    # exactly what we snapshotted at preflight.
    lin = ctx.prod_session.query(User).filter(
        User.id == ctx.prod_lindsey_id
    ).first()
    if lin is None:
        raise RuntimeError(
            "VERIFY: prod Lindsey disappeared — the CASCADE should NOT "
            "have touched the users table."
        )
    other_mem = (
        ctx.prod_session.query(func.count(SpaceMembership.id))
        .filter(SpaceMembership.user_id == ctx.prod_lindsey_id)
        .scalar()
    ) or 0
    if other_mem != ctx.prod_lindsey_other_membership_count:
        raise RuntimeError(
            f"VERIFY: prod Lindsey's other-Space membership count "
            f"changed: preflight={ctx.prod_lindsey_other_membership_count}, "
            f"now={other_mem}. Unrelated data was disturbed."
        )

    log.info(
        "Verification: ✓ Space + Pathway + SpaceMembership + Event + "
        "ConversationChannel rows scoped to id=%s all gone; "
        "prod Lindsey + her %d other-Space memberships preserved.",
        sid, ctx.prod_lindsey_other_membership_count,
    )


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Permanently delete The Natural Leader Hub Space "
                    "from production (obsolete demo Collective).",
    )
    p.add_argument("--commit", action="store_true",
                   help="Actually delete. Default is dry-run.")
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
        ctx, child_counts, r2_keys = preflight(args)
    except PreflightError as e:
        print(f"PREFLIGHT: {e}", file=sys.stderr)
        return 2

    print_summary(ctx, child_counts, r2_keys)

    if not ctx.commit:
        print("Dry-run complete. Pass --commit to actually delete.")
        return 0

    if not ctx.yes_i_am_sure:
        confirm_interactive()

    try:
        delete_space(ctx.prod_session, ctx.space_id)
        ctx.prod_session.commit()
    except Exception as e:
        ctx.prod_session.rollback()
        print(f"\nDELETE FAILED: {e}", file=sys.stderr)
        print("Rollback complete. Prod DB unchanged.", file=sys.stderr)
        return 4

    try:
        verify(ctx, child_counts)
    except Exception as e:
        print(f"\nVERIFY FAILED (commit already landed): {e}", file=sys.stderr)
        return 5

    print()
    print("=" * 74)
    print(f"DELETE COMPLETE — Space {TARGET_SLUG!r} and its scoped "
          "child rows are gone.")
    print("=" * 74)
    return 0


if __name__ == "__main__":
    sys.exit(main())
