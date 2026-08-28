# Resend inbound webhooks (Milestone 6, R4)

## Purpose

The receiver correlates Resend's Svix-signed delivery-status webhooks
back to Fresh Collective's `CommunicationDelivery` rows so we know
which sends landed, bounced, or drew a spam complaint. It does not
manage subscriptions or replace consent surfaces — consent remains
a member-side action captured through the platform's own UI (see
`webhooks.py` architecture note).

## Endpoint

```
POST /api/webhooks/comms/resend
```

Resend must be configured to POST to this URL. Sits under the same
public router as other webhook receivers; no auth beyond Svix
signature verification.

## Configuration

| Env var                 | Purpose                                            |
| ----------------------- | -------------------------------------------------- |
| `RESEND_API_KEY`        | Enables outbound sending. Independent of inbound.  |
| `RESEND_WEBHOOK_SECRET` | Svix signing secret. Required to accept webhooks. |

If `RESEND_API_KEY` is set but `RESEND_WEBHOOK_SECRET` is not, the
FastAPI lifespan handler logs a single WARNING at startup:
outbound email still works, but every inbound webhook will be
rejected with 401 until the secret is provisioned.

## Events subscribed

R4 scope is deliberately narrow — only three event types drive state:

| Resend event      | FC event type | Effect                                                                                   |
| ----------------- | ------------- | ---------------------------------------------------------------------------------------- |
| `email.delivered` | `delivered`   | Intent → `delivered`; delivery `terminal_outcome=delivered`                              |
| `email.bounced`   | `bounced`     | Intent → `bounced`; delivery `terminal_outcome=bounced` + `bounce_class`; suppress if hard |
| `email.complained`| `complained`  | Intent → `complained`; delivery `terminal_outcome=complained`; suppress                  |

Every other verified event (`opened`, `clicked`, `sent`,
`unsubscribed`, `delivery_delayed`, anything future Resend adds) is
logged at INFO and dropped. No audit row is written, nothing is
mutated. If we later want opens/clicks in the pipeline, subscribing
in the Resend dashboard alone is not enough — the receiver's
`_R4_IN_SCOPE_EVENT_TYPES` set has to grow too.

Only the three events above need to be enabled in the Resend
dashboard's webhook subscription.

## Idempotency

Each Resend payload carries a Svix `svix-id`. The
`communication_webhook_events` table has a partial UNIQUE index on
`(provider_key, provider_event_id) WHERE provider_event_id IS NOT NULL`
so a replayed `svix-id` collides on insert and is skipped without
mutating state a second time. `CommunicationDelivery` uses the
matching partial UNIQUE index on `(provider_key, provider_message_id)
WHERE provider_message_id IS NOT NULL` (migration 099) so message-id
lookups from the mapping step are a natural-key resolution.

## Failure modes and HTTP status codes

| Situation                                        | HTTP | Body                                    | Audit row? |
| ------------------------------------------------ | ---- | --------------------------------------- | ---------- |
| Missing / malformed Svix headers                 | 400  | `{"error": "missing_signature_headers"}` | No         |
| Malformed JSON body (signature valid)            | 400  | `{"error": "malformed_payload"}`         | No         |
| Signature verification failed                    | 401  | `{"error": "invalid_signature"}`         | No         |
| Provider key not registered                      | 404  | Detail string                           | No         |
| Verified + in-scope + delivery matched           | 200  | ReceiverOutcome JSON                    | Yes (processed) |
| Verified + in-scope + unknown provider_message_id | 200 | ReceiverOutcome JSON                    | Yes (process_error) |
| Verified + out-of-scope event type               | 200  | ReceiverOutcome JSON (0 processed)      | No         |

The ledger is trusted history — untrusted payloads never touch it.

## Suppression side effects

Hard bounces and complaints add the recipient email to
`comms_suppressions` (reason `bounced` / `complained`). Soft bounces
do not suppress — they may recover on the next attempt.
Suppressed addresses are refused by the delivery worker before it
calls the provider again.

## Local verification

Resend can fire a test event from its dashboard's webhook editor. Any
Svix-format signed payload works; there's no Resend-only dependency
in `verify_svix_signature`, so a manually crafted payload signed with
`sign_svix_payload()` (in `webhooks.py`) also verifies. Tests in
`backend/tests/test_comms_webhooks.py` demonstrate the header shape.

## Rotating the signing secret

1. In the Resend dashboard, rotate the webhook signing secret.
2. Update `RESEND_WEBHOOK_SECRET` in the backend environment.
3. Restart the backend so the new value is loaded.
4. Fire a test event from the dashboard and confirm the receiver
   returns 200 (check the audit table for the new row).

There is no in-app rotation flow — the secret is loaded once at
process start via pydantic-settings and cached in `settings`.
