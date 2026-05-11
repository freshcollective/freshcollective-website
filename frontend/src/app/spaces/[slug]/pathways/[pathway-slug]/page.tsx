import { notFound } from 'next/navigation'
import Link from 'next/link'
import { getPathway } from '@/lib/serverApi'
import type { PathwaySummary } from '@/types/platform'

interface Props {
  params: Promise<{ slug: string; 'pathway-slug': string }>
}

export default async function PathwayDetailPage({ params }: Props) {
  const { slug, 'pathway-slug': pathwaySlug } = await params
  const pathway: PathwaySummary | null = await getPathway(slug, pathwaySlug)

  if (!pathway) notFound()

  return (
    <div className="max-w-2xl">
      <Link
        href={`/spaces/${slug}/pathways`}
        className="mb-6 inline-block text-sm text-slate-500 hover:text-navy-700"
      >
        ← All Pathways
      </Link>
      <div className="mb-2 h-px w-6 bg-gold-500" />
      <h2 className="mb-2 font-serif text-3xl text-navy-900">{pathway.title}</h2>
      {pathway.description && (
        <p className="mb-8 text-sm leading-relaxed text-slate-500">{pathway.description}</p>
      )}
      <div className="rounded-xl border border-border bg-surface p-6 text-sm text-slate-500">
        Steps for this pathway are coming soon.
      </div>
    </div>
  )
}
