import type { Metadata } from 'next'
import { Suspense } from 'react'
import VerifyEmailClient from './VerifyEmailClient'

export const metadata: Metadata = {
  title: 'Verify your email · Fresh Collective',
  description: 'Confirm your email address to start joining Collectives and Gatherings.',
}

/**
 * SEC-009 — email verification landing page.
 *
 * Reads ``?token=…`` from the URL, POSTs it to the backend, and
 * renders a warm success / friendly-error state. Works whether the
 * user is signed in or signed out — verification is proven by
 * possession of the token, not by the caller's session.
 *
 * The client component uses ``useSearchParams()``, which under the
 * Next.js App Router forces a client-side bailout during static
 * generation unless it lives inside a ``<Suspense>`` boundary. The
 * page (a Server Component) provides the boundary; the fallback is
 * a small "One moment…" state so first paint isn't blank while the
 * hydrated client reads the token.
 */
function VerifyEmailFallback() {
  return (
    <main
      className="mx-auto flex min-h-screen max-w-xl flex-col justify-center px-6 py-16"
      style={{ color: '#0C1826' }}
    >
      <h1 className="font-serif text-[28px] leading-tight md:text-[32px]">
        Verifying your email
      </h1>
      <p className="mt-4 text-[16px] opacity-80">One moment…</p>
    </main>
  )
}

export default function VerifyEmailPage() {
  return (
    <Suspense fallback={<VerifyEmailFallback />}>
      <VerifyEmailClient />
    </Suspense>
  )
}
