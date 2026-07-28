import { getMyMemberships, getSpaceNotificationPrefs } from '@/lib/serverApi'
import type { NotificationPrefs, SpaceMembership } from '@/types/platform'
import StayConnectedClient from './StayConnectedClient'

/**
 * Stay Connected — the member's communication preferences across
 * every collective they belong to.
 *
 * This is a UI relocation of the old per-collective Notifications
 * modal. Nothing about the underlying data model or delivery logic
 * changes:
 *
 *   - The existing ``SpaceMemberNotificationPrefs`` row is reused
 *     per (user, space); no new backend model, no defaults migration.
 *   - Reads via the existing ``GET /api/spaces/{slug}/notification-settings``.
 *   - Writes via the existing ``PATCH /api/spaces/{slug}/notification-settings``.
 *
 * Digest fields — ``weekly_digest_email`` and ``daily_digest_email``
 * are stored on the backend but no delivery job exists for them
 * today (grep for "digest" in backend/app returns only the model
 * columns, schema + route serialisation, and forward-looking
 * comments in the Activity Engine). The controls are therefore
 * OMITTED from this page rather than shown as disabled/unavailable
 * rows — the calm-page principle prefers absence over greyed noise,
 * and stored values are preserved untouched so re-adding the
 * controls when delivery ships is a UI change only.
 */

export default async function StayConnectedPage() {
  // Enumerate the caller's collectives, then load prefs for each in
  // parallel. Two per-request round-trips at worst (memberships → N
  // prefs) rather than N+1, without introducing a new backend batch
  // endpoint per the task's "no new abstraction" constraint.
  const memberships = (await getMyMemberships()) as SpaceMembership[]

  const collectives: {
    membership: SpaceMembership
    prefs: NotificationPrefs | null
  }[] = await Promise.all(
    memberships.map(async (m) => ({
      membership: m,
      prefs: await getSpaceNotificationPrefs(m.space_slug),
    })),
  )

  return (
    <div>
      <div className="mb-8">
        <h2 className="mb-1 font-serif text-xl text-navy-900">Stay Connected</h2>
        <p className="text-sm text-black">
          Choose how you&rsquo;d like to stay connected with each collective you belong to.
        </p>
      </div>

      <StayConnectedClient collectives={collectives} />
    </div>
  )
}
