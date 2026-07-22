'use client'

import { useState } from 'react'
import { apiUrl } from '@/lib/api'

interface WaitingMember {
  user_id: string
  display_name: string
  email: string | null
}

interface ManualStepEntry {
  step_id: string
  step_slug: string
  step_title: string
  pathway_slug: string
  pathway_title: string
  waiting: WaitingMember[]
}

interface Props {
  spaceSlug: string
  initialEntries: ManualStepEntry[]
}

export default function ManualReleasesClient({ spaceSlug, initialEntries }: Props) {
  const [entries, setEntries] = useState<ManualStepEntry[]>(initialEntries)
  const [busyKey, setBusyKey] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function release(stepSlug: string, stepId: string, userId: string) {
    setBusyKey(`${stepId}:${userId}`)
    setError(null)
    try {
      const res = await fetch(
        apiUrl(
          `/api/creator/spaces/${spaceSlug}/pathways/`
          + `${entries.find((e) => e.step_id === stepId)?.pathway_slug ?? ''}`
          + `/steps/${stepSlug}/release-for/${userId}`,
        ),
        { method: 'POST', credentials: 'include' },
      )
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      // Optimistically drop the member from the local waiting list.
      setEntries((prev) => prev.map((e) => e.step_id === stepId
        ? { ...e, waiting: e.waiting.filter((m) => m.user_id !== userId) }
        : e))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Release failed.')
    } finally {
      setBusyKey(null)
    }
  }

  return (
    <div className="space-y-4">
      {error && <p className="text-[13px] text-red-500">{error}</p>}
      {entries.map((entry) => (
        <section
          key={entry.step_id}
          className="rounded-2xl bg-white px-6 py-5"
          style={{ border: '1px solid rgba(0,0,0,0.07)' }}
        >
          <div className="mb-3">
            <h2 className="font-serif text-lg text-navy-900">{entry.step_title}</h2>
            <p className="text-[12px] italic text-slate-500">
              {entry.pathway_title}
            </p>
          </div>

          {entry.waiting.length === 0 ? (
            <p className="text-[13px] italic text-slate-500">
              No one is waiting for this step.
            </p>
          ) : (
            <ul className="divide-y divide-slate-100">
              {entry.waiting.map((m) => {
                const busy = busyKey === `${entry.step_id}:${m.user_id}`
                return (
                  <li key={m.user_id} className="flex items-center justify-between gap-3 py-2.5">
                    <div>
                      <p className="text-[14px] font-medium text-navy-900">{m.display_name}</p>
                      {m.email && <p className="text-[11.5px] text-slate-500">{m.email}</p>}
                    </div>
                    <button
                      type="button"
                      onClick={() => release(entry.step_slug, entry.step_id, m.user_id)}
                      disabled={busy}
                      className="rounded-full px-4 py-1.5 text-[12.5px] font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-50"
                      style={{ background: 'var(--fc-accent, #0d9488)' }}
                    >
                      {busy ? 'Releasing…' : 'Release'}
                    </button>
                  </li>
                )
              })}
            </ul>
          )}
        </section>
      ))}
    </div>
  )
}
