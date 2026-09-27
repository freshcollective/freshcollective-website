/**
 * The Collective's timezone, and the one fallback for when it is absent.
 *
 * Every Gathering timestamp is stored naive-UTC and belongs to a
 * Collective, so *something* has to say which zone to render it in.
 * ``Space.timezone`` is that something (backend default:
 * ``app/spaces/schemas.py``), but a handful of payloads still reach the
 * UI without it, and each call site was writing its own
 * ``?? 'Australia/Melbourne'``. Ten copies of a default is nine chances
 * to change it in nine places.
 *
 * Deliberately NOT in ``lib/dateTime``. That module opens with a
 * standing instruction — "timezone should come from collective settings
 * passed at call sites — do not re-add a hardcoded constant here" — and
 * it is right: a formatter that can silently default is a formatter that
 * hides a missing timezone instead of surfacing it. The formatters keep
 * demanding an explicit zone; this module is where a caller goes to
 * resolve one.
 */

/** Platform default when a Collective has not set its own. */
export const DEFAULT_COLLECTIVE_TIMEZONE = 'Australia/Melbourne'

/** The Collective's timezone, or the platform default. */
export function collectiveTimezone(
  space: { timezone?: string | null } | null | undefined,
): string {
  return space?.timezone?.trim() || DEFAULT_COLLECTIVE_TIMEZONE
}
