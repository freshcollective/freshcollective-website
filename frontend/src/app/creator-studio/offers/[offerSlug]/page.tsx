import { notFound } from 'next/navigation'
import Link from 'next/link'
import {
  getActiveCreatorSpace,
  getCreatorBilling,
  getCreatorEvent,
  getCreatorGatheringSeriesList,
  getCreatorOfferPage,
  getCreatorPathways,
  getCreatorSpace,
} from '@/lib/serverApi'
import type {
  CreatorGatheringSeriesSummary,
  CreatorOfferPage,
  CreatorPathway,
  CreatorSpaceDetail,
} from '@/types/platform'
import CollectiveArtworkHeader from '@/components/creator/CollectiveArtworkHeader'
import OfferPageEditor from './OfferPageEditor'
import UpgradeNotice from '../UpgradeNotice'

/**
 * Offer Page — editor entry.
 *
 * Server component. Fetches the offer, its pathways (for the target
 * picker while draft), and the collective detail (for the artwork
 * header + palette continuity). Renders the upgrade notice if the
 * plan doesn't unlock paid offers so a Community creator hitting the
 * URL directly sees a calm state rather than a broken editor.
 */

interface Props {
  params: Promise<{ offerSlug: string }>
}

async function _safe<T>(p: Promise<T>, label: string, fallback: T): Promise<T> {
  try {
    return await p
  } catch (err) {
    console.error(`[creator-studio/offers/edit] ${label} failed:`, err)
    return fallback
  }
}

export default async function OfferPageEditPage({ params }: Props) {
  const { offerSlug } = await params
  const activeSpace = await getActiveCreatorSpace()

  const billing = await _safe(getCreatorBilling(), 'getCreatorBilling', null)
  const paidOffersEnabled = !!(
    billing?.is_platform_owner
    || billing?.current_plan?.paid_offers_enabled
  )

  if (!activeSpace) {
    return (
      <div className="w-full max-w-[1180px] px-8 py-8 md:px-10 md:py-10">
        <div className="mb-8">
          <h1 className="font-serif text-2xl text-navy-900 md:text-3xl">Offer Page</h1>
        </div>
        <div className="rounded-2xl border border-dashed border-slate-200 bg-white p-8 text-center">
          <p className="text-[14px] leading-relaxed text-black">
            Select a collective first from{' '}
            <Link href="/creator-studio" className="font-medium text-teal-700 hover:underline">
              My World
            </Link>{' '}
            to open this Offer Page.
          </p>
        </div>
      </div>
    )
  }

  if (!paidOffersEnabled) {
    return (
      <div className="w-full max-w-[1180px] px-8 py-8 md:px-10 md:py-10">
        <UpgradeNotice />
      </div>
    )
  }

  const offer = await _safe(
    getCreatorOfferPage(activeSpace.slug, offerSlug) as Promise<CreatorOfferPage | null>,
    'getCreatorOfferPage', null,
  )

  if (!offer) notFound()

  // Fetch only the reference data the editor actually needs for this
  // Offer Page's target kind. The editor no longer lets the Creator
  // silently retarget an existing page to a completely different
  // experience — the target panel is read-only — so we don't need to
  // load every kind's list.
  const [pathways, seriesList, event, spaceDetail]: [
    CreatorPathway[],
    CreatorGatheringSeriesSummary[],
    Awaited<ReturnType<typeof getCreatorEvent>> | null,
    CreatorSpaceDetail | null,
  ] = await Promise.all([
    offer.target_kind === 'pathway'
      ? _safe(getCreatorPathways(activeSpace.slug), 'getCreatorPathways', [])
      : Promise.resolve([] as CreatorPathway[]),
    offer.target_kind === 'event_series'
      ? _safe(
          getCreatorGatheringSeriesList(activeSpace.slug) as Promise<CreatorGatheringSeriesSummary[]>,
          'getCreatorGatheringSeriesList', [] as CreatorGatheringSeriesSummary[],
        )
      : Promise.resolve([] as CreatorGatheringSeriesSummary[]),
    offer.target_kind === 'gathering'
      ? _safe(
          getCreatorEvent(activeSpace.slug, offer.target_id) as Promise<
            Awaited<ReturnType<typeof getCreatorEvent>> | null
          >,
          'getCreatorEvent', null,
        )
      : Promise.resolve(null),
    _safe(
      getCreatorSpace(activeSpace.slug) as Promise<CreatorSpaceDetail | null>,
      'getCreatorSpace', null,
    ),
  ])

  // Resolve the display title for the target — null when the target
  // has been deleted since the Offer Page was created. Editor shows
  // "(target no longer available)" in that case.
  const targetTitle: string | null =
    offer.target_kind === 'pathway'
      ? pathways.find((p) => p.id === offer.target_id)?.title ?? null
    : offer.target_kind === 'event_series'
      ? seriesList.find((s) => s.id === offer.target_id)?.title ?? null
    : offer.target_kind === 'gathering'
      ? event?.title ?? null
      : null

  // Note: header meta intentionally omitted — the strong identity
  // band inside <OfferPageEditor /> carries "{kind} Offer Page /
  // {target name}", so echoing the same information in the header's
  // small italic subtitle would only clutter the composition.
  return (
    <div className="w-full max-w-[1180px] px-8 py-8 md:px-10 md:py-10">
      <CollectiveArtworkHeader
        collectiveName={activeSpace.name}
        sectionTitle={offer.title}
        location={spaceDetail?.location ?? null}
        coverImageUrl={spaceDetail?.cover_image_url ?? null}
        backLink={{ href: '/creator-studio/offers', label: '← Offer Pages' }}
      />

      <OfferPageEditor
        spaceSlug={activeSpace.slug}
        initialOffer={offer}
        targetTitle={targetTitle}
      />
    </div>
  )
}
