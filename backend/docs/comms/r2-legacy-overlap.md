# R2 — legacy / comms overlap inventory

Written at the end of R1 (2026-08-21). Documents every product event
where **enabling the new comms dispatcher today would produce a
duplicate user email**, because both the legacy
`services/email_service.py` path and the comms Milestone-5 template
pipeline can fire for the same trigger.

R1 is safe today because `COMMS_SHADOW=false` and
`COMMS_LIVE_TOPICS=""` (defaults). No comms emit produces a live
dispatchable intent — the legacy path is authoritative. R2 must
migrate each of these to the comms pipeline AND add the
`is_event_live(event_type) → return` guard in the legacy call site
before its corresponding topic can be added to `COMMS_LIVE_TOPICS`.

The pattern is documented in `app/comms/rollout.py:12-21`.

## Overlap table

| Domain event                        | Legacy send site                              | Comms template exists? | Comms event registered? | Would double-send if `COMMS_LIVE_TOPICS` contained | R2 action |
|---|---|---|---|---|---|
| Password reset                      | `app/auth/routes.py:358`                       | ✅ `account.password_reset_requested.email_transactional` | ✅ `account.password_reset_requested` | `security` / `account` | Guard legacy site; then promote `security` to live |
| Invitation (creator sends)          | `app/creator/routes.py:1592`                   | ❌ (no comms template) | ❌ (no comms event registered) | — | Add comms event + template + resolver first, then guard legacy site |
| Booking confirmation (Gathering)    | `app/services/notification_service.py:671`     | ✅ `gathering.booking.confirmed.email_transactional` | ✅ `gathering.booking.confirmed` | `gatherings` | Guard legacy site; verify comms emit is wired at the booking creation trigger, then promote `gatherings` to live |
| Community post reply                | `app/services/notification_service.py:148,197,270` | ✅ `community.post.published.email_transactional` | ✅ `community.post.published` | `conversations` | Guard legacy site; then promote `conversations` to live |
| Community comment                   | `app/services/notification_service.py:376,432` | ❌ | ✅ `community.comment.created` | — | Add comms template first; then migrate |
| Community mention                   | `app/services/notification_service.py:492`     | ❌ | ✅ `community.mention.created` | — | Add comms template first; then migrate |
| Notification digest / other         | `app/notifications/routes.py:272,392`          | Partial — depends on notification_type | Partial | Various | Case-by-case migration; likely folds into per-event topics |

## The two required halves of an R2 cutover per event

1. **Legacy site guard.** At the top of the legacy send function, before it calls `email_service.send(...)`:
    ```python
    from app.comms.rollout import is_event_live

    if is_event_live("account.password_reset_requested"):
        return
    ```
    Ensures the legacy path becomes a no-op once the comms pipeline is authoritative for the event.

2. **Comms emit site.** In the same domain function that runs the legacy send today, add:
    ```python
    from app.comms.events import emit
    from app.comms.rollout import schedule_routing_if_needed

    event = emit(db, event_type="account.password_reset_requested", ...)
    schedule_routing_if_needed(background_tasks, event, "account.password_reset_requested")
    ```
    `schedule_routing_if_needed` respects `COMMS_SHADOW` and `COMMS_LIVE_TOPICS`, so this addition is safe to land before the topic is promoted.

Both halves must land in the same PR per event. The order of the two lines in the same source file matters only for readability — they are idempotent with respect to each other.

## Promotion pre-conditions

Before any topic is added to `COMMS_LIVE_TOPICS`:

- 3 consecutive UTC days of 100% shadow parity per the admin parity report (`GET /api/admin/comms/shadow-parity?topic=…`).
- The legacy site's guard is in place.
- A comms template exists for every `(event_type, channel)` combination the legacy site was emitting.
- The dispatcher scheduler is running (either the in-process asyncio task or a Render cron hitting `/api/internal/comms/dispatch-due` — neither is enabled today).

## Topics that are safe to promote soonest (least legacy coupling)

- `direct_messages` — DM notifications may not have a legacy email path at all (needs one-line check at cutover time).
- `pathways` — legacy audit did not surface a `pathway.published` email caller. Verify at cutover.

## Deliberately NOT enabled by R1

- `COMMS_SHADOW` remains `false`.
- `COMMS_LIVE_TOPICS` remains `""`.
- The dispatcher runs in-process only for the R1 dev-only test-send endpoint via `dispatch_specific_intent`. No global scheduler is registered.
- `services/email_service.py` and `services/email_templates.py` remain in place, unchanged.

This document is the R2 starting point — do not delete it until R2 cutover is complete.
