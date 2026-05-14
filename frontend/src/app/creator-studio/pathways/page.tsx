import Link from 'next/link'
import { getCreatorSpaces, getCreatorPathways } from '@/lib/serverApi'
import type { CreatorPathway } from '@/types/platform'

const STATUS_STYLE: Record<string, { bg: string; text: string }> = {
  active:      { bg: 'rgba(56,160,158,0.10)', text: '#38A09E' },
  draft:       { bg: 'rgba(0,0,0,0.06)',       text: '#94a3b8' },
  coming_soon: { bg: 'rgba(212,176,72,0.12)',  text: '#b08d2a' },
  archived:    { bg: 'rgba(0,0,0,0.06)',       text: '#cbd5e1' },
}

export default async function PathwaysPage() {
  const spaces = await getCreatorSpaces()
  const primarySpace = spaces[0] ?? null
  const pathways: CreatorPathway[] = primarySpace
    ? await getCreatorPathways(primarySpace.slug)
    : []

  return (
    <div className="max-w-4xl px-8 py-8 md:px-10 md:py-10">

      <div className="mb-8 flex items-start justify-between gap-4">
        <div>
          <p
            className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.16em]"
            style={{ color: '#38A09E' }}
          >
            Creator Studio
          </p>
          <h1 className="font-serif text-2xl text-navy-900 md:text-3xl">Pathways</h1>
        </div>
        {primarySpace && pathways.length > 0 && (
          <Link
            href={`/creator/spaces/${primarySpace.slug}/pathways`}
            className="shrink-0 rounded-lg border border-border bg-white px-4 py-2 text-[13px] font-medium text-slate-600 transition-colors hover:border-teal-200 hover:text-teal-700"
          >
            Manage in detail →
          </Link>
        )}
      </div>

      {/* No collective yet */}
      {!primarySpace && (
        <div className="rounded-xl border border-dashed border-slate-200 bg-white p-8 text-center">
          <p className="mb-1.5 font-serif text-base text-navy-900">No collective yet</p>
          <p className="mb-5 text-sm text-slate-400">
            Set up your collective first, then build pathways within it.
          </p>
          <Link
            href="/creator"
            className="inline-flex items-center rounded-lg px-5 py-2.5 text-sm font-semibold text-white transition-opacity hover:opacity-90"
            style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
          >
            Go to creator area
          </Link>
        </div>
      )}

      {/* Collective exists but no pathways */}
      {primarySpace && pathways.length === 0 && (
        <div className="rounded-xl border border-dashed border-slate-200 bg-white p-8 text-center">
          <p className="mb-1.5 font-serif text-base text-navy-900">No pathways yet.</p>
          <p className="mb-5 text-sm text-slate-400">
            Create your first guided journey so people have a clear way through your work.
          </p>
          <Link
            href={`/creator/spaces/${primarySpace.slug}/pathways`}
            className="inline-flex items-center rounded-lg px-5 py-2.5 text-sm font-semibold text-white transition-opacity hover:opacity-90"
            style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
          >
            Create pathway
          </Link>
        </div>
      )}

      {/* Pathway list */}
      {pathways.length > 0 && (
        <div className="space-y-3">
          {pathways.map((pathway) => {
            const style = STATUS_STYLE[pathway.status] ?? STATUS_STYLE.draft
            return (
              <Link
                key={pathway.id}
                href={`/creator/spaces/${primarySpace!.slug}/pathways/${pathway.slug}`}
                className="group flex items-center gap-4 rounded-xl border border-border bg-white p-5 transition-all hover:border-teal-200 hover:shadow-sm"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2.5">
                    <p className="font-medium text-navy-900 transition-colors group-hover:text-teal-700">
                      {pathway.title}
                    </p>
                    <span
                      className="rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide"
                      style={{ background: style.bg, color: style.text }}
                    >
                      {pathway.status.replace('_', ' ')}
                    </span>
                  </div>
                  {pathway.description && (
                    <p className="mt-1 truncate text-[12px] text-slate-400">
                      {pathway.description}
                    </p>
                  )}
                </div>
                <div className="shrink-0 text-right">
                  <p className="text-[13px] font-medium text-navy-900">{pathway.step_count}</p>
                  <p className="text-[11px] text-slate-400">steps</p>
                </div>
              </Link>
            )
          })}
        </div>
      )}

    </div>
  )
}
