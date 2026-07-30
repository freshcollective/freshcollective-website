'use client'

import { useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { apiUrl } from '@/lib/api'
import type {
  PhysicalLocationDetail,
  PhysicalLocationStatus,
} from '@/lib/physicalLocations/types'

/**
 * Add a new Physical Location. Small identity form — artwork,
 * blurb, and admin note are added on the detail page once the row
 * exists. Newly-created rows start as ``draft`` so administrators
 * can prepare artwork and copy before anything appears on
 * Discover Places.
 */
export default function NewPhysicalLocationPage() {
  const router = useRouter()
  const [name, setName] = useState('')
  const [slug, setSlug] = useState('')
  const [region, setRegion] = useState('')
  const [country, setCountry] = useState('AU')
  const [status, setStatus] = useState<PhysicalLocationStatus>('draft')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const canCreate = name.trim().length > 0 && country.trim().length === 2

  async function create() {
    setBusy(true)
    setError(null)
    try {
      const res = await fetch(apiUrl('/api/admin/physical-locations'), {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: name.trim(),
          slug: slug.trim() || null,
          region: region.trim() || null,
          country_code: country.trim(),
          status,
        }),
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(
          typeof data.detail === 'string'
            ? data.detail
            : 'Could not create Physical Location.'
        )
      }
      const created = (await res.json()) as PhysicalLocationDetail
      router.push(`/admin/physical-locations/${created.slug}`)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not create Physical Location.')
      setBusy(false)
    }
  }

  return (
    <div className="mx-auto max-w-[720px] px-6 py-10 md:px-10">
      <Link
        href="/admin/physical-locations"
        className="mb-6 inline-flex items-center text-[13px] font-medium transition-opacity hover:opacity-70"
        style={{ color: 'rgba(12, 24, 38, 0.62)' }}
      >
        ← Physical Locations
      </Link>

      <header className="mb-10">
        <p className="mb-3 text-[11px] font-semibold uppercase tracking-[0.28em]" style={{ color: '#38A09E' }}>
          World Management
        </p>
        <h1 className="font-serif text-[30px] leading-tight md:text-[36px]" style={{ color: '#0C1826' }}>
          A new Physical Location
        </h1>
        <p className="mt-3 text-[14.5px] italic" style={{ color: 'rgba(12,24,38,0.65)', fontFamily: 'Georgia, serif' }}>
          Name the place and where it sits in the world. Artwork,
          editorial blurb, and admin notes are added on the detail
          page once it exists.
        </p>
      </header>

      <div
        className="mb-6 rounded-2xl px-5 py-4"
        style={{
          background: 'rgba(56,160,158,0.06)',
          border: '1px solid rgba(56,160,158,0.28)',
        }}
      >
        <p
          className="text-[13.5px] leading-relaxed"
          style={{ color: 'rgba(12, 24, 38, 0.78)', fontFamily: 'Georgia, serif' }}
        >
          Use a broad location members will naturally recognise
          and search for, such as <strong>Melbourne</strong>,
          <strong> Hobart</strong> or the <strong>Blue Mountains</strong>.
          Store suburbs and venue addresses on the Collective or
          Gathering — not here.
        </p>
      </div>

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
              placeholder="e.g. Byron Bay"
              className="w-full rounded-xl px-4 py-3 text-[15px] focus:outline-none"
              style={{ background: '#FFFFFF', border: '1px solid rgba(12,24,38,0.12)', color: '#0C1826' }}
            />
          </div>
          <div>
            <label className="mb-2 block text-[11px] font-semibold uppercase tracking-[0.20em]" style={{ color: 'rgba(12,24,38,0.62)' }}>
              URL slug <span className="text-[10.5px] font-normal normal-case italic" style={{ color: 'rgba(12,24,38,0.45)' }}>(optional — derived from name)</span>
            </label>
            <input
              type="text"
              value={slug}
              onChange={(e) => setSlug(e.target.value)}
              maxLength={100}
              placeholder="byron-bay"
              className="w-full rounded-xl px-4 py-3 text-[15px] focus:outline-none"
              style={{ background: '#FFFFFF', border: '1px solid rgba(12,24,38,0.12)', color: '#0C1826' }}
            />
          </div>
          <div className="grid gap-5 md:grid-cols-[1.6fr_1fr]">
            <div>
              <label className="mb-2 block text-[11px] font-semibold uppercase tracking-[0.20em]" style={{ color: 'rgba(12,24,38,0.62)' }}>
                State / region
              </label>
              <input
                type="text"
                value={region}
                onChange={(e) => setRegion(e.target.value)}
                maxLength={100}
                placeholder="Northern Rivers"
                className="w-full rounded-xl px-4 py-3 text-[15px] focus:outline-none"
                style={{ background: '#FFFFFF', border: '1px solid rgba(12,24,38,0.12)', color: '#0C1826' }}
              />
            </div>
            <div>
              <label className="mb-2 block text-[11px] font-semibold uppercase tracking-[0.20em]" style={{ color: 'rgba(12,24,38,0.62)' }}>
                Country (ISO)
              </label>
              <input
                type="text"
                value={country}
                onChange={(e) => setCountry(e.target.value.toUpperCase().slice(0, 2))}
                maxLength={2}
                placeholder="AU"
                className="w-full rounded-xl px-4 py-3 text-[15px] uppercase focus:outline-none"
                style={{ background: '#FFFFFF', border: '1px solid rgba(12,24,38,0.12)', color: '#0C1826' }}
              />
            </div>
          </div>
          <div>
            <label className="mb-2 block text-[11px] font-semibold uppercase tracking-[0.20em]" style={{ color: 'rgba(12,24,38,0.62)' }}>
              Status
            </label>
            <div className="flex flex-wrap gap-2">
              {(['draft', 'active', 'hidden', 'archived'] as const).map((s) => {
                const on = status === s
                return (
                  <button
                    key={s}
                    type="button"
                    onClick={() => setStatus(s)}
                    className="rounded-full px-4 py-2 text-[12.5px] font-medium capitalize transition-all"
                    style={{
                      background: on ? 'rgba(56,160,158,0.10)' : '#FFFFFF',
                      border: on ? '1px solid rgba(56,160,158,0.55)' : '1px solid rgba(12,24,38,0.12)',
                      color: on ? '#38A09E' : '#0C1826',
                    }}
                  >
                    {s}
                  </button>
                )
              })}
            </div>
            <p className="mt-2 text-[12.5px] italic" style={{ color: 'rgba(12,24,38,0.55)', fontFamily: 'Georgia, serif' }}>
              Only <strong>active</strong> Physical Locations show up on Discover Places.
            </p>
          </div>
        </div>

        {error && <p className="mt-4 text-[13px]" style={{ color: '#A64526' }}>{error}</p>}

        <div className="mt-8 flex items-center justify-between">
          <Link
            href="/admin/physical-locations"
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
            {busy ? 'Creating…' : 'Add Physical Location'}
          </button>
        </div>
      </section>
    </div>
  )
}
