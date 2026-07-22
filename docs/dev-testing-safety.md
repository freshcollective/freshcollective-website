# Dev Testing Safety

## Rule: automated browser testing must use a dedicated test account

Never log into a real user account — including your own admin account —
from an automated browser test, a Playwright verification run, a curl
integration check, or any other headless script. Never reset a real
user's password in order to make automated testing possible.

This rule exists because a headless-verification run silently reset the
project owner's admin password in the past. That kind of failure mode
must not be possible.

## The dedicated Playwright test account

Fixed identity (never varied without an explicit reason):

- **Email:** `playwright-test@fresh-collective.test`
- **Name:** Playwright Test User
- **Role:** `learner` (minimum permissions)

To create or update the password (interactive prompt — never on the CLI):

```bash
cd backend
.venv/bin/python3 scripts/seed_playwright_test_user.py
```

Guards in that script:

- Refuses non-localhost `DATABASE_URL`
- Refuses any email that doesn't contain `.test`, `example.com`, or
  `playwright`
- Refuses `role='admin'` outright
- Prompts for the password interactively via `getpass` — the plaintext
  is never accepted as a CLI argument and never appears in shell history
- Idempotent: re-running only updates the password on the existing test
  row; it never duplicates or cascades

## The password-reset script

`scripts/reset_dev_user_password.py` requires:

- `--email <address>` — no default, no hard-coded target
- `--confirm` — mandatory ack that this replaces the existing hash
- `--allow-admin` — additional gate when the target is an admin account
- `--create-if-missing` — required to fall back to INSERT when the email
  doesn't already exist (default behaviour is to exit 3, not create)

Passwords are prompted for interactively (twice, with confirmation) and
never accepted from `sys.argv`.

## What "test data" looks like

If a test flow needs representative content (memberships, creator
Collectives, Gatherings, drafts), seed it against the Playwright test
user only. When adding new seed helpers, follow the same pattern:

- Fixed, obviously-test email
- No admin role
- Idempotent upsert keyed on the test email
- Localhost-only DB guard

## When automated testing is not enough

If a feature genuinely requires an admin account's perspective to
verify, the correct response is to **stop and ask a human operator**,
not to reset an admin password. Automation cannot log in as an admin
without a human's involvement — that boundary is the point of the guard
rails.

## Session revocation gap (as of 2026-07-16)

Sessions are stateless JWTs. `POST /api/auth/me/change-password` updates
`password_hash` but does not invalidate previously-issued JWTs, which
remain valid until their `exp` (default `settings.jwt_expire_days`).
`POST /api/auth/logout` only deletes the cookie client-side. There is no
server-side revocation list, no `token_version`, and no
`password_updated_at` field on the user model.

**Consequence:** if a password is compromised or unexpectedly changed,
existing sessions on other devices continue to function until the JWT
naturally expires. This gap is documented rather than fixed here; the
remediation options (token_version bump on password change, deny-list
table, or dropping to opaque server-side sessions) are all separate
scoped work.
