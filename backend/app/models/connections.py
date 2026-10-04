"""Mutual "Say hello" between two members.

Design: two directed rows, not one undirected relationship
--------------------------------------------------------------
A hello is a *directed* act — A greeted B — and the product's four
states are exactly what two directed rows express:

    neither row          → no hello
    A→B only             → outgoing for A, incoming for B
    both rows            → mutual

The alternative, one row per pair with a status column, needs a
canonical ordering of the two user ids and a state machine whose
transitions can interleave: if A and B greet each other at the same
moment, both requests read "no relationship", both try to create the
pair row, and one has to lose and retry as an update. Mutuality then
lives in a column that can disagree with reality.

With directed rows there is nothing to contend. Each side inserts its
own row, the unique constraint makes a repeat click a no-op, and
mutuality is *derived* — the reciprocal row either exists or it does
not. There is no state to corrupt and no ordering to get right.

It also gives persistence for free. Rows are never deleted, so a
connection survives the recommendation evidence that introduced it: an
upcoming Gathering passing, a Pathway changing state, or the pair simply
no longer being surfaced. Eligibility governs discovery and the first
hello; it does not govern a connection two people already made.
"""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MemberHello(Base):
    """One member has said hello to another.

    Append-only. Nothing in this work item deletes a hello: there is no
    "unsay hello" in the product, and withdrawal would need its own
    product decision about what the other person sees.
    """

    __tablename__ = "member_hellos"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    #: Who greeted.
    from_user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
    )
    #: Who was greeted.
    to_user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False,
    )

    __table_args__ = (
        # Makes a repeat click a no-op at the database rather than in
        # application logic, which is what keeps it idempotent under
        # concurrent requests too.
        UniqueConstraint("from_user_id", "to_user_id", name="uq_member_hellos_pair"),
        # Nobody greets themselves. Enforced here as well as in the
        # service so no future caller can reintroduce it.
        CheckConstraint("from_user_id <> to_user_id", name="ck_member_hellos_not_self"),
        # Both directions are read on every card render: outgoing for
        # the viewer, and incoming to decide whether to show "they said
        # hello". The unique constraint already indexes
        # (from_user_id, to_user_id); this covers lookups keyed on the
        # recipient.
        Index("ix_member_hellos_to_user", "to_user_id"),
    )
