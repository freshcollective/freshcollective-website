"""Let members control the Account email category again.

Revision ID: 133
Revises: 132
Create Date: 2026-09-19

Motivation
----------
``communication_channel_defaults`` seeded (account, email_transactional)
as ``is_locked=True`` in migration 097. At the time that lock was the
only thing standing between a member's "quieten everything" and an
email verification they could not do without, so it was pointed at the
whole category.

It is no longer the only thing. Every essential Account email now
carries an explicit event-level lock in
``app.comms.registry.TRANSACTIONAL_EVENT_TYPES`` — email verification,
password reset, collective invitation, creator plan activation and the
four creator-subscription lifecycle emails — and that lock is both
stronger and narrower. Stronger, because it also forces immediate
delivery, so a digest cadence cannot defer a password reset, and it
exempts the email from the daily rate cap and from quiet hours.
Narrower, because it names emails rather than a category.

What the category lock is still doing, therefore, is holding exactly
one email hostage: the welcome note. A greeting is not a security
message, a receipt or an access-state change, and a member who would
rather not have one should be able to say so. Keeping the lock also
left World Management honestly but confusingly reporting the welcome
email as "Transactional".

Effect
------
Exactly one live email changes behaviour: ``account.welcome_after_signup``
becomes preference-controlled. Nothing else in the category can move.

* The eight event-locked Account emails ignore the category preference
  entirely — the lock they rely on is in code, not in this row.
* ``account.created`` and ``account.password_reset_completed`` have no
  email template and send nothing.
* ``diagnostics.provider_probe`` is a dev-only diagnostic whose
  endpoint builds its intent directly and never consults a preference.

``default_enabled`` is deliberately untouched: with no override, a new
member still receives the welcome email exactly as before. Only the
ability to decline it is restored.

Scope
-----
* (account, in_app) keeps its lock. An in-app notice interrupts
  nobody, and the duty-of-care argument for it is unchanged.
* Purchases and Safety are untouched.

Safety
------
* One boolean on one seeded reference row. No member data is read or
  written, no preference rows are created or removed.
* Reversible: ``downgrade`` restores the lock. A member override saved
  while unlocked would then stop being writable, but
  ``get_effective_preference`` reports ``is_locked`` from this row, so
  the decision pipeline ignores such a row's ``silent`` the moment the
  lock returns — the pre-migration behaviour exactly.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "133"
down_revision = "132"
branch_labels = None
depends_on = None


_ROW = sa.text(
    "UPDATE communication_channel_defaults SET is_locked = :locked "
    "WHERE category_key = 'account' AND channel = 'email_transactional'"
)


def upgrade() -> None:
    op.get_bind().execute(_ROW, {"locked": False})


def downgrade() -> None:
    op.get_bind().execute(_ROW, {"locked": True})
