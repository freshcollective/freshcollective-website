'use client'

import { useState } from 'react'
import Link from 'next/link'
import AuthCard from '@/components/layout/AuthCard'
import Button from '@/components/ui/Button'
import { apiUrl, extractErrorMessage } from '@/lib/api'

export default function ForgotPasswordForm() {
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    setError(null)
    setSuccess(null)
    setLoading(true)

    const email = (e.currentTarget.elements.namedItem('email') as HTMLInputElement).value.trim()

    try {
      const res = await fetch(apiUrl('/api/auth/forgot-password'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email }),
      })

      if (!res.ok) {
        const data = await res.json().catch(() => ({ detail: 'Something went wrong.' }))
        setError(extractErrorMessage(data))
        return
      }

      const data = await res.json()
      setSuccess(data.message ?? 'If that email is registered, a reset link will appear in the server console.')
    } catch {
      setError('Unable to connect to the server. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <AuthCard
      title="Reset your password"
      subtitle="Enter your email and we’ll send you a link to set a new one."
      error={error}
      footerLink={success ? undefined : { href: '/login', label: 'Back to log in' }}
    >
      {success ? (
        <div className="space-y-4">
          <div className="rounded-lg border border-teal-200 bg-teal-50 px-4 py-3 text-sm text-teal-800">
            {success}
          </div>
          <Link
            href="/login"
            className="block text-center text-sm text-teal-600 underline-offset-4 transition-colors hover:text-teal-700 hover:underline"
          >
            Back to log in
          </Link>
        </div>
      ) : (
        <form onSubmit={handleSubmit} className="space-y-5">
          <div>
            <label htmlFor="email" className="mb-1.5 block text-sm font-medium text-navy-900">
              Email address
            </label>
            <input
              id="email"
              name="email"
              type="email"
              autoComplete="email"
              required
              placeholder="you@example.com"
              className="w-full rounded-lg border border-border bg-surface px-4 py-3 text-sm text-navy-900 placeholder-[#718096] outline-none transition-colors focus:border-teal-500 focus:ring-2 focus:ring-teal-100"
            />
          </div>

          <Button type="submit" variant="primary" size="md" className="w-full" disabled={loading}>
            {loading ? (
              <span className="flex items-center justify-center gap-2">
                <span className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
                Sending…
              </span>
            ) : (
              'Send reset link'
            )}
          </Button>
        </form>
      )}
    </AuthCard>
  )
}
