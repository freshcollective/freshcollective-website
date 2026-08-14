'use client'

import { useRouter } from 'next/navigation'
import { useState } from 'react'
import { apiUrl } from '@/lib/api'

export default function NewPaymentOptionClient({ spaceSlug }: { spaceSlug: string }) {
  const router = useRouter()
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault()
    if (!name.trim()) {
      setError('Please give this Payment Option a name.')
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      const res = await fetch(
        apiUrl(`/api/creator/spaces/${spaceSlug}/commerce/payment-options`),
        {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            name: name.trim(),
            description: description.trim() || null,
            payment_type: 'one_time',
            status: 'draft',
            currency: 'AUD',
          }),
        },
      )
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body?.detail ?? `${res.status} ${res.statusText}`)
      }
      const created = await res.json() as { id: string }
      router.push(`/creator-studio/payment-options/${created.id}`)
    } catch (err) {
      setError(String((err as Error)?.message ?? err))
      setSubmitting(false)
    }
  }

  return (
    <form
      onSubmit={handleCreate}
      className="rounded-xl border border-slate-200 bg-white p-6"
    >
      <label className="block text-[13px] font-semibold text-navy-900">
        Name
      </label>
      <input
        type="text"
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder='e.g. "Awaken" or "Standard Ticket" or "Course Access"'
        className="mt-1.5 w-full rounded-md border border-slate-300 px-3 py-2 text-[14px] focus:border-teal-500 focus:outline-none focus:ring-1 focus:ring-teal-500"
        autoFocus
      />
      <p className="mt-1.5 text-[12px] text-slate-500">
        This is what members see when they choose how to join.
      </p>

      <label className="mt-6 block text-[13px] font-semibold text-navy-900">
        Description <span className="text-slate-400">(optional)</span>
      </label>
      <textarea
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        rows={3}
        placeholder="A short line about what this option is for."
        className="mt-1.5 w-full rounded-md border border-slate-300 px-3 py-2 text-[14px] focus:border-teal-500 focus:outline-none focus:ring-1 focus:ring-teal-500"
      />

      {error && (
        <p className="mt-4 rounded-md bg-red-50 px-3 py-2 text-[12px] text-red-800 ring-1 ring-red-200">
          {error}
        </p>
      )}

      <div className="mt-6 flex items-center gap-3">
        <button
          type="submit"
          disabled={submitting}
          className="inline-flex items-center rounded-md bg-teal-600 px-4 py-2 text-[13px] font-semibold text-white transition-colors hover:bg-teal-700 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {submitting ? 'Creating…' : 'Create & continue'}
        </button>
        <button
          type="button"
          onClick={() => router.push('/creator-studio/payment-options')}
          className="text-[13px] text-slate-600 hover:text-slate-800"
        >
          Cancel
        </button>
      </div>
    </form>
  )
}
