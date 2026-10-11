'use client'

/**
 * The payout sections, sharing one Connect status.
 *
 * Why this component exists
 * -------------------------
 * The readiness panel and the bank-account section describe the same Stripe
 * account. They used to hold separate copies of its status — the panel its
 * own state, the bank section a prop frozen at page load — so pressing
 * "Refresh status" updated one and left the other stale. In production that
 * meant a creator with payouts active, a confirmed bank account and a paid
 * payout was told "No bank account added yet", and no amount of refreshing
 * changed it.
 *
 * Holding the status once, here, makes that impossible rather than merely
 * fixed: there is no second copy to drift. The refresh still happens inside
 * the panel, using the existing ``POST /refresh`` — which is the call that
 * actually re-reads Stripe and persists the masked bank details — and both
 * sections re-render from its answer. No extra request.
 */

import { useState } from 'react'

import StripeConnectPanel from '../billing/StripeConnectPanel'
import type { CreatorStripeConnectStatus } from '@/types/platform'
import BankAccountPanel from './BankAccountPanel'

export default function BankPayoutsSections({
  initialStatus,
  planFeeBasisPoints,
}: {
  initialStatus: CreatorStripeConnectStatus | null
  planFeeBasisPoints: number | null
}) {
  const [status, setStatus] = useState<CreatorStripeConnectStatus | null>(
    initialStatus,
  )

  return (
    <>
      <StripeConnectPanel
        initialStatus={initialStatus}
        planFeeBasisPoints={planFeeBasisPoints}
        onStatusChange={setStatus}
      />
      <BankAccountPanel status={status} />
    </>
  )
}
