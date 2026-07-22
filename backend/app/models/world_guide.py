"""SQLAlchemy models for the World Guide.

Shape mirrors migration 087. Enum-shaped fields are kept as string
tuples here so the Pydantic schema layer and the CHECK constraints
stay in lockstep.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


# ---------------------------------------------------------------------------
# Enum-shaped string constants — kept in sync with migration 087's CHECKs.
# ---------------------------------------------------------------------------

DOCUMENT_CATEGORIES: tuple[str, ...] = (
    "governance", "members", "creators", "platform", "other",
)
DOCUMENT_AUDIENCES: tuple[str, ...] = (
    "everyone", "members", "creators", "platform_owner", "other",
)
VERSION_STATUSES: tuple[str, ...] = ("draft", "published", "archived")


# ---------------------------------------------------------------------------


class WorldGuideDocument(Base):
    """A governance document as an abstract "record" — metadata that
    persists across every version of the document. Version content
    lives on :class:`WorldGuideVersion`.

    ``current_version_id`` points at the version that appears on the
    public World Guide right now. It is nullable — a document with
    only draft versions has no current published version yet.
    """

    __tablename__ = "world_guide_documents"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    slug: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    audience: Mapped[str] = mapped_column(String(32), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    author_user_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    reading_time_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True,
    )
    current_version_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("world_guide_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False,
        server_default=func.now(), onupdate=func.now(),
    )


class WorldGuideVersion(Base):
    """One version of a :class:`WorldGuideDocument`.

    A version is either ``draft`` (mutable), ``published`` (frozen —
    never edited again), or ``archived`` (a previously published
    version that has been superseded but is still viewable in
    history).

    Every published version is preserved. To edit a published
    document, admins create a new draft version — they do not edit
    the published row.
    """

    __tablename__ = "world_guide_versions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    document_id: Mapped[str] = mapped_column(
        String, ForeignKey("world_guide_documents.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    version_number: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    effective_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Structured content sections. Each renders as its own visible
    # block on the public document page. Markdown-shaped text, rendered
    # client-side by the World Guide reader.
    why_this_exists: Mapped[str | None] = mapped_column(Text, nullable=True)
    what_this_covers: Mapped[str | None] = mapped_column(Text, nullable=True)
    main_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    whats_changed: Mapped[str | None] = mapped_column(Text, nullable=True)

    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True,
    )
    published_by_user_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    last_edited_by_user_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False,
        server_default=func.now(), onupdate=func.now(),
    )

    __table_args__ = (
        UniqueConstraint(
            "document_id", "version_number",
            name="uq_wg_versions_document_version_number",
        ),
    )


class WorldGuideAcceptance(Base):
    """Records a member's acceptance of a specific version of a
    governance document. Future-proofing: the model exists so the
    schema can start tracking acceptances without another migration
    once the workflow ships. No endpoints expose it yet.
    """

    __tablename__ = "world_guide_acceptances"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    version_id: Mapped[str] = mapped_column(
        String, ForeignKey("world_guide_versions.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    accepted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now(),
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id", "version_id",
            name="uq_wg_acceptances_user_version",
        ),
    )


# ---------------------------------------------------------------------------
# Utilities used by the read + write paths.
# ---------------------------------------------------------------------------


_WORDS_PER_MINUTE = 220


def estimate_reading_time_minutes(*sections: str | None) -> int:
    """Rough estimate of reading time in whole minutes.

    Counts whitespace-separated tokens across every section and
    divides by ~220 words per minute — the standard silent-reading
    rate. Minimum 1 minute so short documents don't display "0 min".
    """
    words = sum(len((s or "").split()) for s in sections)
    if words == 0:
        return 1
    return max(1, round(words / _WORDS_PER_MINUTE))


def next_version_number(prev: str | None, *, kind: str = "draft") -> str:
    """Compute the next version number.

    - No prior version → ``"0.1"`` (initial draft).
    - Prior draft ``M.N`` → same series stays on drafting cycle;
      publishing bumps the minor (or major on first publish).
    - Prior published ``M.N`` and creating a new draft → next minor
      as a draft (``M.(N+1)``).
    """
    if prev is None:
        return "0.1"
    try:
        major_str, minor_str = prev.split(".")
        major = int(major_str)
        minor = int(minor_str)
    except (ValueError, AttributeError):
        return "0.1"
    if kind == "publish_initial":
        return "1.0"
    if kind == "publish_next":
        return f"{major}.{minor + 1}"
    # Creating a new draft after a published version.
    return f"{major}.{minor + 1}"
