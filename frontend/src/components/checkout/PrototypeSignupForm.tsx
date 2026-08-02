'use client'

/**
 * PrototypeSignupForm — visual-only signup form for the account-creation
 * prototype flows at /signup/creator and /signup/member.
 *
 * PROTOTYPE ONLY. This component intentionally:
 *   - does NOT POST anywhere
 *   - does NOT create a user
 *   - does NOT grant any role, plan, entitlement or Collective access
 *   - does NOT log the visitor in
 *
 * On submit it simply navigates to `nextHref`, which the parent page
 * has already constructed to include `preview=true` and enough context
 * (plan / collective) for the honest holding screen at /checkout/next
 * to render truthfully.
 *
 * The real signup form lives at `frontend/src/app/signup/SignupForm.tsx`
 * and is untouched by this file. Do not import this component from the
 * generic /signup route.
 */

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import Button from '@/components/ui/Button'
import { PasswordInput } from '@/components/ui/PasswordInput'

interface Props {
  /** Where to navigate on submit. Must already carry `preview=true` and
   *  the flow context the /checkout/next holding screen needs. */
  nextHref: string
  /** Copy shown at the top of the form card. */
  heading: string
  subheading: string
}

export default function PrototypeSignupForm({ nextHref, heading, subheading }: Props) {
  const [submitting, setSubmitting] = useState(false)
  const router = useRouter()

  function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    // Prototype: no POST, no user creation. Just move to the honest
    // holding screen so the visitor can review the next step.
    setSubmitting(true)
    router.push(nextHref)
  }

  return (
    <div
      className="w-full max-w-[440px] rounded-2xl bg-white p-8 md:p-10"
      style={{
        boxShadow: '0 24px 60px rgba(5, 11, 20, 0.35), 0 2px 8px rgba(5, 11, 20, 0.20)',
      }}
    >
      <div className="mb-6 flex justify-center">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src="/brand/fresh-collective-logo-navy-gold-white.png"
          alt="Fresh Collective"
          style={{ height: '44px', width: 'auto' }}
        />
      </div>

      <div className="mb-6 text-center">
        <h1 className="mb-2 font-serif text-[26px] leading-tight text-navy-900">
          {heading}
        </h1>
        <p
          className="text-[14px] italic leading-relaxed"
          style={{ color: '#5A6B7D', fontFamily: 'Georgia, serif' }}
        >
          {subheading}
        </p>
      </div>

      <PrototypeNote>
        Prototype preview — no account is created and nothing is saved
        when you continue.
      </PrototypeNote>

      <form onSubmit={handleSubmit} className="mt-6 space-y-5">
        <div>
          <label htmlFor="name" className="mb-1.5 block text-sm font-medium text-navy-900">
            Full name
          </label>
          <input
            id="name"
            name="name"
            type="text"
            autoComplete="name"
            placeholder="Your name"
            className="w-full rounded-lg border border-border bg-surface px-4 py-3 text-sm text-navy-900 placeholder-[#718096] outline-none transition-colors focus:border-teal-500 focus:ring-2 focus:ring-teal-100"
          />
        </div>

        <div>
          <label htmlFor="email" className="mb-1.5 block text-sm font-medium text-navy-900">
            Email address
          </label>
          <input
            id="email"
            name="email"
            type="email"
            autoComplete="email"
            placeholder="you@example.com"
            className="w-full rounded-lg border border-border bg-surface px-4 py-3 text-sm text-navy-900 placeholder-[#718096] outline-none transition-colors focus:border-teal-500 focus:ring-2 focus:ring-teal-100"
          />
        </div>

        <div>
          <label htmlFor="password" className="mb-1.5 block text-sm font-medium text-navy-900">
            Password
          </label>
          <PasswordInput
            id="password"
            name="password"
            autoComplete="new-password"
            placeholder="At least 8 characters"
            className="w-full rounded-lg border border-border bg-surface px-4 py-3 text-sm text-navy-900 placeholder-[#718096] outline-none transition-colors focus:border-teal-500 focus:ring-2 focus:ring-teal-100"
          />
          <p className="mt-1.5 text-xs" style={{ color: '#718096' }}>Minimum 8 characters.</p>
        </div>

        <Button type="submit" variant="primary" size="md" className="w-full" disabled={submitting}>
          {submitting ? 'Loading…' : 'Preview the next step →'}
        </Button>
      </form>

      <p className="mt-6 text-center text-sm" style={{ color: '#5A6B7D' }}>
        Already have an account?{' '}
        <Link
          href="/login"
          className="font-medium text-teal-600 underline-offset-4 transition-colors hover:text-teal-700 hover:underline"
        >
          Log in
        </Link>
      </p>
    </div>
  )
}

function PrototypeNote({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="rounded-lg border px-3 py-2 text-center text-[12px] leading-snug"
      style={{
        borderColor: 'rgba(56, 160, 158, 0.32)',
        background: 'rgba(56, 160, 158, 0.06)',
        color: '#246B6A',
        fontFamily: 'Georgia, serif',
        fontStyle: 'italic',
      }}
    >
      {children}
    </div>
  )
}
