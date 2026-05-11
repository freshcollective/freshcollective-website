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
      <h2 className="mb-6 font-serif text-2xl text-navy-900">Pathways</h2>
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
