"""Relax the B1 CHECK: allow ``valid_from_override`` /
``valid_until_override`` on ``pathway`` grants (still forbid on
``gathering``). Credits (``sessions_per_week`` / ``total_sessions``)
remain event_series-only.

Revision ID: 109
Revises: 108
Create Date: 2026-08-13

Motivation: bundled Pathway grants (a Series-attached PaymentOption
with ``grants_pathway_id`` set) need to carry the effective pathway
entitlement end date so the backfill can encode
"PathwayEntitlement.ends_at = series.ends_at OR option.term_end_date"
without fulfilment later having to *guess* "use the only Series in
this Option" — which will not be a safe assumption once Options
grant multiple experiences.

The original B1 constraint (``payment_option_grants_series_fields_only_for_series``)
lumped credits and windows together as "series-only". This migration
splits that into two narrower constraints:

  * ``payment_option_grants_credits_only_for_series``:
        credits stay series-only (unchanged rule, tighter name).

  * ``payment_option_grants_windows_not_on_gathering``:
        windows allowed on Series + Pathway grants; still forbidden on
        Gathering grants (a booking window has no meaning distinct
        from the Event's own ``starts_at`` / ``ends_at``).

The exactly-one-target CHECK from B1 is untouched.
"""

from __future__ import annotations

from alembic import op


revision = "109"
down_revision = "108"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "payment_option_grants_series_fields_only_for_series",
        "payment_option_grants",
        type_="check",
    )
    op.create_check_constraint(
        "payment_option_grants_credits_only_for_series",
        "payment_option_grants",
        "(grant_kind = 'event_series')"
        " OR (sessions_per_week IS NULL AND total_sessions IS NULL)",
    )
    op.create_check_constraint(
        "payment_option_grants_windows_not_on_gathering",
        "payment_option_grants",
        "(grant_kind IN ('event_series', 'pathway'))"
        " OR (valid_from_override IS NULL AND valid_until_override IS NULL)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "payment_option_grants_windows_not_on_gathering",
        "payment_option_grants",
        type_="check",
    )
    op.drop_constraint(
        "payment_option_grants_credits_only_for_series",
        "payment_option_grants",
        type_="check",
    )
    op.create_check_constraint(
        "payment_option_grants_series_fields_only_for_series",
        "payment_option_grants",
        "(grant_kind = 'event_series') OR ("
        "  sessions_per_week IS NULL"
        "   AND total_sessions IS NULL"
        "   AND valid_from_override IS NULL"
        "   AND valid_until_override IS NULL)",
    )
