'use client'

/**
 * PlaceAndFeelForm — the Geographic Location half of the Place & Feel
 * tab in Creator Studio.
 *
 * Sits above the existing Collective Home panel (which stays exactly
 * as it was — atmosphere, palette, and the Home landscape). This
 * form captures:
 *
 *   * How does your Collective connect?  →  Online / In person / Both
 *   * Primary location                    →  LocationPicker (when
 *                                            not Online)
 *
 * Saves via the existing PATCH /api/creator/spaces/{slug} endpoint
 * — no bespoke endpoint for this shape. Publishing controls
 * discoverability; save controls whether the Place link exists.
 * Drafts save the link too.
 *
 * See docs/foundations/discovery-connection-belonging-location-model.md.
 */

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { apiUrl } from '@/lib/api'
import LocationPicker, { type PickedPlace } from '@/components/places/LocationPicker'
import type { CreatorSpaceDetail } from '@/types/platform'

type ConnectionStyle = 'online' | 'in_person' | 'both'

interface Props {
  space: CreatorSpaceDetail
}

const STYLE_OPTIONS: { value: ConnectionStyle; label: string; helper: string }[] = [
  { value: 'online',    label: 'Online',     helper: 'Members gather from anywhere.' },
  { value: 'in_person', label: 'In person',  helper: 'Members gather in a specific place.' },
  { value: 'both',      label: 'Both',       helper: 'A mix of online and in-person gatherings.' },
]

export default function PlaceAndFeelForm({ space }: Props) {
  const router = useRouter()
  const [style, setStyle] = useState<ConnectionStyle>(space.connection_style ?? 'online')
  const [place, setPlace] = useState<PickedPlace | null>(space.primary_place ?? null)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved]   = useState(false)
  const [error, setError]   = useState<string | null>(null)

  // Track whether the current form differs from what's saved. A
  // Creator who just opened the tab shouldn't see a Save prompt for
  // a change they haven't made.
  const dirty =
    style !== (space.connection_style ?? 'online') ||
    (place?.id ?? null) !== (space.primary_place?.id ?? null)

  const needsLocation = style === 'in_person' || style === 'both'
  const canSave =
    dirty &&
    !saving &&
    // If the Creator chose in_person/both they must pick a location
    // to save (matches the "require active choice" preference).
    (!needsLocation || place !== null)

  async function handleSave() {
    setSaving(true)
    setSaved(false)
    setError(null)
    try {
      const res = await fetch(apiUrl(`/api/creator/spaces/${space.slug}`), {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          connection_style: style,
          // Explicit empty string clears; omitting the field leaves
          // whatever is already stored. We always send an explicit
          // value so intent is unambiguous.
          primary_place_id: needsLocation && place ? place.id : '',
        }),
      })
      if (!res.ok) {
        const b = await res.json().catch(() => ({}))
        throw new Error(
          typeof b.detail === 'string'
            ? b.detail
            : `Save failed (${res.status})`,
        )
      }
      setSaved(true)
      router.refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong. Please try again.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <section
      className="rounded-2xl border border-border bg-white p-6"
      aria-labelledby="place-and-feel-heading"
    >
      <h2
        id="place-and-feel-heading"
        className="mb-1 text-[17px] font-semibold text-navy-900"
      >
        Geographic Location
      </h2>
      <p className="mb-6 text-[14px] italic leading-relaxed" style={{ color: 'rgba(12,24,38,0.62)', fontFamily: 'Georgia, serif' }}>
        Where in the real world your collective operates. Online-only
        collectives don&rsquo;t need a location.
      </p>

      {/* Connection style — the active choice. */}
      <div className="mb-6">
        <p id="conn-style-label" className="mb-2 text-[14px] font-semibold text-navy-900">
          How does your Collective connect?
        </p>
        <div role="radiogroup" aria-labelledby="conn-style-label" className="flex flex-wrap gap-2">
          {STYLE_OPTIONS.map((opt) => {
            const selected = style === opt.value
            return (
              <button
                key={opt.value}
                type="button"
                role="radio"
                aria-checked={selected}
                onClick={() => setStyle(opt.value)}
                className={
                  'rounded-xl border px-4 py-2.5 text-left text-[13px] transition-colors ' +
                  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40 focus-visible:ring-offset-2 ' +
                  (selected
                    ? 'border-teal-500 bg-teal-500/10 text-teal-700'
                    : 'border-slate-200 bg-white text-navy-600 hover:border-slate-300 hover:bg-slate-50')
                }
              >
                <span className={selected ? 'font-semibold' : 'font-medium'}>{opt.label}</span>
                <span className="mt-0.5 block text-[12px] text-navy-500">
                  {opt.helper}
                </span>
              </button>
            )
          })}
        </div>
      </div>

      {/* Primary location — only when connection style needs it. */}
      {needsLocation && (
        <div className="mb-6">
          <p className="mb-2 text-[14px] font-semibold text-navy-900">
            Primary location
          </p>
          <LocationPicker
            value={place}
            onChange={setPlace}
            helperText="Pick the city or region this collective is based in. A single searchable field is enough — Fresh Collective handles the rest behind the scenes."
          />
        </div>
      )}

      {/* Save row */}
      <div className="mt-4 flex items-center gap-4">
        <button
          type="button"
          onClick={handleSave}
          disabled={!canSave}
          className={
            'rounded-full px-5 py-2 text-[13px] font-semibold transition-opacity ' +
            'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40 focus-visible:ring-offset-2 ' +
            (canSave
              ? 'text-white opacity-100 hover:opacity-90'
              : 'text-white opacity-50 cursor-not-allowed')
          }
          style={{
            background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)',
            letterSpacing: '0.06em',
          }}
        >
          {saving ? 'Saving…' : 'Save changes'}
        </button>
        {saved && !dirty && (
          <span
            aria-live="polite"
            className="text-[13px] italic"
            style={{ color: '#1E6E6C', fontFamily: 'Georgia, serif' }}
          >
            Saved.
          </span>
        )}
        {needsLocation && !place && dirty && (
          <span className="text-[13px] italic text-navy-500" style={{ fontFamily: 'Georgia, serif' }}>
            Pick a primary location to save.
          </span>
        )}
      </div>

      {error && (
        <p role="alert" className="mt-3 text-[13px] text-[#A64526]">
          {error}
        </p>
      )}
    </section>
  )
}
