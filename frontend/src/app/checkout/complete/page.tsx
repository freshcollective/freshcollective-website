import type { Metadata } from 'next'
import { notFound } from 'next/navigation'
import SiteShell from '@/components/layout/SiteShell'
import Container from '@/components/layout/Container'
import CompleteFlow from '@/components/checkout/CompleteFlow'
import { getMe, getPurchaseByToken } from '@/lib/serverApi'

/**
 * /checkout/complete?token=<raw> — the real post-Stripe destination.
 *
 * Server component. Fetches the safe by-token summary of the
 * PurchaseIntent (a public endpoint that forwards the session cookie
 * so ``consumed_by_current_user`` is computed correctly) plus the
 * current viewer, and hands both to the client CompleteFlow which
 * picks the correct rendered state.
 *
 * If the token is missing or unknown → 404. Otherwise the client
 * component honestly reflects the intent's real state — no prototype
 * language, no fake success.
 */

export const metadata: Metadata = {
  title: 'Completing your purchase — Fresh Collective',
  robots: { index: false, follow: false },
}

export default async function CheckoutCompletePage({
  searchParams,
}: {
  searchParams: Promise<{ token?: string }>
}) {
  const { token } = await searchParams
  if (!token) notFound()

  const [intent, me] = await Promise.all([
    getPurchaseByToken(token),
    getMe().catch(() => null),
  ])
  if (!intent) notFound()

  return (
    <SiteShell>
      <section className="py-20 sm:py-24" style={{ background: '#FFFFFF' }}>
        <Container>
          <CompleteFlow
            token={token}
            initialData={intent}
            currentUserEmail={me?.email ?? null}
            currentUserName={me?.name ?? null}
          />
        </Container>
      </section>
    </SiteShell>
  )
}
