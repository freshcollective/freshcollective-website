import { getActiveCreatorSpace, getCreatorBilling, getCreatorSpace } from '@/lib/serverApi'
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

  // Platform Owners have no creator plan, so no fee / currency to inherit.
  // The Payments client already handles the platform-owner branch and does
  // not render fee-related UI in that state.
  const feeBasisPoints = billing?.current_plan?.transaction_fee_basis_points ?? 0
  const currency = billing?.current_plan?.currency ?? 'AUD'
  const stripeEnabled = billing?.payment_setup.member_payments_connected ?? false
  const stripeTestMode = billing?.payment_setup.stripe_test_mode ?? false
  const isPlatformOwner = billing?.is_platform_owner ?? false

  return (
    <CreatorPaymentsClient
      feeBasisPoints={feeBasisPoints}
      currency={currency}
      stripeEnabled={stripeEnabled}
      stripeTestMode={stripeTestMode}
      isPlatformOwner={isPlatformOwner}
      headerCollectiveName={activeSpace?.name ?? null}
      headerLocation={spaceDetail?.location ?? null}
      headerCoverImageUrl={spaceDetail?.cover_image_url ?? null}
    />
  )
}
