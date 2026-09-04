import type { Metadata } from 'next'
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
 */
export default function VerifyEmailPage() {
  return <VerifyEmailClient />
}
