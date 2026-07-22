'use client'

import { useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { apiUrl } from '@/lib/api'
import type { LocationDetail } from '@/lib/atlas/types'

/**
 * Add a new Location to The Atlas. Small, focused form — everything else
 * (artwork, taxonomy, recommendation metadata) is edited on the detail
 * page once the Location exists.
 */
export default function NewLocationPage() {
  const router = useRouter()
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [status, setStatus] = useState<'active' | 'hidden'>('active')
  const [locationType, setLocationType] = useState<'ATLAS' | 'COMMUNITY' | 'CORNERSTONE'>('ATLAS')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const canCreate = name.trim().length > 0

  async function create() {
    setBusy(true)
    setError(null)
    try {
      const res = await fetch(apiUrl('/api/admin/atlas/locations'), {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: name.trim(),
          description: description.trim() || null,
          status,
          location_type: locationType,
        }),
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(typeof data.detail === 'string' ? data.detail : 'Could not create Location.')
      }
      const created = await res.json() as LocationDetail
      router.push(`/admin/atlas/${created.key}`)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not create Location.')
      setBusy(false)
    }
  }

  return (
    <div className="mx-auto max-w-[720px] px-6 py-10 md:px-10">
      <Link
        href="/admin/atlas"
        className="mb-6 inline-flex items-center text-[13px] font-medium transition-opacity hover:opacity-70"
        style={{ color: 'rgba(12, 24, 38, 0.62)' }}
      >
        ← The Atlas
      </Link>

      <header className="mb-10">
        <p className="mb-3 text-[11px] font-semibold uppercase tracking-[0.28em]" style={{ color: '#38A09E' }}>
          Fresh Collective
        </p>
        <h1 className="font-serif text-[30px] leading-tight md:text-[36px]" style={{ color: '#0C1826' }}>
          A new Location
        </h1>
        <p className="mt-3 text-[14.5px] italic" style={{ color: 'rgba(12,24,38,0.65)', fontFamily: 'Georgia, serif' }}>
          Give it a name and a first sentence. Artwork, taxonomy and recommendation metadata are added on the detail page once it exists.
        </p>
      </header>

      <section
        className="rounded-2xl bg-white px-6 py-7 md:px-8"
        style={{
          border: '1px solid rgba(12, 24, 38, 0.06)',
          boxShadow: '0 1px 3px rgba(12, 24, 38, 0.03)',
        }}
      >
        <div className="grid gap-5">
          <div>
            <label className="mb-2 block text-[11px] font-semibold uppercase tracking-[0.20em]" style={{ color: 'rgba(12,24,38,0.62)' }}>
              Name
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={200}
              placeholder="e.g. The Grove"
              className="w-full rounded-xl px-4 py-3 text-[15px] focus:outline-none"
              style={{ background: '#FFFFFF', border: '1px solid rgba(12,24,38,0.12)', color: '#0C1826' }}
            />
          </div>
          <div>
            <label className="mb-2 block text-[11px] font-semibold uppercase tracking-[0.20em]" style={{ color: 'rgba(12,24,38,0.62)' }}>
              Description
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              maxLength={2000}
              rows={4}
              placeholder="One sentence about the feeling of this place."
              className="w-full resize-none rounded-xl px-4 py-3 text-[14.5px] leading-relaxed focus:outline-none"
              style={{ background: '#FFFFFF', border: '1px solid rgba(12,24,38,0.12)', color: '#0C1826', fontFamily: 'Georgia, serif' }}
            />
          </div>
          <div>
            <label className="mb-2 block text-[11px] font-semibold uppercase tracking-[0.20em]" style={{ color: 'rgba(12,24,38,0.62)' }}>
              Type
            </label>
            <div className="flex flex-wrap gap-2">
              {(['ATLAS', 'COMMUNITY', 'CORNERSTONE'] as const).map((t) => {
                const on = locationType === t
                return (
                  <button
                    key={t}
                    type="button"
                    onClick={() => setLocationType(t)}
                    className="rounded-full px-4 py-2 text-[12.5px] font-medium transition-all"
                    style={{
                      background: on ? 'rgba(56,160,158,0.10)' : '#FFFFFF',
                      border: on ? '1px solid rgba(56,160,158,0.55)' : '1px solid rgba(12,24,38,0.12)',
                      color: on ? '#38A09E' : '#0C1826',
                    }}
                  >
                    {t === 'ATLAS' ? 'Atlas Location' : t === 'COMMUNITY' ? 'Community Location' : 'Cornerstone'}
                  </button>
                )
              })}
            </div>
            <p className="mt-2 text-[12.5px] italic" style={{ color: 'rgba(12,24,38,0.55)', fontFamily: 'Georgia, serif' }}>
              {locationType === 'CORNERSTONE'
                ? 'Reserved for Fresh Collective experiences. Not shown to creators.'
                : locationType === 'COMMUNITY'
                ? 'A simple place where a new community begins. Offered to Community (Free) collectives.'
                : 'A premium world available to Creator and Pro collectives.'}
            </p>
          </div>

          <div>
            <label className="mb-2 block text-[11px] font-semibold uppercase tracking-[0.20em]" style={{ color: 'rgba(12,24,38,0.62)' }}>
              Status
            </label>
            <div className="flex gap-2">
              {(['active', 'hidden'] as const).map((s) => {
                const on = status === s
                return (
                  <button
                    key={s}
                    type="button"
                    onClick={() => setStatus(s)}
                    className="rounded-full px-4 py-2 text-[12.5px] font-medium transition-all"
                    style={{
                      background: on ? 'rgba(56,160,158,0.10)' : '#FFFFFF',
                      border: on ? '1px solid rgba(56,160,158,0.55)' : '1px solid rgba(12,24,38,0.12)',
                      color: on ? '#38A09E' : '#0C1826',
                    }}
                  >
                    {s === 'active' ? 'Active' : 'Hidden'}
                  </button>
                )
              })}
            </div>
          </div>
        </div>

        {error && <p className="mt-4 text-[13px]" style={{ color: '#A64526' }}>{error}</p>}

        <div className="mt-8 flex items-center justify-between">
          <Link
            href="/admin/atlas"
            className="text-[13px] font-medium transition-opacity hover:opacity-70"
            style={{ color: 'rgba(12, 24, 38, 0.55)' }}
          >
            Cancel
          </Link>
          <button
            type="button"
            onClick={create}
            disabled={!canCreate || busy}
            className="rounded-full px-5 py-2.5 text-[13px] font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-40"
            style={{
              background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)',
              letterSpacing: '0.06em',
            }}
          >
            {busy ? 'Creating…' : 'Add to Atlas'}
          </button>
        </div>
      </section>
    </div>
  )
}
