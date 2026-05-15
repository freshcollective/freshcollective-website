import { getSpacePathways } from '@/lib/serverApi'
import PathwayCard from '@/components/spaces/PathwayCard'
import type { PathwaySummary } from '@/types/platform'

interface Props {
  params: Promise<{ slug: string }>
}

export default async function SpacePathwaysPage({ params }: Props) {
  const { slug } = await params
  const pathways: PathwaySummary[] = await getSpacePathways(slug)

  const active = pathways.filter((p) => p.status !== 'coming_soon')
  const soon = pathways.filter((p) => p.status === 'coming_soon')

  return (
    <div>
      <div className="mb-6">
        <div className="mb-2 h-[2px] w-8 rounded-full bg-teal-400" />
        <h2 className="mb-1 font-serif text-2xl text-navy-900">Pathways</h2>
        <p className="text-[14px] leading-relaxed text-slate-500">
          Structured journeys to guide your growth and reflection.
        </p>
      </div>

      {pathways.length === 0 ? (
        <div className="rounded-2xl border border-teal-100 bg-white px-7 py-12 text-center">
          <p className="font-serif text-lg text-navy-800">Pathways coming soon.</p>
          <p className="mt-1.5 text-sm text-slate-400">
            Your pathways will appear here once they are ready.
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
