import Link from 'next/link'
import { getSpace } from '@/lib/serverApi'
import PathwayCard from '@/components/spaces/PathwayCard'
import type { PathwaySummary } from '@/types/platform'

interface Props {
  params: Promise<{ slug: string }>
}

export default async function SpacePage({ params }: Props) {
  const { slug } = await params
  const space = await getSpace(slug)

  const activePathways: PathwaySummary[] = (space?.pathways ?? []).filter(
    (p: PathwaySummary) => p.status === 'active',
  )

  return (
    <div>
      <section className="mb-10">
        <h2 className="mb-1 font-serif text-2xl text-navy-900">Welcome</h2>
        {space?.description && (
          <p className="max-w-prose text-sm leading-relaxed text-slate-500">{space.description}</p>
        )}
      </section>

      {activePathways.length > 0 && (
        <section>
          <div className="mb-4 flex items-baseline justify-between">
            <h2 className="font-serif text-xl text-navy-900">Your Pathways</h2>
            <Link href={`/spaces/${slug}/pathways`} className="text-sm text-teal-600 hover:underline">
              View all
            </Link>
          </div>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {activePathways.map((pathway) => (
              <PathwayCard key={pathway.id} pathway={pathway} spaceSlug={slug} />
            ))}
          </div>
        </section>
      )}
    </div>
  )
}
