import type { Metadata } from 'next'
import Link from 'next/link'
import SiteShell from '@/components/layout/SiteShell'
import Container from '@/components/layout/Container'

/**
 * /checkout/repair-return — Stripe success_url for FIP4B2 repair
 * setup Sessions (see backend/app/commerce/finite_plan_repair_routes.py).
 *
 * Deliberately truthful. Saving a new PaymentMethod is NOT the same
 * as recovery. Stripe redirects the browser back the moment the
 * setup Session completes, but the actual retry of the overdue
 * invoice happens in the ``checkout.session.completed`` webhook
 * handler (:func:`app.webhooks.finite_plan_handlers.handle_finite_plan_repair_completed`)
 * — usually a second or two later. The plan doesn't transition
 * back to ``active`` (and access is not reinstated for suspended
 * members) until the subsequent ``invoice.payment_succeeded``
 * webhook fires.
 *
 * We deliberately do NOT say "Payment successful" here. We say
 * "Payment details updated — we're retrying now". No polling; the
 * MemberPlanState refresh happens naturally when the member
 * navigates back to any Experience surface (banner disappears once
 * the plan is active).
 */

export const metadata: Metadata = {
  title: 'Payment details updated — Fresh Collective',
  robots: { index: false, follow: false },
}


export default function RepairReturnPage() {
  return (
    <SiteShell noFooter>
      <Container>
        <div className="mx-auto max-w-lg py-16 text-center">
          <h1 className="font-serif text-3xl leading-tight text-navy-900">
            Payment details updated
          </h1>
          <p className="mt-4 text-[15px] leading-relaxed text-slate-700">
            We&rsquo;re retrying your payment now. Your access will
            update as soon as the payment is confirmed.
          </p>
          <p className="mt-6 text-[13px] leading-relaxed text-slate-500">
            You can close this tab or return to Fresh Collective — the
            recovery banner will disappear from your Experience pages
            as soon as the retry succeeds.
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
