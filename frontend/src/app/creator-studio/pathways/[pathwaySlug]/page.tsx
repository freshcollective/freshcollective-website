import Link from 'next/link'
import { notFound } from 'next/navigation'
import { getActiveCreatorSpace, getCreatorPathway, getCreatorSections, getCreatorSteps } from '@/lib/serverApi'
import type { CreatorPathway, CreatorSection, CreatorStep } from '@/types/platform'
import EditPathwayClient from './EditPathwayClient'

interface Props {
  params: Promise<{ pathwaySlug: string }>
}

export default async function EditPathwayPage({ params }: Props) {
  const { pathwaySlug } = await params
  const activeSpace = await getActiveCreatorSpace()

  if (!activeSpace) {
    return (
      <div className="max-w-2xl px-8 py-8 md:px-10 md:py-10">
        <div className="rounded-2xl border border-dashed border-slate-200 bg-white p-10 text-center">
          <p className="mb-2 text-[16px] font-semibold text-navy-900">No collective selected.</p>
          <Link
            href="/creator-studio"
            className="inline-flex items-center rounded-xl px-5 py-2.5 text-[14px] font-semibold text-white transition-opacity hover:opacity-90"
            style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
          >
            Back to Studio Home
          </Link>
        </div>
      </div>
    )
  }

  const [pathway, steps, sections]: [CreatorPathway | null, CreatorStep[], CreatorSection[]] = await Promise.all([
    getCreatorPathway(activeSpace.slug, pathwaySlug),
    getCreatorSteps(activeSpace.slug, pathwaySlug),
    getCreatorSections(activeSpace.slug, pathwaySlug),
  ])

  if (!pathway) notFound()

  return (
    <div className="max-w-2xl px-8 py-8 md:px-10 md:py-10">
      <div className="mb-8">
        <Link
          href="/creator-studio/pathways"
          className="mb-4 inline-flex items-center gap-1.5 text-[13px] text-slate-500 transition-colors hover:text-teal-700"
        >
          ← Back to Pathways
        </Link>
        <p
          className="mt-4 text-[11px] font-semibold uppercase tracking-[0.16em]"
          style={{ color: '#38A09E' }}
        >
          {activeSpace.name}
        </p>
        <h1 className="mt-1.5 font-serif text-2xl text-navy-900 md:text-3xl">
          {pathway.title}
        </h1>
      </div>

      <EditPathwayClient
        pathway={pathway}
        steps={steps}
        sections={sections}
        spaceSlug={activeSpace.slug}
      />
    </div>
  )
}
