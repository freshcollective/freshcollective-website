"""Reporting a member from a peer conversation.

Routes into the existing Community Care framework rather than a second
reporting system, and needs **no schema change** to do it:

  * ``member_behaviour`` is already a CHECK-permitted case
    ``content_type``;
  * ``community_care_cases.subject_space_id`` is already nullable, so a
    case with no Collective is representable;
  * ``subject_member_user_id`` already exists;
  * ``content_snapshot`` is already documented as "a point-in-time copy
    of the reported content… kept for review and audit even if the
    source is later edited or removed" — exactly what a conversation
    reference needs to be;
  * ``community_care_reports.content_type`` has no CHECK, so a peer
    report can name itself.

The 5c audit said the existing report route "derives subject_space_id
and assumes a Collective context". That was true of the *route*, not
the schema — ``submit_member_report`` requires exactly one of a post or
comment target, which a conversation has neither of. So this is a
second intake into the same framework, not a change to the framework.
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy.orm import Session

from app.community_care.shared import (
    find_open_case,
    next_case_number,
    write_event,
)
from app.models.community_care import (
    REPORT_CATEGORIES,
    CommunityCareCase,
    CommunityCareReport,
)

__all__ = ["REPORT_CATEGORIES", "submit_peer_report"]

#: How many messages of context a case carries. Enough for a reviewer
#: to see what happened without copying an entire relationship into the
#: moderation surface.
SNAPSHOT_MESSAGE_LIMIT = 30


def _snapshot(thread_id: str, messages: list, message_id: str | None) -> dict:
    """Point-in-time evidence for the case.

    Stored because the live conversation is not a safe source of truth
    for a review: either participant may send more, and a reviewer needs
    what was reported. The most recent messages are kept — the tail is
    what a report is usually about.
    """
    tail = messages[-SNAPSHOT_MESSAGE_LIMIT:]
    return {
        "kind": "peer_conversation",
        "peer_thread_id": thread_id,
        "reported_message_id": message_id,
        "message_count": len(messages),
        "messages": [
            {
                "id": m.id,
                "sender_user_id": m.sender_user_id,
                "body": m.body,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in tail
        ],
    }


def submit_peer_report(
    db: Session,
    *,
    reporter_user_id: str,
    reported_user_id: str,
    thread_id: str,
    category: str,
    reporter_note: str | None,
    message_id: str | None,
    messages: list,
) -> str:
    """Open or extend a Community Care case about a peer member.

    Mirrors ``submit_member_report``: dedupes onto an open case about
    the same member, increments ``report_count`` rather than opening a
    second, and writes the same audit events — so a peer report behaves
    like every other report in the admin surfaces.

    Does not commit; the route owns the transaction. Does not notify the
    reported member, and does not block — reporting and blocking are
    offered together in the UI but are independent actions.
    """
    now = datetime.utcnow()

    case = find_open_case(db, target_member_user_id=reported_user_id)
    if case is None:
        case = CommunityCareCase(
            id=str(uuid4()),
            case_number=next_case_number(db, now),
            content_type="member_behaviour",
            subject_member_user_id=reported_user_id,
            # No Collective: a peer conversation belongs to none, and
            # the column is nullable precisely for subjects like this.
            subject_space_id=None,
            subject_creator_user_id=None,
            content_snapshot=_snapshot(thread_id, messages, message_id),
            category=category,
            status="new",
            priority="low",
            report_count=1,
            opened_at=now,
        )
        db.add(case)
        db.flush()
        write_event(
            db,
            case=case,
            kind="case_opened",
            actor_user_id=reporter_user_id,
            new_value={
                "case_number": case.case_number,
                "content_type": case.content_type,
                "reporter_kind": "member",
                "context": "peer_conversation",
            },
        )
    else:
        case.report_count = (case.report_count or 0) + 1
        case.updated_at = now

    report = CommunityCareReport(
        id=str(uuid4()),
        case_id=case.id,
        reporter_user_id=reporter_user_id,
        reporter_kind="member",
        # Names itself so a reviewer can tell at a glance that this came
        # from a private conversation rather than a Collective's feed.
        content_type="peer_conversation",
        target_member_user_id=reported_user_id,
        category=category,
        reporter_note=reporter_note,
    )
    db.add(report)
    db.flush()
    write_event(
        db,
        case=case,
        kind="report_attached",
        actor_user_id=reporter_user_id,
        new_value={
            "report_id": report.id,
            "category": category,
            "reporter_kind": "member",
            "context": "peer_conversation",
        },
    )
    return case.case_number
