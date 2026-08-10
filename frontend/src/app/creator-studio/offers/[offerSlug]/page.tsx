import { notFound } from 'next/navigation'
import Link from 'next/link'
import {
  getActiveCreatorSpace,
  getCreatorBilling,
  getCreatorOfferPage,
  getCreatorPathways,
  getCreatorSpace,
} from '@/lib/serverApi'
import type {
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

  const [offer, pathways, spaceDetail]: [
    CreatorOfferPage | null,
    CreatorPathway[],
    CreatorSpaceDetail | null,
  ] = await Promise.all([
    _safe(
      getCreatorOfferPage(activeSpace.slug, offerSlug) as Promise<CreatorOfferPage | null>,
      'getCreatorOfferPage', null,
    ),
    _safe(getCreatorPathways(activeSpace.slug), 'getCreatorPathways', []),
    _safe(
      getCreatorSpace(activeSpace.slug) as Promise<CreatorSpaceDetail | null>,
      'getCreatorSpace', null,
    ),
  ])

  if (!offer) notFound()

  const targetPathway = pathways.find((p) => p.id === offer.target_id) ?? null

  return (
    <div className="w-full max-w-[1180px] px-8 py-8 md:px-10 md:py-10">
      <CollectiveArtworkHeader
        collectiveName={activeSpace.name}
        sectionTitle={offer.title}
        meta={
          targetPathway
            ? `Offer Page · Pathway: ${targetPathway.title}`
            : 'Offer Page'
        }
        location={spaceDetail?.location ?? null}
        coverImageUrl={spaceDetail?.cover_image_url ?? null}
        backLink={{ href: '/creator-studio/offers', label: '← Offer Pages' }}
      />

      <OfferPageEditor
        spaceSlug={activeSpace.slug}
        initialOffer={offer}
        pathways={pathways}
      />
    </div>
  )
}
