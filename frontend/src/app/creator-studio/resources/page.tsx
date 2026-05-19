import Link from 'next/link'
import { getActiveCreatorSpace, getCreatorPathways } from '@/lib/serverApi'
import type { CreatorPathway } from '@/types/platform'

const RESOURCE_TYPES = [
  { label: 'Prompts', desc: 'Reflection questions or journalling starters' },
  { label: 'Practices', desc: 'Exercises, rituals, or daily actions' },
  { label: 'Links', desc: 'Articles, tools, or external references' },
  { label: 'Files', desc: 'PDFs, worksheets, or downloadable guides' },
  { label: 'Video', desc: 'Short explainers or recorded content' },
]

export default async function ResourcesPage() {
  const primarySpace = await getActiveCreatorSpace()
  const pathways: CreatorPathway[] = primarySpace
    ? await getCreatorPathways(primarySpace.slug)
    : []

  return (
    <div className="w-full max-w-[1180px] px-8 py-8 md:px-10 md:py-10">

      <div className="mb-8">
        <p
          className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.16em]"
          style={{ color: '#38A09E' }}
        >
          Creator Studio
        </p>
        <h1 className="font-serif text-2xl text-navy-900 md:text-3xl">Resources</h1>
        <p className="mt-2 text-[15px] leading-relaxed" style={{ color: '#334155' }}>
          Add the tools, prompts, practices, links, and files that support the work.
        </p>
      </div>

      {/* What resources are */}
      <div className="mb-6 rounded-2xl border border-border bg-white p-6">
        <p className="mb-2 text-[17px] font-semibold text-navy-900">What resources are</p>
        <p className="mb-5 text-[14px] leading-relaxed text-slate-500">
          Resources are the tools, prompts, practices, links, and files that support the work
          between sessions. They attach to individual steps within your pathways.
        </p>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {RESOURCE_TYPES.map(({ label, desc }) => (
            <div key={label} className="flex items-start gap-2.5 rounded-xl p-3" style={{ background: '#F7F8FA' }}>
              <div
                className="mt-0.5 h-4 w-4 shrink-0 rounded"
                style={{ background: 'rgba(56,160,158,0.18)' }}
              />
              <div>
                <p className="text-[13px] font-medium text-navy-900">{label}</p>
                <p className="text-[12px] text-slate-500">{desc}</p>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* How to add */}
      <div className="mb-6 rounded-2xl border border-border bg-white px-6 py-5">
        <p className="text-[14px] leading-relaxed text-slate-500">
          To add a resource, open a step inside one of your pathways and use the resource
          manager on that step.
        </p>
      </div>

      {/* No collective yet */}
      {!primarySpace && (
        <div className="rounded-2xl border border-dashed border-slate-200 bg-white p-8 text-center">
          <p className="mb-2 text-[16px] font-semibold text-navy-900">No collective yet</p>
          <p className="mb-6 text-[14px] leading-relaxed text-slate-500">
            Set up your collective first, then build pathways and add resources to each step.
          </p>
          <Link
            href="/creator-studio/create"
            className="inline-flex items-center rounded-xl px-5 py-2.5 text-[14px] font-semibold text-white transition-opacity hover:opacity-90"
            style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
          >
            Create collective
          </Link>
        </div>
      )}

      {/* No pathways yet */}
      {primarySpace && pathways.length === 0 && (
        <div className="rounded-2xl border border-dashed border-slate-200 bg-white p-8 text-center">
          <p className="mb-2 text-[16px] font-semibold text-navy-900">No pathways yet.</p>
          <p className="mb-6 text-[14px] leading-relaxed text-slate-500">
            Create a pathway and add steps to it, then attach resources to each step.
          </p>
          <Link
            href={`/creator/spaces/${primarySpace.slug}/pathways`}
            className="inline-flex items-center rounded-xl px-5 py-2.5 text-[14px] font-semibold text-white transition-opacity hover:opacity-90"
            style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
          >
            Create pathway
          </Link>
        </div>
      )}

      {/* Pathway list for navigation */}
      {primarySpace && pathways.length > 0 && (
        <div>
          <p
            className="mb-3 text-[11px] font-semibold uppercase tracking-[0.16em]"
            style={{ color: '#38A09E' }}
          >
            Add resources via a pathway step
          </p>
          <div className="space-y-2.5">
            {pathways.map((pathway) => (
              <Link
                key={pathway.id}
                href={`/creator/spaces/${primarySpace.slug}/pathways/${pathway.slug}`}
                className="group flex items-center justify-between rounded-2xl border border-border bg-white px-5 py-4 transition-all hover:border-teal-200 hover:shadow-sm"
              >
                <div>
                  <p className="text-[14px] font-medium text-navy-900 transition-colors group-hover:text-teal-700">
                    {pathway.title}
                  </p>
                  <p className="mt-0.5 text-[13px] text-slate-500">
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
