"""Give ``direct_message_email`` the column it has always been read from.

``app/messages/routes.py`` has passed ``pref_key="direct_message_email"``
since direct messages shipped, and ``_get_notification_pref`` lists it in
its defaults dict — but no column has ever existed. The two branches of
that lookup therefore disagree:

* a member with **no** prefs row falls through to the defaults dict,
  finds ``True``, and is emailed;
* a member **with** a row takes ``getattr(prefs, pref_key, False)``,
  which cannot find the attribute and returns ``False``.

A row is created by saving *any* preference on /settings/stay-connected —
a page that has never offered a direct-message toggle. So the act of
visiting notification settings silently and permanently stopped direct
message emails for that Collective, with no way for the member to turn
them back on. In-app notifications were unaffected: they are created
before the email branch is reached.

``server_default="true"`` matches the defaults dict, so existing rows
are repaired to the behaviour members would have had before they ever
opened the page, rather than to the accidental ``False``.

Revision ID: 169
Revises: 168
"""
from alembic import op
import sqlalchemy as sa


revision = "169"
down_revision = "168"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "space_member_notification_prefs",
        sa.Column(
            "direct_message_email",
            sa.Boolean(),
            nullable=False,
            server_default="true",
        ),
    )


def downgrade() -> None:
    op.drop_column("space_member_notification_prefs", "direct_message_email")
