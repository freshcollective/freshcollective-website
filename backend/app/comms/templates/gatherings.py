"""Templates for gathering category events."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.comms.categories import CHANNEL_EMAIL_TRANSACTIONAL, CHANNEL_IN_APP
from app.comms.models import CommunicationEvent
from app.comms.providers.base import RenderedPayload
from app.comms.routing.resolver import ResolvedRecipient
from app.comms.templates.base import render_email_shell
from app.comms.templates.editable import resolver_for
from app.comms.templates.registry import template_for


_EVENT_BOOKING_CONFIRMED = "gathering.booking.confirmed"


def _title(recipient: ResolvedRecipient) -> str:
    return (recipient.template_context.get("gathering_title") or "your gathering").strip()


@template_for(_EVENT_BOOKING_CONFIRMED, CHANNEL_IN_APP)
class BookingConfirmedInAppTemplate:
    key = "gathering.booking.confirmed.in_app"
    version = "v1"

    def render(
        self, db: Session, event: CommunicationEvent, recipient: ResolvedRecipient,
    ) -> RenderedPayload:
        return RenderedPayload(
            to="",
            subject=f"Booked: {_title(recipient)}",
            body_text="You're booked. We'll remind you closer to the time.",
            metadata={
                "notification_type": "booking_confirmed",
                "gathering_id": recipient.template_context.get("gathering_id"),
            },
        )


@template_for(_EVENT_BOOKING_CONFIRMED, CHANNEL_EMAIL_TRANSACTIONAL)
class BookingConfirmedEmailTemplate:
    key = "gathering.booking.confirmed.email_transactional"
    version = "v1"

    def render(
        self, db: Session, event: CommunicationEvent, recipient: ResolvedRecipient,
    ) -> RenderedPayload:
        title = _title(recipient)
        starts_at = recipient.template_context.get("gathering_starts_at") or "the scheduled time"
        collective = recipient.template_context.get("collective_name") or "the collective"
        ctx        = recipient.template_context
        added      = bool(ctx.get("added_by_creator"))
        url        = (ctx.get("gathering_url") or "").strip()

        r = resolver_for(db, self.key, {
            **ctx,
            "gathering_title": title,
            "collective_name": collective,
            "gathering_starts_at": starts_at,
        })
        subject = r.text("subject")
        # Never tell someone they reserved a place they did not reserve.
        opening = r.text(
            "body.added_by_creator" if added else "body.self_booked",
        )
        promise = r.text("body.reminder_promise")
        cta = r.text("cta_label")
        body_text = (
            f"{opening}\n\n"
            f"{promise}"
            + (f"\n\n{cta}:\n{url}" if url else "")
        )
        body_html = render_email_shell(
            db=db,
            preheader=opening,
            heading=r.text("heading"),
            body_paragraphs=[opening, promise],
            action=(cta, url) if url else None,
        )
        return RenderedPayload(
            to="",
            subject=subject,
            body_html=body_html,
            body_text=body_text,
            metadata={
                "notification_type": "booking_confirmed",
                "gathering_id": recipient.template_context.get("gathering_id"),
            },
        )


# ---------------------------------------------------------------------------
# gathering.cancelled — the creator cancelled the whole gathering
# ---------------------------------------------------------------------------
#
# Scope note. Only the creator-cancels-the-gathering case emails. The
# other three ways a booking can end are deliberately silent here:
#
#   * member cancels their own booking — they performed the action and
#     saw it confirmed in the UI;
#   * plan suspension releases future bookings — the
#     ``access.suspended`` email already discloses exactly this, and a
#     second email would duplicate it;
#   * admin access revocation — an operator-driven flow with its own
#     member communication.


_EVENT_CANCELLED = "gathering.cancelled"


@template_for(_EVENT_CANCELLED, CHANNEL_EMAIL_TRANSACTIONAL)
class GatheringCancelledEmailTemplate:
    key = "gathering.cancelled.email_transactional"
    version = "v1"

    def render(
        self, db: Session, event: CommunicationEvent, recipient: ResolvedRecipient,
    ) -> RenderedPayload:
        ctx        = recipient.template_context
        title      = (ctx.get("gathering_title") or "").strip() or "your gathering"
        collective = (ctx.get("collective_name") or "").strip()
        starts_at  = (ctx.get("gathering_starts_at") or "").strip()
        ticketed   = bool(ctx.get("was_ticketed"))


        r = resolver_for(db, self.key, {
            **ctx, "gathering_title": title, "collective_name": collective,
        })
        subject = r.text("subject")
        # Generated: names the gathering and who cancelled it.
        opening = (
            f"{title} has been cancelled"
            + (f" by {collective}." if collective else ".")
        )
        released = r.text("body.released")
        when = (
            f"It was due to take place {starts_at}. {released}"
            if starts_at else released
        )

        paragraphs = [opening, when]
        # Only say anything about money when a ticket was actually paid
        # for. Refunds are handled separately and confirmed by their own
        # email, so this promises nothing about timing or amount.
        ticket_note = r.text("body.ticketed")
        if ticketed:
            paragraphs.append(ticket_note)

        body_text = f"{opening}\n\n{when}" + (
            f"\n\n{ticket_note}" if ticketed else ""
        )
        body_html = render_email_shell(
            db=db,
            preheader=opening,
            heading=r.text("heading"),
            body_paragraphs=paragraphs,
        )
        return RenderedPayload(
            to="",
            subject=subject,
            body_html=body_html,
            body_text=body_text,
            metadata={"notification_type": "gathering_cancelled"},
        )


@template_for(_EVENT_CANCELLED, CHANNEL_IN_APP)
class GatheringCancelledInAppTemplate:
    key = "gathering.cancelled.in_app"
    version = "v1"

    def render(
        self, db: Session, event: CommunicationEvent, recipient: ResolvedRecipient,
    ) -> RenderedPayload:
        ctx   = recipient.template_context
        title = (ctx.get("gathering_title") or "").strip() or "your gathering"
        return RenderedPayload(
            to="",
            subject=f"Cancelled: {title}",
            body_text="Your place has been released.",
            metadata={"notification_type": "gathering_cancelled"},
        )


# ---------------------------------------------------------------------------
# gathering.reminder.24h — one reminder, roughly a day ahead
# ---------------------------------------------------------------------------
#
# Deliberately short. The member already chose to be there; this is a
# nudge, not a pitch. The registered ``gathering.reminder.1h`` event has
# no template on purpose — the MVP sends exactly one reminder.


_EVENT_REMINDER_24H = "gathering.reminder.24h"


@template_for(_EVENT_REMINDER_24H, CHANNEL_EMAIL_TRANSACTIONAL)
class GatheringReminder24hEmailTemplate:
    key = "gathering.reminder.24h.email_transactional"
    version = "v1"

    def render(
        self, db: Session, event: CommunicationEvent, recipient: ResolvedRecipient,
    ) -> RenderedPayload:
        ctx        = recipient.template_context
        title      = (ctx.get("gathering_title") or "").strip() or "your gathering"
        when       = (ctx.get("gathering_when") or "").strip()
        collective = (ctx.get("collective_name") or "").strip()
        url        = (ctx.get("gathering_url") or "").strip()

        r = resolver_for(db, self.key, {
            **ctx, "gathering_title": title, "collective_name": collective,
            "gathering_starts_at": when,
        })
        subject = r.text("subject")

        opening = (
            r.text("body.opening")
            if when else f"{title} is coming up tomorrow."
        )
        if collective:
            opening += f" It\u2019s part of {collective}."

        reassurance = r.text("body.reassurance")
        cta = r.text("cta_label")
        paragraphs = [opening, reassurance]

        body_text = (
            f"{opening}\n\n{reassurance}"
            + (f"\n\n{cta}:\n{url}" if url else "")
        )
        body_html = render_email_shell(
            db=db,
            preheader=opening,
            heading=r.text("heading"),
            body_paragraphs=paragraphs,
            action=(cta, url) if url else None,
        )
        return RenderedPayload(
            to="",
            subject=subject,
            body_html=body_html,
            body_text=body_text,
            metadata={"notification_type": "gathering_reminder_24h"},
        )


@template_for(_EVENT_REMINDER_24H, CHANNEL_IN_APP)
class GatheringReminder24hInAppTemplate:
    key = "gathering.reminder.24h.in_app"
    version = "v1"

    def render(
        self, db: Session, event: CommunicationEvent, recipient: ResolvedRecipient,
    ) -> RenderedPayload:
        ctx   = recipient.template_context
        title = (ctx.get("gathering_title") or "").strip() or "your gathering"
        when  = (ctx.get("gathering_when") or "").strip()
        return RenderedPayload(
            to="",
            subject=f"Tomorrow: {title}",
            body_text=(
                f"Coming up {when}." if when else "Coming up tomorrow."
            ),
            metadata={
                "notification_type": "gathering_reminder_24h",
                "url": ctx.get("gathering_url"),
            },
        )


# ---------------------------------------------------------------------------
# gathering.multi_booking.confirmed — one action, several gatherings
# ---------------------------------------------------------------------------
#
# Booking a Series, or a creator adding a member to a run of recurring
# sessions, creates one EventBooking per occurrence. Sending one email
# each would be a mailbox flood for a single click, so this is the one
# summary that stands in for all of them. The schedule extract is
# capped deliberately — enough to recognise what was booked, not a
# reproduction of the timetable.


_EVENT_MULTI_BOOKING = "gathering.multi_booking.confirmed"


@template_for(_EVENT_MULTI_BOOKING, CHANNEL_EMAIL_TRANSACTIONAL)
class MultiBookingConfirmedEmailTemplate:
    key = "gathering.multi_booking.confirmed.email_transactional"
    version = "v1"

    def render(
        self, db: Session, event: CommunicationEvent, recipient: ResolvedRecipient,
    ) -> RenderedPayload:
        ctx        = recipient.template_context
        collective = (ctx.get("collective_name") or "").strip()
        series     = (ctx.get("series_title") or "").strip()
        count      = int(ctx.get("session_count") or 0)
        first      = (ctx.get("first_starts_at") or "").strip()
        last       = (ctx.get("last_starts_at") or "").strip()
        preview    = ctx.get("schedule_preview") or []
        url        = (ctx.get("cta_url") or "").strip()
        added      = bool(ctx.get("added_by_creator"))

        what = series or "a run of gatherings"
        sessions = "session" if count == 1 else "sessions"

        subject = (
            f"Booked: {series}" if series
            else f"Booked: {count} {sessions}"
        )

        opening = (
            f"You've been added to {what}"
            if added else
            f"You're booked for {what}"
        )
        if collective:
            opening += f" in {collective}"
        opening += f" — {count} {sessions} in total."

        # A date range only says something when there is more than one.
        if count > 1 and first and last:
            span = f"Running from {first} through to {last}."
        elif first:
            span = f"Starting {first}."
        else:
            span = ""

        paragraphs = [opening, span]

        if preview:
            shown = [
                f"{item.get('title', '')} — {item.get('when', '')}".strip(" —")
                for item in preview[:3]
            ]
            paragraphs.append("  •  ".join(s for s in shown if s))
            if count > len(preview):
                remaining = count - len(preview)
                paragraphs.append(
                    f"…and {remaining} more "
                    f"{'session' if remaining == 1 else 'sessions'}."
                )

        r = resolver_for(db, self.key, ctx)
        paragraphs.append(r.text("body.closing"))

        body_text = "\n\n".join(p for p in paragraphs if p) + (
            f"\n\n{r.text('cta_label')}:\n{url}" if url else ""
        )
        body_html = render_email_shell(
            db=db,
            preheader=opening,
            heading=subject,
            body_paragraphs=paragraphs,
            action=(r.text("cta_label"), url) if url else None,
        )
        return RenderedPayload(
            to="",
            subject=subject,
            body_html=body_html,
            body_text=body_text,
            metadata={"notification_type": "multi_booking_confirmed"},
        )


@template_for(_EVENT_MULTI_BOOKING, CHANNEL_IN_APP)
class MultiBookingConfirmedInAppTemplate:
    key = "gathering.multi_booking.confirmed.in_app"
    version = "v1"

    def render(
        self, db: Session, event: CommunicationEvent, recipient: ResolvedRecipient,
    ) -> RenderedPayload:
        ctx    = recipient.template_context
        series = (ctx.get("series_title") or "").strip()
        count  = int(ctx.get("session_count") or 0)
        sessions = "session" if count == 1 else "sessions"
        return RenderedPayload(
            to="",
            subject=(
                f"Booked: {series}" if series else f"Booked: {count} {sessions}"
            ),
            body_text=f"{count} {sessions} added to your schedule.",
            metadata={
                "notification_type": "multi_booking_confirmed",
                "url": ctx.get("cta_url"),
            },
        )
