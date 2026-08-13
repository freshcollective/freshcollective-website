import Link from 'next/link'
import { notFound } from 'next/navigation'
import { getActiveCreatorSpace, getCreatorBilling, getCreatorMedia, getCreatorOfferPages, getCreatorPathway, getCreatorSections, getCreatorSpace, getCreatorSteps } from '@/lib/serverApi'
import type { CreatorMediaAsset, CreatorOfferPageSummary, CreatorPathway, CreatorSection, CreatorSpaceDetail, CreatorStep } from '@/types/platform'
import CreatorPageContainer from '@/components/creator/CreatorPageContainer'
import PathwayHeader from '../PathwayHeader'
import PathwayOfferPagesShortcut from '../PathwayOfferPagesShortcut'
import PathwaySettingsClient from '../PathwaySettingsClient'

interface Props {
  params: Promise<{ pathwaySlug: string }>
}

export default async function PathwaySettingsPage({ params }: Props) {
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

  // Settings does not use the steps list itself, but we still need to know
  // whether the Manual releases tab should be surfaced in the shared header.
  //
  // ``offers`` + ``billing`` are best-effort — the shortcut degrades to
  // its "no offers" or "not on your plan" state on failure rather than
  // 500ing the whole settings page.
  const [pathway, steps, sections, mediaAssets, spaceDetail, offers, billing]: [
    CreatorPathway | null, CreatorStep[], CreatorSection[], CreatorMediaAsset[], CreatorSpaceDetail | null,
    CreatorOfferPageSummary[],
    Awaited<ReturnType<typeof getCreatorBilling>>,
  ] = await Promise.all([
    getCreatorPathway(activeSpace.slug, pathwaySlug),
    getCreatorSteps(activeSpace.slug, pathwaySlug),
    getCreatorSections(activeSpace.slug, pathwaySlug),
    getCreatorMedia(activeSpace.slug),
    getCreatorSpace(activeSpace.slug) as Promise<CreatorSpaceDetail | null>,
    getCreatorOfferPages(activeSpace.slug).catch(() => [] as CreatorOfferPageSummary[]),
    getCreatorBilling().catch(() => null),
  ])

  if (!pathway) notFound()

  const hasManualStep = steps.some((s) => s.release_type === 'manual')
  const paidOffersEnabled = !!(
    billing?.is_platform_owner
    || billing?.current_plan?.paid_offers_enabled
  )

  return (
    <CreatorPageContainer>
      {/* Note: no standalone back link here — PathwayHeader already
          passes ``backLink`` to CollectiveArtworkHeader, so rendering
          a second CreatorBackLink duplicated "← Back to Pathways" in
          browser review. */}
      <PathwayHeader
        active="settings"
        spaceName={activeSpace.name}
        pathway={pathway}
        showManualReleases={hasManualStep}
        location={spaceDetail?.location ?? null}
        coverImageUrl={spaceDetail?.cover_image_url ?? null}
        steps={steps}
        sections={sections}
      />
      <div className="mb-6">
        <PathwayOfferPagesShortcut
          pathwayId={pathway.id}
          pathwayTitle={pathway.title}
          offers={offers}
          paidOffersEnabled={paidOffersEnabled}
        />
      </div>
      <PathwaySettingsClient
        pathway={pathway}
        spaceSlug={activeSpace.slug}
        mediaAssets={mediaAssets}
      />
    </CreatorPageContainer>
  )
}
