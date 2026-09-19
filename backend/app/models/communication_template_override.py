"""Admin overrides for editable email copy.

One row per overridden slot. Fresh Collective's own wording stays in
code as the default; this table holds only what an admin has actually
changed, so an untouched template costs nothing and
**reset-to-default is a DELETE** rather than a copy of the default back
over itself.

Deliberately key-value rather than a
``subject / heading / greeting / body`` column layout. Three templates
branch into entirely different copy — creator plan activation on
``is_fresh_creator``, booking confirmation on ``added_by_creator``,
purchase confirmation on ``payment_mode`` — and several have two or
three distinct body paragraphs that should be separately resettable.
Rows express both without a migration every time a template's copy is
restructured.

No draft state in this phase: a saved override takes effect on the next
send. See ``app/comms/templates/editable.py`` for the resolution rules
and the safety properties this table participates in.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CommunicationTemplateOverride(Base):
    """One admin-edited slot of one email template."""

    __tablename__ = "communication_template_overrides"
    __table_args__ = (
        # One override per slot. The admin save path upserts on this.
        UniqueConstraint(
            "template_key", "slot_id",
            name="uq_comm_tpl_override_key_slot",
        ),
        Index("ix_comm_tpl_override_key", "template_key"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)

    # e.g. "account.welcome_after_signup.email_transactional" — matches
    # the ``key`` on the registered Template class.
    template_key: Mapped[str] = mapped_column(String(160), nullable=False)

    # e.g. "subject" | "heading" | "body.fresh_creator". Must match a
    # slot the template declares; an unknown slot is refused at save and
    # ignored at render.
    slot_id: Mapped[str] = mapped_column(String(80), nullable=False)

    # Plain text, may contain ``{{merge_fields}}``. Never HTML — the
    # canonical shell escapes whatever it is given, and the save path
    # refuses markup outright.
    value: Mapped[str] = mapped_column(Text, nullable=False)

    # Hash of the code default at the moment this override was saved.
    # When a later deploy improves that default the hash stops matching,
    # which is how the admin UI can offer "the Fresh Collective default
    # has changed since you customised this". Never used to overwrite
    # anything automatically.
    default_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)

    # Attribution. There is no general audit-log table in this codebase,
    # so "who last edited this" lives on the row itself. SET NULL rather
    # than CASCADE: losing the admin account must not silently delete
    # the copy they wrote.
    updated_by_user_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now(),
    )

    def __repr__(self) -> str:  # pragma: no cover — debugging aid
        return (
            f"<CommunicationTemplateOverride {self.template_key}"
            f".{self.slot_id}>"
        )
