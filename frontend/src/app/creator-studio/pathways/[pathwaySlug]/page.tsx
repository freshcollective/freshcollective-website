import Link from 'next/link'
import { notFound } from 'next/navigation'
import { getActiveCreatorSpace, getCreatorMedia, getCreatorPathway, getCreatorSections, getCreatorSteps } from '@/lib/serverApi'
import type { CreatorMediaAsset, CreatorPathway, CreatorSection, CreatorStep } from '@/types/platform'
import CreatorPageContainer from '@/components/creator/CreatorPageContainer'
import PathwayContentClient from './PathwayContentClient'
import PathwayHeader from './PathwayHeader'

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

  const hasManualStep = steps.some((s) => s.release_type === 'manual')

  return (
    <CreatorPageContainer>
      <PathwayHeader
        active="content"
        spaceName={activeSpace.name}
        pathway={pathway}
        showManualReleases={hasManualStep}
      />
      <PathwayContentClient
        pathway={pathway}
        steps={steps}
        sections={sections}
        spaceSlug={activeSpace.slug}
        mediaAssets={mediaAssets}
      />
    </CreatorPageContainer>
  )
}
