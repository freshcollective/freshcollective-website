import { getRecentActivities } from '@/lib/serverApi'
import RecentMomentsRow from '@/components/activity/RecentMomentsRow'

/**
 * Recent Moments — the "across your world" perspective on the Your
 * World dashboard.
 *
 * Answers: "What's happened since I was last here?" Not an inbox, not
 * a bell, not a badge. A quiet strip of up to 5 recent moments that
 * lives above the collectives grid.
 *
 * Data source: ``GET /api/activities?limit=5`` — recipient scope is
 * the current caller, no collective filter (this is the global feed).
 */

export default async function RecentMomentsSection() {
  const { activities } = await getRecentActivities(5)

  return (
    <section className="mb-10">
      {/* Title uses the same font-family and colour as the other Your
          World section titles (Your Collectives, Elsewhere in the
          world, Collectives you created). A touch smaller than the
          major sections (20px vs 22–24px) so it reads as the
          calmer, lighter section per the brief without slipping
          back into eyebrow territory. */}
      <h2
        className="mb-4 font-serif text-[20px] leading-tight md:text-[22px]"
        style={{ color: '#0C1826' }}
      >
        Recent Moments
      </h2>

      {activities.length === 0 ? (
        <p
          className="text-[13.5px] italic leading-relaxed"
          style={{ color: 'rgba(12, 24, 38, 0.55)', fontFamily: 'Georgia, serif' }}
        >
          Nothing new to share yet — come back after your collectives stir.
        </p>
      ) : (
        <ul className="-ml-2 flex flex-col gap-0.5">
          {activities.map((a) => (
            <li key={a.id}>
              <RecentMomentsRow activity={a} variant="comfortable" />
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
