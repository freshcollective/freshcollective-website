'use client'

import { useState } from 'react'
import Link from 'next/link'
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
    <div
      className="w-full max-w-sm rounded-xl border border-border bg-surface p-8 md:p-10"
      style={{ boxShadow: 'var(--fc-shadow-md)' }}
    >
      <div className="mb-8">
        <div className="mb-4 h-px w-6 bg-gold-500" />
        <h1 className="mb-2 font-serif text-3xl text-navy-900">Reset your password.</h1>
        <p className="text-sm text-[#718096]">Enter your email and we&apos;ll send you a reset link.</p>
      </div>

      {error && (
        <div role="alert" className="mb-5 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

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

          <p className="text-center text-sm text-[#718096]">
            <Link href="/login" className="text-teal-600 underline-offset-4 transition-colors hover:text-teal-700 hover:underline">
              Back to log in
            </Link>
          </p>
        </form>
      )}
    </div>
  )
}
