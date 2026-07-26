'use client'

import { useState } from 'react'
import { PasswordInput } from '@/components/ui/PasswordInput'
import { apiUrl } from '@/lib/api'

const MIN_PASSWORD_LENGTH = 8

export default function ChangePasswordForm() {
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const [saving, setSaving] = useState(false)
  const [success, setSuccess] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setSuccess(false)
    setError(null)

    if (next !== confirm) {
      setError('New passwords do not match.')
      return
    }

    setSaving(true)
    try {
      const res = await fetch(apiUrl('/api/auth/me/change-password'), {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ current_password: current, new_password: next }),
      })

      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        setError(data.detail ?? 'Something went wrong. Please try again.')
        return
      }

      setSuccess(true)
      setCurrent('')
      setNext('')
      setConfirm('')
    } catch {
      setError('Network error. Please try again.')
    } finally {
      setSaving(false)
    }
  }

  const inputClass =
    'w-full rounded-lg border border-border bg-white px-4 py-2.5 text-sm text-navy-900 focus:border-teal-400 focus:outline-none focus:ring-2 focus:ring-teal-100'

  return (
    <form onSubmit={handleSubmit} className="space-y-4" noValidate>
      <div>
        <label className="mb-1.5 block text-sm font-medium text-navy-800" htmlFor="current-password">
          Current password
        </label>
        <PasswordInput
          id="current-password"
          autoComplete="current-password"
          value={current}
          onChange={(e) => setCurrent(e.target.value)}
          required
          className={inputClass}
        />
      </div>

      <div>
        <label className="mb-1.5 block text-sm font-medium text-navy-800" htmlFor="new-password">
          New password
        </label>
        <PasswordInput
          id="new-password"
          autoComplete="new-password"
          value={next}
          onChange={(e) => setNext(e.target.value)}
          required
          minLength={MIN_PASSWORD_LENGTH}
          className={inputClass}
        />
        <p className="mt-1 text-xs text-black">At least {MIN_PASSWORD_LENGTH} characters.</p>
      </div>

      <div>
        <label className="mb-1.5 block text-sm font-medium text-navy-800" htmlFor="confirm-new-password">
          Confirm new password
        </label>
        <PasswordInput
          id="confirm-new-password"
          autoComplete="new-password"
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
          required
          minLength={MIN_PASSWORD_LENGTH}
          className={inputClass}
        />
      </div>

      {error && <p role="alert" className="text-sm text-red-500">{error}</p>}
      {success && <p role="status" className="text-sm text-teal-600">Password updated.</p>}

      <button
        type="submit"
        disabled={saving}
        className="rounded-lg bg-navy-900 px-6 py-2.5 text-sm font-medium text-white transition-colors hover:bg-navy-800 disabled:opacity-50"
      >
        {saving ? 'Updating…' : 'Update password'}
      </button>
    </form>
  )
}
