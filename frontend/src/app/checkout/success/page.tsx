import type { Metadata } from 'next'
import Link from 'next/link'
import SiteShell from '@/components/layout/SiteShell'
import Container from '@/components/layout/Container'

/**
 * /checkout/success — the redirect target used by FIP2 finite-plan
 * setup Sessions (see backend/scripts/fip2_start_finite_plan.py and
 * services/finite_plan_orchestration.py).
 *
 * Deliberately simple. This route is only proof of "Stripe redirected
 * the browser back". It MUST NOT imply that payment or access is
 * confirmed — the real activation flip happens server-side on
 * ``invoice.payment_succeeded`` after Stripe bills the first
 * instalment, which can take a moment after this page renders.
 *
 * A richer per-plan status view (with polling / real state) is out
 * of scope until FIP3 wires the full lifecycle; this page purely
 * exists so members don't land on Next.js's 404 after completing a
 * setup Session.
 */

export const metadata: Metadata = {
  title: 'Payment details saved — Fresh Collective',
  robots: { index: false, follow: false },
}


export default function CheckoutSuccessPage() {
  return (
    <SiteShell noFooter>
      <Container>
        <div className="mx-auto max-w-lg py-16 text-center">
          <h1 className="font-serif text-3xl leading-tight text-navy-900">
            Payment details saved
          </h1>
          <p className="mt-4 text-[15px] leading-relaxed text-slate-700">
            We&rsquo;re confirming your payment plan and access. This can
            take a moment.
          </p>
          <p className="mt-6 text-[13px] leading-relaxed text-slate-500">
            You can close this tab or return to Fresh Collective — your
            plan will appear in your account as soon as it&rsquo;s ready.
          </p>
          <div className="mt-8">
            <Link
              href="/dashboard"
              className="inline-flex items-center rounded-full px-6 py-2.5 text-[14px] font-semibold text-white transition-opacity hover:opacity-90"
              style={{
                background:
                  'linear-gradient(135deg, var(--fc-accent, #38A09E) 0%, var(--fc-accent-strong, #55B8B6) 100%)',
              }}
            >
              Return to Fresh Collective
            </Link>
          </div>
        </div>
      </Container>
    </SiteShell>
  )
}
