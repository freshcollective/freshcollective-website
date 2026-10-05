"""Move in-app notification links off the old frontend host.

Why these are rewritten when sent emails are not
------------------------------------------------
A delivered email is a record of what was actually sent. Editing it
would make the history say something that never happened, and the
member's copy is in their inbox regardless — nothing is gained.

An in-app notification is not a record. It is live navigation: the row
*is* the link, and tapping it today takes a member somewhere. One
pointing at ``fc-web-q950.onrender.com`` sends them to a hostname that
is not the product and will stop resolving when the service is renamed
or retired. So these get corrected and the email ledger does not.

How narrow the rewrite is
-------------------------
Exactly one origin — scheme, host and port — is matched, and only the
origin changes. Path, query and fragment are preserved byte for byte,
because a notification URL can carry a token and the token was never
the problem.

Explicitly left alone: any other ``onrender.com`` subdomain, every
external host (Stripe among them), and relative paths, which are how
most in-app links are stored and which have no origin to correct.

That is deliberately stricter than the route-time canonicalisation in
``comms/routing/routing.py``. That one is a safety net on content being
generated now, so it keys on "any non-public host". This one edits rows
that already exist, so it keys on the single host we know was wrong.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.url_policy import replace_origin

logger = logging.getLogger(__name__)

#: The host fc-web served on before the custom domain. The only origin
#: this tool will rewrite.
OLD_ORIGIN = "https://fc-web-q950.onrender.com"

#: Columns checked for the old host but never rewritten. A notification
#: body is content, not navigation; if the host appears in one, that is
#: worth reporting to a person rather than editing silently.
CONTENT_COLUMNS = ("title", "message")


@dataclass
class Finding:
    """One notification row carrying the old origin in its link."""

    notification_id: str
    notification_type: str | None
    user_id: str | None
    email: str | None
    created_at: object | None
    is_read: bool | None
    old_url: str
    new_url: str

    #: Set when the row needs a person rather than a rewrite.
    warnings: list[str] = field(default_factory=list)

    @property
    def safe(self) -> bool:
        return not self.warnings and self.new_url != self.old_url


@dataclass
class ContentMention:
    """The old host inside notification text rather than its link."""

    notification_id: str
    column: str
    excerpt: str


def audit(db: Session) -> tuple[list[Finding], list[ContentMention]]:
    """Every notification whose ``url`` carries the old origin.

    Writes nothing. ``strpos`` rather than ``LIKE`` — these URLs are
    full of underscores and hyphens and ``LIKE`` reads ``_`` as "any
    character".
    """
    rows = db.execute(text(
        "SELECT n.id, n.notification_type, n.user_id, u.email, n.created_at, "
        "       n.is_read, n.url "
        "FROM notifications n "
        "LEFT JOIN users u ON u.id = n.user_id "
        "WHERE strpos(coalesce(n.url, ''), :needle) > 0 "
        "ORDER BY n.created_at"
    ), {"needle": "onrender.com"}).all()

    findings: list[Finding] = []
    for row in rows:
        old_url = row[6]
        new_url = replace_origin(old_url, OLD_ORIGIN, _public_base())
        finding = Finding(
            notification_id=row[0], notification_type=row[1], user_id=row[2],
            email=row[3], created_at=row[4], is_read=row[5],
            old_url=old_url, new_url=new_url or old_url,
        )
        if new_url == old_url:
            # Matched ``onrender.com`` but not the one origin this tool
            # rewrites. Reported, never guessed at.
            finding.warnings.append(
                f"host is not {OLD_ORIGIN} — left unchanged for review"
            )
        findings.append(finding)

    mentions: list[ContentMention] = []
    for column in CONTENT_COLUMNS:
        for row in db.execute(text(
            f"SELECT id, {column} FROM notifications "  # noqa: S608 - allowlist
            f"WHERE strpos(coalesce({column}, ''), :needle) > 0 LIMIT 50"
        ), {"needle": "onrender.com"}).all():
            mentions.append(ContentMention(
                notification_id=row[0], column=column,
                excerpt=(row[1] or "")[:160],
            ))

    return findings, mentions


def _public_base() -> str:
    from app.core.public_url import public_app_url
    return public_app_url()


def destination_is_usable() -> str | None:
    """Why this must not run against the current configuration, if so.

    Checked once for the run rather than per row: rewriting production
    notification links to ``http://localhost:3000`` is the obvious way
    to do real damage with this tool, and it is a property of the
    environment, not of any row.
    """
    base = _public_base()
    if not base.startswith("https://"):
        return (
            f"the configured public address is {base!r}, which is not an "
            f"https origin. Run this where PUBLIC_APP_URL is the real public "
            f"domain — rewriting live notification links to a local address "
            f"would be worse than leaving them alone."
        )
    if base.rstrip("/") == OLD_ORIGIN:
        return (
            "the configured public address is the old host itself, so there "
            "is nothing to move these links to."
        )
    return None


def apply(db: Session, findings: list[Finding]) -> list[Finding]:
    """Rewrite the safe findings. Caller commits.

    Each update is guarded on the exact URL it was audited with, so a
    row changed between the audit and the apply is skipped rather than
    overwritten. Nothing but ``url`` is touched.
    """
    updated: list[Finding] = []
    for finding in findings:
        if not finding.safe:
            continue
        result = db.execute(text(
            "UPDATE notifications SET url = :new "
            "WHERE id = :id AND url = :old"
        ), {
            "new": finding.new_url,
            "id": finding.notification_id,
            "old": finding.old_url,
        })
        if result.rowcount:
            updated.append(finding)
            logger.info(
                "notification_links: %s -> %s (%s)",
                finding.old_url, finding.new_url, finding.notification_id,
            )
    return updated


def remaining(db: Session) -> int:
    """Notifications still linking to the old origin. Must be zero after
    a successful apply."""
    return db.scalar(text(
        "SELECT count(*) FROM notifications "
        "WHERE strpos(coalesce(url, ''), :needle) > 0"
    ), {"needle": _origin_host()}) or 0


def _origin_host() -> str:
    from urllib.parse import urlsplit
    return urlsplit(OLD_ORIGIN).netloc
