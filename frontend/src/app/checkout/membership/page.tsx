import type { Metadata } from 'next'
import { redirect } from 'next/navigation'

import Container from '@/components/layout/Container'
import SiteShell from '@/components/layout/SiteShell'
import { getMe } from '@/lib/serverApi'
import MembershipReturnFlow from './MembershipReturnFlow'

/**
 * /checkout/membership?collective=<slug> — where Stripe sends a member
 * back after a membership subscription, or after changing the card on
 * one.
 *
 * Deliberately NOT under /spaces/[slug]: that area's layout can turn
 * a non-member away, and for a second or two after checkout this
 * member may still be exactly that — the webhook that grants
 * membership has not necessarily landed. Sending them somewhere that
 * might bounce them is the one thing this page must not do.
 */

export const metadata: Metadata = {
  title: 'Your membership — Fresh Collective',
  robots: { index: false, follow: false },
}

export default async function MembershipReturnPage({
  searchParams,
}: {
  searchParams: Promise<{
    collective?: string
    checkout?: string
    session_id?: string
    pm_session_id?: string
  }>
}) {
  const { collective, checkout, pm_session_id } = await searchParams
  if (!collective) redirect('/settings/membership')

  const me = await getMe().catch(() => null)
  if (!me) redirect(`/login?next=/checkout/membership?collective=${collective}`)

  return (
    <SiteShell>
      <section className="py-16 sm:py-20" style={{ background: '#FFFFFF' }}>
        <Container>
          <MembershipReturnFlow
            slug={collective}
            outcome={checkout ?? null}
            paymentMethodSessionId={pm_session_id ?? null}
          />
        </Container>
      </section>
    </SiteShell>
  )
}
