import { getSpacePathways } from '@/lib/serverApi'
import PathwayCard from '@/components/spaces/PathwayCard'
import type { PathwaySummary } from '@/types/platform'

interface Props {
  params: Promise<{ slug: string }>
}

export default async function SpacePathwaysPage({ params }: Props) {
  const { slug } = await params
  const pathways: PathwaySummary[] = await getSpacePathways(slug)

  return (
    <div>
      <div className="mb-2 h-[2px] w-8 rounded-full bg-teal-400" />
      <h2 className="mb-2 font-serif text-2xl text-navy-900">Pathways</h2>
      <p className="mb-6 text-[14px] leading-relaxed text-slate-500">
        Structured journeys to guide your growth and reflection.
      </p>
      {pathways.length === 0 ? (
        <p className="text-sm text-slate-500">No pathways available yet.</p>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {pathways.map((pathway) => (
            <PathwayCard key={pathway.id} pathway={pathway} spaceSlug={slug} />
          ))}
        </div>
      )}
    </div>
  )
}
