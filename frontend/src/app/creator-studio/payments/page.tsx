import { getCreatorBilling } from '@/lib/serverApi'
import CreatorPaymentsClient from './CreatorPaymentsClient'

export const metadata = { title: 'Payments — Creator Studio' }

export default async function CreatorPaymentsPage() {
  const billing = await getCreatorBilling()
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
    />
  )
}
