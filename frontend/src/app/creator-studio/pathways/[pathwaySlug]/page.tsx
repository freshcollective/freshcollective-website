import Link from 'next/link'
import { notFound } from 'next/navigation'
import { getActiveCreatorSpace, getCreatorMedia, getCreatorPathway, getCreatorSections, getCreatorSteps, serverFetch } from '@/lib/serverApi'
import type { CreatorMediaAsset, CreatorPathway, CreatorSection, CreatorStep } from '@/types/platform'
import CreatorPageContainer from '@/components/creator/CreatorPageContainer'
import EditPathwayClient from './EditPathwayClient'

interface Props {
  params: Promise<{ pathwaySlug: string }>
}

export default async function EditPathwayPage({ params }: Props) {
  const { pathwaySlug } = await params
  const activeSpace = await getActiveCreatorSpace()

  if (!activeSpace) {
    return (
      <CreatorPageContainer>
        <div className="rounded-2xl border border-dashed border-slate-200 bg-white p-10 text-center">
          <p className="mb-2 text-[16px] font-semibold text-navy-900">No collective selected.</p>
          <Link
            href="/creator-studio"
            className="inline-flex items-center rounded-xl px-5 py-2.5 text-[14px] font-semibold text-white transition-opacity hover:opacity-90"
            style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
          >
            Back to Dashboard
          </Link>
        </div>
      </CreatorPageContainer>
    )
  }

  const [pathway, steps, sections, mediaAssets]: [
    CreatorPathway | null, CreatorStep[], CreatorSection[], CreatorMediaAsset[],
  ] = await Promise.all([
    getCreatorPathway(activeSpace.slug, pathwaySlug),
    getCreatorSteps(activeSpace.slug, pathwaySlug),
    getCreatorSections(activeSpace.slug, pathwaySlug),
    getCreatorMedia(activeSpace.slug),
  ])

  if (!pathway) notFound()

  // Caretaker-releases entry point. Only surfaced when at least one
  // step uses the manual release rule; the manual-releases endpoint
  // returns an empty list otherwise, which we treat as "hide the link".
  let waitingCount: number | null = null
  const hasManualStep = steps.some((s) => s.release_type === 'manual')
  if (hasManualStep) {
    try {
      const res = await serverFetch(
        `/api/creator/spaces/${activeSpace.slug}/pathways/${pathwaySlug}/manual-releases`,
      )
      if (res.ok) {
        const entries: { waiting: unknown[] }[] = await res.json()
        waitingCount = entries.reduce((n, e) => n + (Array.isArray(e.waiting) ? e.waiting.length : 0), 0)
      }
    } catch {
      // Non-fatal — the link still appears without a count.
    }
  }

  return (
    <CreatorPageContainer>
      <div className="mb-8">
        <Link
          href="/creator-studio/pathways"
          className="mb-4 inline-flex items-center gap-1.5 text-[13px] text-black transition-colors hover:text-teal-700"
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
        {hasManualStep && (
          <Link
            href={`/creator-studio/pathways/${pathwaySlug}/manual-releases`}
            className="mt-4 inline-flex items-center gap-2 rounded-full px-4 py-1.5 text-[13px] font-medium transition-colors"
            style={{
              background: 'var(--fc-accent-soft, rgba(56,160,158,0.10))',
              color: 'var(--fc-accent, #0f766e)',
              border: '1px solid var(--fc-accent-line, rgba(56,160,158,0.20))',
            }}
          >
            <span>Manage caretaker releases →</span>
            {waitingCount !== null && waitingCount > 0 && (
              <span className="rounded-full bg-white/70 px-2 py-0.5 text-[11px] font-semibold" style={{ color: 'var(--fc-accent, #0f766e)' }}>
                {waitingCount === 1 ? '1 member waiting' : `${waitingCount} members waiting`}
              </span>
            )}
          </Link>
        )}
      </div>

      <EditPathwayClient
        pathway={pathway}
        steps={steps}
        sections={sections}
        spaceSlug={activeSpace.slug}
        mediaAssets={mediaAssets}
      />
    </CreatorPageContainer>
  )
}
