import Link from 'next/link'
import { getCreatorSpaces, getCreatorPathways } from '@/lib/serverApi'
import type { CreatorPathway } from '@/types/platform'

export default async function ResourcesPage() {
  const spaces = await getCreatorSpaces()
  const primarySpace = spaces[0] ?? null
  const pathways: CreatorPathway[] = primarySpace
    ? await getCreatorPathways(primarySpace.slug)
    : []

  return (
    <div className="max-w-3xl px-8 py-8 md:px-10 md:py-10">

      <div className="mb-8">
        <p
          className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.16em]"
          style={{ color: '#38A09E' }}
        >
          Creator Studio
        </p>
        <h1 className="font-serif text-2xl text-navy-900 md:text-3xl">Resources</h1>
      </div>

      <div className="mb-6 rounded-xl border border-border bg-white p-6">
        <p className="mb-2 font-serif text-base text-navy-900">Resources live on steps</p>
        <p className="text-[13.5px] leading-relaxed text-slate-400">
          Files, links, and downloadable resources are attached to individual steps within your
          pathways. Open a step in the pathway editor to add or manage its resources.
        </p>
      </div>

      {!primarySpace && (
        <div className="rounded-xl border border-dashed border-slate-200 bg-white p-8 text-center">
          <p className="mb-4 text-sm text-slate-400">
            Set up your space first to manage resources.
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

      {primarySpace && pathways.length === 0 && (
        <div className="rounded-xl border border-dashed border-slate-200 bg-white p-8 text-center">
          <p className="mb-4 text-sm text-slate-400">
            Create a pathway first, then add resources to its steps.
          </p>
          <Link
            href={`/creator/spaces/${primarySpace.slug}/pathways`}
            className="inline-flex items-center rounded-lg px-5 py-2.5 text-sm font-semibold text-white transition-opacity hover:opacity-90"
            style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
          >
            Go to pathways
          </Link>
        </div>
      )}

      {primarySpace && pathways.length > 0 && (
        <div>
          <p className="mb-3 text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">
            Your pathways
          </p>
          <div className="space-y-2.5">
            {pathways.map((pathway) => (
              <Link
                key={pathway.id}
                href={`/creator/spaces/${primarySpace.slug}/pathways/${pathway.slug}`}
                className="group flex items-center justify-between rounded-xl border border-border bg-white px-5 py-4 transition-all hover:border-teal-200 hover:shadow-sm"
              >
                <div>
                  <p className="text-[14px] font-medium text-navy-900 transition-colors group-hover:text-teal-700">
                    {pathway.title}
                  </p>
                  <p className="mt-0.5 text-[12px] text-slate-400">
                    {pathway.step_count} step{pathway.step_count !== 1 ? 's' : ''}
                  </p>
                </div>
                <span className="text-slate-300 transition-colors group-hover:text-teal-500">
                  →
                </span>
              </Link>
            ))}
          </div>
        </div>
      )}

    </div>
  )
}
