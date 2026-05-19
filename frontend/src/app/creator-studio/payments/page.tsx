import { getCreatorBilling } from '@/lib/serverApi'
import CreatorPaymentsClient from './CreatorPaymentsClient'

export const metadata = { title: 'Payments — Creator Studio' }

export default async function CreatorPaymentsPage() {
  const billing = await getCreatorBilling()
  const feeBasisPoints = billing?.current_plan.transaction_fee_basis_points ?? 0
  const currency = billing?.current_plan.currency ?? 'AUD'

  return (
    <CreatorPaymentsClient feeBasisPoints={feeBasisPoints} currency={currency} />
  )
}
