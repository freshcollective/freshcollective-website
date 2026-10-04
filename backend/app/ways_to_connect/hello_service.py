"""Saying hello, and the mutual connection it can become.

State is derived, not stored
----------------------------
There is no status column. A hello is a directed row, and the four
states the product needs are read off which of the two possible rows
exist — see ``app/models/connections.py`` for why that shape beat an
undirected pair row with a state machine.

    HelloState.NONE      neither row
    HelloState.OUTGOING  viewer → other only
    HelloState.INCOMING  other → viewer only
    HelloState.MUTUAL    both

Because mutuality is derived, it cannot disagree with the rows, and two
people greeting each other at the same instant converge on MUTUAL
without either request needing to know about the other.
"""

from __future__ import annotations

import logging
from enum import Enum
from uuid import uuid4

from sqlalchemy import or_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.connections import MemberHello

logger = logging.getLogger(__name__)


class HelloState(str, Enum):
    NONE = "none"
    OUTGOING = "outgoing"
    INCOMING = "incoming"
    MUTUAL = "mutual"


def _state(sent: bool, received: bool) -> HelloState:
    if sent and received:
        return HelloState.MUTUAL
    if sent:
        return HelloState.OUTGOING
    if received:
        return HelloState.INCOMING
    return HelloState.NONE


def hello_states(
    db: Session, viewer_id: str, other_user_ids: set[str],
) -> dict[str, HelloState]:
    """Relationship state between the viewer and each of ``other_user_ids``.

    One query for the whole page rather than one per card. Ids the
    viewer has no row with simply resolve to ``NONE``, so the caller
    does not have to distinguish "no hello" from "not asked about".
    """
    if not other_user_ids:
        return {}

    rows = (
        db.query(MemberHello)
        .filter(
            or_(
                MemberHello.from_user_id == viewer_id,
                MemberHello.to_user_id == viewer_id,
            )
        )
        .all()
    )
    sent = {r.to_user_id for r in rows if r.from_user_id == viewer_id}
    received = {r.from_user_id for r in rows if r.to_user_id == viewer_id}
    return {
        other: _state(other in sent, other in received)
        for other in other_user_ids
    }


def hello_state(db: Session, viewer_id: str, other_user_id: str) -> HelloState:
    """Relationship state for a single pair."""
    return hello_states(db, viewer_id, {other_user_id}).get(
        other_user_id, HelloState.NONE,
    )


def incoming_hellos_recent_first(db: Session, viewer_id: str) -> list[str]:
    """Everyone who has said hello to the viewer, most recent first.

    Used to make an incoming hello discoverable even when the sender
    falls outside the day's introductions — somebody greeting you should
    not be buried because the rotation put them on page two.

    Ordered, not a set, because the page shows at most
    ``selection.MAX_PEOPLE`` people and more than that many greetings can
    be waiting. Something then has to decide which are shown, and the
    order has to be stable or the cards would shuffle on every reload.

    Most recent first, so a new greeting is seen promptly and an old
    unanswered one cannot hold a slot forever. The alternative —
    longest-waiting first — sounds fairer and behaves worse: a greeting
    the viewer has decided not to answer would sit at the top
    indefinitely and bury every greeting that came after it.

    Being shown is not what permits a reply. ``is_eligible_pair`` is the
    authorisation rule and is not limited, so a greeting that falls off
    today's page can still be answered — the sender's own page, and the
    notification they generated, both still reach the viewer.
    """
    return [
        r.from_user_id
        for r in db.query(MemberHello)
        .filter(MemberHello.to_user_id == viewer_id)
        .order_by(MemberHello.created_at.desc(), MemberHello.from_user_id)
        .all()
    ]


def say_hello(
    db: Session, from_user_id: str, to_user_id: str,
) -> tuple[HelloState, bool]:
    """Record a hello. Returns ``(state, created)``. Idempotent.

    ``created`` is False when the hello already existed — including when
    a concurrent request wrote it first. Callers key notifications on
    it, which is what stops a double click, a retry and a page reload
    from each announcing themselves. It cannot be reconstructed after
    the fact, because by then the row exists either way.

    Callers authorise first — this function does not know the Ways to
    Connect eligibility rule and must not learn it. It does refuse a
    self-hello, because that is a property of the data rather than of
    any policy.

    Idempotency is the unique constraint's, not a prior read's: a second
    click, a retried request and two concurrent requests all attempt the
    same insert, and the loser of the race is caught here and treated as
    success. Checking "does a row exist" first would still leave the gap
    between the check and the insert.

    Does not commit — the route owns the transaction, so the hello and
    its notification land together or not at all.
    """
    if from_user_id == to_user_id:
        raise ValueError("A member cannot say hello to themselves.")

    # One statement, no prior read. ``ON CONFLICT DO NOTHING`` makes the
    # unique constraint the only arbiter of whether this hello already
    # existed, which is both simpler and strictly safer than checking
    # first: a pre-check leaves a window in which a concurrent request
    # inserts between the read and the write, and it would also make the
    # conflict clause unreachable in every sequential test — a
    # concurrency safeguard nothing exercises.
    #
    # It never raises, so it needs no SAVEPOINT and cannot disturb the
    # caller's transaction, which matters because the route writes a
    # notification in the same one.
    #
    # ``rowcount`` is the honest answer to "did I create it": 1 when this
    # call inserted, 0 when the row was already there. That is what keeps
    # a double click, a retry and a race from each announcing themselves.
    result = db.execute(
        pg_insert(MemberHello.__table__)
        .values(
            id=str(uuid4()),
            from_user_id=from_user_id,
            to_user_id=to_user_id,
        )
        .on_conflict_do_nothing(constraint="uq_member_hellos_pair")
    )
    created = result.rowcount == 1
    if not created:
        logger.info(
            "say_hello: hello from=%s to=%s already existed — treating as sent",
            from_user_id, to_user_id,
        )

    return hello_state(db, from_user_id, to_user_id), created
