import { getRecentActivities } from '@/lib/serverApi'
import RecentMomentsRow from '@/components/activity/RecentMomentsRow'

/**
 * Recent Moments (in this place) — the collective-scoped panel that
 * lives inside ``CollectiveSidebarPanel``, above the Important
 * content.
 *
 * Deliberately paired with — but distinct from — the Your World
 * dashboard version:
 *   - Dashboard "Recent Moments" = across your world (all collectives)
 *   - Sidebar "Recent Moments"   = in this place (this collective)
 *
 * Data source: ``GET /api/activities?limit=3&collective_id=<space_id>``
 * — recipient scope stays the caller; the collective filter narrows
 * the same feed used on Your World.
 */

interface Props {
  spaceId: string
  className?: string
}

export default async function CollectiveRecentMomentsPanel({ spaceId, className }: Props) {
  const { activities } = await getRecentActivities(3, spaceId)

  return (
    <div className={className}>
      <p
        className="mb-2 text-[11px] font-semibold uppercase tracking-[0.16em]"
        style={{ color: 'var(--fc-accent, #0f766e)' }}
      >
        Recent Moments
      </p>

      {activities.length === 0 ? (
        <p className="text-[12px] leading-relaxed text-black italic">
          Nothing new in this place yet.
        </p>
      ) : (
        <ul className="-ml-2 flex flex-col gap-0.5">
          {activities.map((a) => (
            <li key={a.id}>
              <RecentMomentsRow activity={a} variant="compact" />
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
