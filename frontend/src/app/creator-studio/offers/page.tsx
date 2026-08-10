import Link from 'next/link'
import {
  getActiveCreatorSpace,
  getCreatorBilling,
  getCreatorOfferPages,
  getCreatorPathways,
  getCreatorSpace,
} from '@/lib/serverApi'
import type {
  CreatorOfferPageSummary,
  CreatorPathway,
  CreatorSpaceDetail,
} from '@/types/platform'
import CollectiveArtworkHeader from '@/components/creator/CollectiveArtworkHeader'
import OffersIndexClient from './OffersIndexClient'
import UpgradeNotice from './UpgradeNotice'

/**
 * Offer Pages — index.
 *
 * Server component. Fetches the active Collective's Offer Pages plus
 * its pathways (so the "New Offer Page" modal can populate its
 * target picker without a second round trip). Renders the upgrade
 * notice if the current plan doesn't unlock paid offers — the
 * sidebar hides the entry for Community, but this route guard makes
 * sure a direct-nav shows something sensible rather than a broken
 * page.
 */

async function _safe<T>(p: Promise<T>, label: string, fallback: T): Promise<T> {
  try {
    return await p
  } catch (err) {
    console.error(`[creator-studio/offers] ${label} failed:`, err)
    return fallback
  }
}

export default async function OffersIndexPage() {
  const activeSpace = await getActiveCreatorSpace()

  // Plan gate — mirror the sidebar. Community sees the upgrade
  // notice; Platform Owner + Creator + Pro see the index.
  const billing = await _safe(getCreatorBilling(), 'getCreatorBilling', null)
  const paidOffersEnabled = !!(
    billing?.is_platform_owner
    || billing?.current_plan?.paid_offers_enabled
  )

  if (!activeSpace) {
    return (
      <div className="w-full max-w-[1180px] px-8 py-8 md:px-10 md:py-10">
        <div className="mb-8">
          <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500">
            Creator Studio
          </p>
          <h1 className="font-serif text-2xl text-navy-900 md:text-3xl">Offer Pages</h1>
        </div>
        <div className="rounded-2xl border border-dashed border-slate-200 bg-white p-8 text-center">
          <p className="mb-2 text-[16px] font-semibold text-navy-900">No collective yet</p>
          <p className="mb-6 text-[14px] leading-relaxed text-black">
            Set up your collective first, then create Offer Pages to share
            what you offer.
          </p>
          <Link
            href="/build-your-collective"
            className="inline-flex items-center rounded-xl px-5 py-2.5 text-[14px] font-semibold text-white transition-opacity hover:opacity-90"
            style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
          >
            Build your collective
          </Link>
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

  const [offers, pathways, spaceDetail]: [
    CreatorOfferPageSummary[],
    CreatorPathway[],
    CreatorSpaceDetail | null,
  ] = await Promise.all([
    _safe(getCreatorOfferPages(activeSpace.slug), 'getCreatorOfferPages', []),
    _safe(getCreatorPathways(activeSpace.slug), 'getCreatorPathways', []),
    _safe(
      getCreatorSpace(activeSpace.slug) as Promise<CreatorSpaceDetail | null>,
      'getCreatorSpace', null,
    ),
  ])

  return (
    <div className="w-full max-w-[1180px] px-8 py-8 md:px-10 md:py-10">
      <CollectiveArtworkHeader
        collectiveName={activeSpace.name}
        sectionTitle="Offer Pages"
        meta="Public pages you can share to invite people into what you offer."
        location={spaceDetail?.location ?? null}
        coverImageUrl={spaceDetail?.cover_image_url ?? null}
      />

      <OffersIndexClient
        spaceSlug={activeSpace.slug}
        initialOffers={offers}
        pathways={pathways}
      />
    </div>
  )
}
