import Link from 'next/link'
import { notFound } from 'next/navigation'
import { getCreatorPathways } from '@/lib/serverApi'
import type { CreatorPathway } from '@/types/platform'
import CreatePathwayButton from './CreatePathwayButton'

const STATUS_LABELS: Record<string, { label: string; color: string }> = {
  draft: { label: 'Draft', color: 'text-slate-400 bg-slate-50 border-slate-200' },
  active: { label: 'Active', color: 'text-teal-700 bg-teal-50 border-teal-200' },
  coming_soon: { label: 'Coming soon', color: 'text-amber-700 bg-amber-50 border-amber-200' },
  archived: { label: 'Archived', color: 'text-red-400 bg-red-50 border-red-200' },
}

export default async function CreatorPathwaysPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params
  const pathways: CreatorPathway[] = await getCreatorPathways(slug)

  return (
    <div>
      <div className="mb-8 flex items-start justify-between gap-4">
        <div>
          <div className="mb-2 h-px w-6 bg-gold-400" />
          <h1 className="font-serif text-2xl text-navy-900">Pathways</h1>
          <p className="mt-1 text-sm text-black">
            {pathways.length === 0 ? 'No pathways yet.' : `${pathways.length} pathway${pathways.length !== 1 ? 's' : ''}`}
          </p>
        </div>
        <CreatePathwayButton slug={slug} />
      </div>

      {pathways.length === 0 ? (
        <div className="rounded-xl border border-border bg-surface px-8 py-10 text-center">
          <p className="font-serif text-lg text-navy-700">No pathways yet</p>
          <p className="mt-1 text-sm text-black">Create your first pathway to start building the learning journey.</p>
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          {pathways.map((pathway, i) => {
            const st = STATUS_LABELS[pathway.status] ?? STATUS_LABELS.draft
            return (
              <div key={pathway.id} className="flex items-center gap-4 rounded-xl border border-border bg-surface px-5 py-4">
                <span className="w-5 shrink-0 text-center text-sm text-black">{i + 1}</span>
                <div className="min-w-0 flex-1">
                  <p className="truncate font-medium text-navy-900">{pathway.title}</p>
                  <p className="text-xs text-black">{pathway.step_count} step{pathway.step_count !== 1 ? 's' : ''}</p>
                </div>
                <span className={`shrink-0 rounded-full border px-2.5 py-0.5 text-xs font-medium ${st.color}`}>
                  {st.label}
                </span>
                <Link
                  href={`/creator/spaces/${slug}/pathways/${pathway.slug}`}
                  className="shrink-0 rounded-lg border border-navy-200 px-3 py-1.5 text-xs font-medium text-navy-700 hover:border-navy-400 hover:bg-navy-50"
                >
                  Edit
                </Link>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
