import {
  getActiveCreatorSpace,
  getCreatorBilling,
  getCreatorSpace,
  getSpaceBillingContext,
} from '@/lib/serverApi'
import type { CreatorSpaceDetail } from '@/types/platform'
import CreatorPaymentsClient from './CreatorPaymentsClient'

export const metadata = { title: 'Payments — Creator Studio' }

export default async function CreatorPaymentsPage() {
  const [billing, activeSpace] = await Promise.all([
    getCreatorBilling(),
    getActiveCreatorSpace(),
  ])
  const spaceDetail: CreatorSpaceDetail | null = activeSpace
    ? ((await getCreatorSpace(activeSpace.slug)) as CreatorSpaceDetail | null)
    : null

  // Per-Space billing context — decouples "viewer is admin"
  // (permission) from "selected Space is platform-owned" (card copy +
  // fee display). Prior versions of this page conflated the two via
  // billing.is_platform_owner and rendered "Platform Owner" cards for
  // every Collective an admin viewed.
  const spaceBillingContext = activeSpace
    ? await getSpaceBillingContext(activeSpace.slug)
    : null

  const viewerIsAdmin = billing?.is_platform_owner ?? false
  const selectedSpaceIsPlatformOwned =
    spaceBillingContext?.selected_space_is_platform_owned ?? false
  // Effective fee bps for the selected Space's creator. Falls back to
  // the viewer's own plan bps only when we have no space context
  // (creator with no Spaces yet). This is what powers the fee-display
  // in the Payments received account card.
  const feeBasisPoints =
    spaceBillingContext?.effective_transaction_fee_basis_points
    ?? billing?.current_plan?.transaction_fee_basis_points
    ?? 0
  const currency =
    spaceBillingContext?.effective_currency
    ?? billing?.current_plan?.currency
    ?? 'AUD'
  const stripeEnabled = billing?.payment_setup.member_payments_connected ?? false
  const stripeTestMode = billing?.payment_setup.stripe_test_mode ?? false

  return (
    <CreatorPaymentsClient
      feeBasisPoints={feeBasisPoints}
      currency={currency}
      stripeEnabled={stripeEnabled}
      stripeTestMode={stripeTestMode}
      viewerIsAdmin={viewerIsAdmin}
      selectedSpaceIsPlatformOwned={selectedSpaceIsPlatformOwned}
      spaceSlug={activeSpace?.slug ?? null}
      spaceOwnerIsViewer={spaceBillingContext?.viewer_is_space_owner ?? false}
      headerCollectiveName={activeSpace?.name ?? null}
      headerLocation={spaceDetail?.location ?? null}
      headerCoverImageUrl={spaceDetail?.cover_image_url ?? null}
    />
  )
}
