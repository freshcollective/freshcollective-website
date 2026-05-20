import { getSpacePathways } from '@/lib/serverApi'
import PathwayCard from '@/components/spaces/PathwayCard'
import type { PathwaySummary } from '@/types/platform'

interface Props {
  params: Promise<{ slug: string }>
}

export default async function SpacePathwaysPage({ params }: Props) {
  const { slug } = await params
  const pathways: PathwaySummary[] = await getSpacePathways(slug)

  // Only show pathways the backend returned as active; coming_soon gets its own section.
  // Draft and archived are already excluded by the API for regular members.
  const active = pathways.filter((p) => p.status === 'active')
  const soon = pathways.filter((p) => p.status === 'coming_soon')

  return (
    <div>
      {/* Intro card */}
      <div
        className="mb-8 overflow-hidden rounded-2xl px-7 py-7"
        style={{
          background: '#071824',
          border: '1px solid rgba(66,199,198,0.10)',
          boxShadow: '0 4px 24px rgba(7,24,36,0.18), 0 1px 4px rgba(0,0,0,0.10)',
        }}
      >
        <div
          className="mb-3 h-[2px] w-8 rounded-full"
          style={{ background: 'linear-gradient(90deg, #55D7D2 0%, transparent 100%)' }}
        />
        <h2 className="mb-2 leading-snug">
          <span
            className="inline-block text-2xl font-semibold"
            style={{
              background: 'linear-gradient(90deg, #55D7D2 0%, #D9FFFD 50%, #FFFFFF 100%)',
              WebkitBackgroundClip: 'text',
              WebkitTextFillColor: 'transparent',
              backgroundClip: 'text',
            }}
          >
            Pathways
          </span>
        </h2>
        <p className="text-[14px] leading-relaxed" style={{ color: 'rgba(255,255,255,0.60)' }}>
          Structured journeys to guide your growth and reflection.
        </p>
      </div>

      {active.length === 0 && soon.length === 0 ? (
        <div className="rounded-2xl border border-teal-100 bg-white px-7 py-12 text-center">
          <p className="font-serif text-lg text-navy-800">No pathways yet.</p>
          <p className="mt-1.5 text-sm text-slate-400">
            Pathways will appear here once they are published.
          </p>
        </div>
      ) : (
        <>
          {active.length > 0 && (
            <div className="mb-10 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
              {active.map((pathway) => (
                <PathwayCard key={pathway.id} pathway={pathway} spaceSlug={slug} />
              ))}
            </div>
          )}

          {soon.length > 0 && (
            <div>
              <p className="mb-4 text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">
                Coming Soon
              </p>
              <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
                {soon.map((pathway) => (
                  <PathwayCard key={pathway.id} pathway={pathway} spaceSlug={slug} />
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
