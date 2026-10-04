"""Blocking between members — the one place the rule lives.

Block outranks everything else. A mutual hello says two people agreed
to connect; a block says one of them has withdrawn that, and withdrawal
wins. So every surface that asks "may these two interact?" asks this
module, and none of them re-implements the question.

Symmetric by design. ``is_blocked_between`` ignores *who* blocked whom,
because every consequence is mutual: neither can message the other,
and neither appears to the other in Ways to Connect. Only
:func:`unblock` cares about direction, because only the person who set a
boundary may remove it.
"""

from __future__ import annotations

import logging
from uuid import uuid4

from sqlalchemy import or_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.member_blocks import MemberBlock

logger = logging.getLogger(__name__)


def is_blocked_between(db: Session, user_a: str, user_b: str) -> bool:
    """Is there an active block in *either* direction?

    The question nearly every caller wants. A block is not a mute: it
    stops interaction both ways, so the direction does not change the
    answer.
    """
    if user_a == user_b:
        return False
    return db.query(
        db.query(MemberBlock)
        .filter(
            or_(
                (MemberBlock.blocker_user_id == user_a)
                & (MemberBlock.blocked_user_id == user_b),
                (MemberBlock.blocker_user_id == user_b)
                & (MemberBlock.blocked_user_id == user_a),
            )
        )
        .exists()
    ).scalar()


def blocked_user_ids(db: Session, viewer_id: str) -> set[str]:
    """Everyone the viewer cannot interact with, in one query.

    Both directions collapsed into a single set, so a listing surface
    can exclude them without caring which way round the block runs —
    and without one query per candidate.
    """
    rows = (
        db.query(MemberBlock)
        .filter(
            or_(
                MemberBlock.blocker_user_id == viewer_id,
                MemberBlock.blocked_user_id == viewer_id,
            )
        )
        .all()
    )
    out: set[str] = set()
    for row in rows:
        out.add(
            row.blocked_user_id
            if row.blocker_user_id == viewer_id
            else row.blocker_user_id
        )
    return out


def has_blocked(db: Session, blocker_id: str, blocked_id: str) -> bool:
    """Did *this* member set the block? Direction matters here.

    Used by the UI to decide whether to offer Unblock: the person who
    was blocked must not be shown a control that would clear somebody
    else's boundary, and must not be told the block exists at all.
    """
    return db.query(
        db.query(MemberBlock)
        .filter(
            MemberBlock.blocker_user_id == blocker_id,
            MemberBlock.blocked_user_id == blocked_id,
        )
        .exists()
    ).scalar()


def block(db: Session, blocker_id: str, blocked_id: str) -> bool:
    """Record a block. Returns whether a new row was created.

    Idempotent via the unique constraint rather than a prior read, so a
    double click and two concurrent requests both settle on one row.
    Does not commit — the caller owns the transaction.

    Deliberately does *not* delete hellos, threads or messages. The
    conversation stays readable to both participants, which matters most
    to the person who blocked: it is their record of what happened.
    """
    if blocker_id == blocked_id:
        raise ValueError("A member cannot block themselves.")

    result = db.execute(
        pg_insert(MemberBlock.__table__)
        .values(
            id=str(uuid4()),
            blocker_user_id=blocker_id,
            blocked_user_id=blocked_id,
        )
        .on_conflict_do_nothing(constraint="uq_member_blocks_pair")
    )
    created = result.rowcount == 1
    if created:
        logger.info(
            "member_block: %s blocked %s", blocker_id, blocked_id,
        )
    return created


def unblock(db: Session, blocker_id: str, blocked_id: str) -> bool:
    """Remove the block this member set. Returns whether a row went.

    Only ever removes the caller's own row, so if the other person has
    also blocked them the pair stays blocked — asymmetric state resolves
    only when both sides have cleared. Idempotent: unblocking somebody
    who is not blocked changes nothing and is not an error.
    """
    removed = (
        db.query(MemberBlock)
        .filter(
            MemberBlock.blocker_user_id == blocker_id,
            MemberBlock.blocked_user_id == blocked_id,
        )
        .delete(synchronize_session=False)
    )
    if removed:
        logger.info("member_block: %s unblocked %s", blocker_id, blocked_id)
    return bool(removed)
