"""One description of what a Gathering's settings are.

Creating one Gathering and creating a recurring run of them are the
same act with different dates. Both paths build an ``Event`` row from
an ``EventCreateRequest``, and they used to do it with two hand-written
argument lists. The lists drifted: the bulk path never assigned
``venue_locality``, ``ticket_price_cents`` or ``ticket_currency``, so
every recurring Gathering lost its Public location, and a recurring
paid one lost its price or failed the published-ticket CHECK
constraint. Nothing failed loudly, because an omitted keyword argument
is a perfectly good column default.

So the field list lives here once, and both routes spread it.

The three buckets
-----------------
Every column on ``Event`` belongs to exactly one of them, and
:data:`ALL_EVENT_FIELDS` asserts that. Adding a column to the model
without placing it here fails the contract test in
``tests/test_gathering_bulk_field_parity.py`` rather than quietly
shipping a field that only one creation path writes.

``SHARED_EVENT_FIELDS``
    Copied from the request by both paths, unchanged. A Gathering's
    *settings* — what it is, where it is, who may book it.

``TICKET_FIELDS``
    Copied by both paths, but only the values
    ``_validate_ticket_config_or_400`` returns. They are separate from
    the bucket above because they are the one pair that must not be
    read straight off the request: the validator nulls them for a
    non-paid access type and refuses a published paid Gathering with no
    price.

``PER_ROW_EVENT_FIELDS``
    Decided per row by the route rather than copied. Identity, the
    dates (the whole point of a recurrence), the recurrence tags, the
    Series id (resolved against the Space first), and the lifecycle and
    attendance columns that describe what happened at one occurrence
    rather than what the creator configured.

What this module deliberately does not do
-----------------------------------------
It does not validate, raise, touch the session or decide anything about
publication. Ticket validation stays in the route because it raises
HTTP errors; announcements and activity rows stay in the route because
they are about one Gathering becoming visible, not about its fields.
"""

from __future__ import annotations

from typing import Any


#: Gathering settings, copied verbatim from the request by every
#: creation path. ``title`` is stripped on the way through — see
#: :func:`shared_event_fields`.
SHARED_EVENT_FIELDS: tuple[str, ...] = (
    "title",
    "description",
    "location_type",
    "location_url",
    "recording_url",
    "is_published",
    "is_public",
    "requires_booking",
    "capacity",
    "show_remaining_publicly",
    "notify_members",
    "booking_closes_at",
    "booking_note",
    "thumbnail_url",
    "gathering_type",
    "attendance_format",
    "venue_name",
    "venue_address",
    # The Public location. Absent from the bulk argument list until
    # FC-201, which is the defect this module exists to prevent.
    "venue_locality",
    "access_instructions",
    "booking_access_type",
    "booking_required_pathway_id",
)

#: Written from the validator's return values, never from the request.
TICKET_FIELDS: tuple[str, ...] = (
    "ticket_price_cents",
    "ticket_currency",
)

#: Decided by the route, per row.
PER_ROW_EVENT_FIELDS: tuple[str, ...] = (
    # Identity and provenance.
    "id",
    "space_id",
    "created_by_id",
    # The dates. A recurrence exists to vary these; a duplicate exists
    # to omit them.
    "starts_at",
    "ends_at",
    # Recurrence provenance — set only by the bulk path, by definition.
    "recurrence_series_id",
    "recurrence_label",
    "recurrence_index",
    "recurrence_total",
    # Semantic Series membership. Both paths set it, but only after
    # ``_validate_series_id_for_space`` has checked it belongs to this
    # Collective, so it is not a verbatim copy.
    "series_id",
    # Lifecycle. Left to the column default (``active``) on creation.
    "status",
    # What happened at one occurrence, not what was configured.
    "attendance_completed_at",
    "attendance_completed_by",
    # Server-side timestamps.
    "created_at",
    "updated_at",
)

#: Every mapped column on ``Event``, partitioned. The contract test
#: compares this against the model.
ALL_EVENT_FIELDS: frozenset[str] = frozenset(
    SHARED_EVENT_FIELDS + TICKET_FIELDS + PER_ROW_EVENT_FIELDS
)


def shared_event_fields(
    body: Any,
    *,
    ticket_price_cents: int | None,
    ticket_currency: str | None,
) -> dict[str, Any]:
    """Every Gathering setting a new ``Event`` row should inherit.

    Returns keyword arguments for ``Event(...)``, so a caller adds only
    the columns it owns per row::

        Event(
            id=str(uuid4()),
            space_id=space.id,
            created_by_id=current_user.id,
            starts_at=occurrence_start,
            ends_at=occurrence_end,
            series_id=resolved_series_id,
            **shared_event_fields(
                body,
                ticket_price_cents=price,
                ticket_currency=currency,
            ),
        )

    ``ticket_price_cents`` and ``ticket_currency`` are passed in rather
    than read off ``body`` so that a caller cannot accidentally persist
    an unvalidated price: the only values that reach a row are the ones
    the validator returned.
    """
    fields: dict[str, Any] = {
        name: getattr(body, name) for name in SHARED_EVENT_FIELDS
    }
    # The one value not copied as-is. Both paths stripped the title
    # before this module existed; keeping it here means neither has to
    # remember.
    fields["title"] = body.title.strip()
    fields["ticket_price_cents"] = ticket_price_cents
    fields["ticket_currency"] = ticket_currency
    return fields
