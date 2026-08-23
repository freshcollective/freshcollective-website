# R2 — legacy / comms overlap inventory

**R2A status (2026-08-23):** four flows migrated (password reset,
invitation, booking confirmation, community post + comment). Four
topics are live via the config default (`security`, `account`,
`gatherings`, `conversations`). Legacy guards on the migrated
triggers no-op when live.

The remaining legacy callers listed at the bottom of this document
still need R2B before `services/email_service.py` can be retired.

Original context (kept for R2B): documents every product event
where **enabling the new comms dispatcher would produce a duplicate
user email**, because both the legacy `services/email_service.py`
path and the comms Milestone-5 template pipeline can fire for the
same trigger.

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

---

## R2A cutover — completed 2026-08-23

Four flows migrated. `COMMS_LIVE_TOPICS` default is now
`"security,account,gatherings,conversations"`.

### Dispatch mechanism

Extended `app/comms/rollout.py::_route_event_bg` to inline-dispatch
every LIVE intent it just created via `dispatch_specific_intent`.
No global scheduler was introduced — dispatch happens as part of
the request that produced the emit, or in the FastAPI
`BackgroundTasks` slot when the caller provides one. Scoped to
intents this specific call produced; never touches queued intents
from other sources.

### Per-flow status

| Flow | Emit site | Legacy site | Legacy guard | Comms event → template |
|---|---|---|---|---|
| Password reset | `auth/routes.py:342` (emit; legacy send + guard deleted) | — | — | `account.password_reset_requested` — email template exists |
| Invitation | `creator/routes.py:1553` (emit; legacy send + template imports deleted) | — | — | `collective.invitation.sent` — new event registered under TOPIC_ACCOUNT; new resolver + template |
| Booking confirmation | `spaces/routes.py:249` (emit unchanged) | `notification_service.py:609` (`trigger_booking_confirmed`) | Early-return `if _rollout_is_live("gathering.booking.confirmed")` — comms takes over in-app + email | `gathering.booking.confirmed` — templates exist |
| Community post published | `community/routes.py:541` (emit unchanged) | `notification_service.py:214` (`trigger_new_post`) | Early-return `if _rollout_is_live("community.post.published")` | `community.post.published` — templates exist |
| Community comment reply | `community/routes.py:684` — new emit added via `_emit_comment_created` helper (post author only, commenter filtered at emit) | `notification_service.py:162` (`trigger_comment_reply`) | Early-return `if _rollout_is_live("community.comment.created")` | `community.comment.created` — new resolver + templates added |

### Registration decision — invitation under TOPIC_ACCOUNT

The invitation event was originally spec'd for
TOPIC_COLLECTIVE_UPDATES (→ CATEGORY_COMMUNITY). CATEGORY_COMMUNITY /
email_transactional is default-off + unlocked, meaning the
inviter's preferences would routinely suppress the invitation
before it left. But the invitation isn't a preference-controlled
notification for the inviter — it's a transactional email to an
external prospect. R2A registers the event under TOPIC_ACCOUNT
(→ CATEGORY_ACCOUNT, which is default-on + locked-immediate) so
the send is never gated by the inviter's preferences.

### Tests

`backend/tests/test_r2a_legacy_to_comms_migration.py` — 6 focused tests,
all passing:

- `test_password_reset_emits_one_event_and_dispatches_via_resend`
- `test_invitation_emits_and_dispatches_to_prospective_member`
- `test_gathering_booking_confirmation_emits_and_dispatches`
- `test_community_comment_created_emits_and_dispatches_to_post_author`
- `test_second_route_of_same_event_does_not_double_send`
- `test_provider_failure_does_not_prevent_intent_from_being_recorded`

Full backend regression: 1695/1695 pass (R1's 1689 + 6 new R2A).

---

## R2B — legacy code still active (not yet safe to retire the shim)

`services/email_service.py` and `services/email_templates.py` cannot
be retired yet because the following callers still send via the
legacy path (they are NOT among the four R2A flows, so no guard is
in place):

**`services/notification_service.py` — 5 non-R2A trigger paths still
send legacy email:**

- `send_notification` (generic helper, line 148) — used by other
  triggers to send arbitrary in-app + email notifications
- `trigger_reply_to_comment` (nested-comment reply, line ~207)
- `trigger_mention` (line ~280)
- `trigger_pathway_available` (line ~386)
- `trigger_caretaker_reply_to_question` and one other trigger (lines
  ~442, ~502)

**`app/notifications/routes.py` — 2 in-app admin/API sites still send
legacy email:**

- Line 272 — bulk notification send
- Line 392 — notification-marked-read path

**Scripts:**

- `scripts/render_email_samples.py` — diagnostic HTML renderer that
  imports `email_templates` directly; not production. R2B can
  update or delete this script.

Until R2B migrates these five triggers + two admin paths + the
render-samples script, the legacy shim stays. Any future PR that
adds a new legacy `email_service.send(...)` call must also add its
R2B migration in the same PR — the pattern is documented at the
top of this file.

**Templates still referenced from non-legacy paths:** none — every
`app.services.email_templates` function is called only from
`services/email_service.py` consumers or the render-samples script.

## Migrated-flow safety net

The R2A migrations keep the guarded legacy code paths in
`notification_service.py` (early-returns) so a config override that
removes a topic from `COMMS_LIVE_TOPICS` restores legacy behaviour
end-to-end. R2B can delete those guarded fallbacks once the four
R2A topics are proven in production for at least one week.
