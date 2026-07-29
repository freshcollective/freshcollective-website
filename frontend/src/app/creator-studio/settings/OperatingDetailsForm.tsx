'use client'

/**
 * OperatingDetailsForm — "Where does this Collective operate?"
 *
 * Rendered on the Details tab in Creator Studio. Groups the
 * practical, operational settings that describe how the Collective
 * meets its members in the real world:
 *
 *   * How does your Collective connect?  →  Online / In person / Both
 *   * Geographic location                 →  LocationPicker (when
 *                                             not Online)
 *   * Timezone                            →  used to display
 *                                             gathering dates + times
 *
 * These are deliberately kept apart from the *Place & Feel* tab.
 * Place & Feel is the emotional / visual identity of the Collective
 * (Island + atmosphere + palette). This form is about where and
 * when the Collective operates. Same underlying PATCH endpoint;
 * separate save button so the two areas remain independently
 * editable.
 *
 * See docs/foundations/discovery-connection-belonging-location-model.md.
 */

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { apiUrl } from '@/lib/api'
import LocationPicker, { type PickedPlace } from '@/components/places/LocationPicker'
import type { CreatorSpaceDetail } from '@/types/platform'

type ConnectionStyle = 'online' | 'in_person' | 'both'

const STYLE_OPTIONS: { value: ConnectionStyle; label: string; helper: string }[] = [
  { value: 'online',    label: 'Online',     helper: 'Members gather from anywhere.' },
  { value: 'in_person', label: 'In person',  helper: 'Members gather in a specific place.' },
  { value: 'both',      label: 'Both',       helper: 'A mix of online and in-person gatherings.' },
]

const TIMEZONE_OPTIONS = [
  { value: 'Australia/Melbourne', label: 'Melbourne (AEST / AEDT)' },
  { value: 'Australia/Sydney',    label: 'Sydney (AEST / AEDT)' },
  { value: 'Australia/Brisbane',  label: 'Brisbane (AEST)' },
  { value: 'Australia/Adelaide',  label: 'Adelaide (ACST / ACDT)' },
  { value: 'Australia/Perth',     label: 'Perth (AWST)' },
  { value: 'Pacific/Auckland',    label: 'Auckland (NZST / NZDT)' },
  { value: 'Europe/London',       label: 'London (GMT / BST)' },
  { value: 'America/New_York',    label: 'New York (EST / EDT)' },
  { value: 'America/Los_Angeles', label: 'Los Angeles (PST / PDT)' },
  { value: 'UTC',                 label: 'UTC' },
]

interface Props {
  space: CreatorSpaceDetail
}

export default function OperatingDetailsForm({ space }: Props) {
  const router = useRouter()
  const [style, setStyle] = useState<ConnectionStyle>(space.connection_style ?? 'online')
  const [place, setPlace] = useState<PickedPlace | null>(space.primary_place ?? null)
  const [timezone, setTimezone] = useState<string>(space.timezone ?? 'Australia/Melbourne')
  const [saving, setSaving] = useState(false)
  const [saved, setSaved]   = useState(false)
  const [error, setError]   = useState<string | null>(null)

  const dirty =
    style !== (space.connection_style ?? 'online') ||
    (place?.id ?? null) !== (space.primary_place?.id ?? null) ||
    timezone !== (space.timezone ?? 'Australia/Melbourne')

  const needsLocation = style === 'in_person' || style === 'both'
  const canSave =
    dirty &&
    !saving &&
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
          primary_place_id: needsLocation && place ? place.id : '',
          timezone,
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
      aria-labelledby="operating-details-heading"
    >
      <h2
        id="operating-details-heading"
        className="mb-1 text-[17px] font-semibold text-navy-900"
      >
        Where does this Collective operate?
      </h2>
      <p
        className="mb-6 text-[14px] italic leading-relaxed"
        style={{ color: 'rgba(12,24,38,0.62)', fontFamily: 'Georgia, serif' }}
      >
        Practical operating details. Kept separate from the
        Collective&rsquo;s island, atmosphere and colour palette on
        the Place &amp; Feel tab.
      </p>

      {/* Connection style — required active choice */}
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

      {/* Geographic location — only when connection style needs it */}
      {needsLocation && (
        <div className="mb-6">
          <p className="mb-2 text-[14px] font-semibold text-navy-900">
            Geographic location
          </p>
          <LocationPicker
            value={place}
            onChange={setPlace}
            helperText="Pick the city or region this Collective is based in. A single searchable field is enough — Fresh Collective handles the rest behind the scenes."
          />
        </div>
      )}

      {/* Timezone — always visible; controls how gathering times display */}
      <div className="mb-6">
        <label htmlFor="operating-timezone" className="mb-2 block text-[14px] font-semibold text-navy-900">
          Timezone
        </label>
        <select
          id="operating-timezone"
          value={timezone}
          onChange={(e) => setTimezone(e.target.value)}
          className="w-full max-w-md rounded-xl border border-slate-200 bg-slate-50/70 px-4 py-2.5 text-[14px] text-navy-900 transition-colors focus:border-teal-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-teal-400/20"
        >
          {TIMEZONE_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>{opt.label}</option>
          ))}
        </select>
        <p className="mt-1.5 text-[12px] text-black">
          Used to display gathering dates and times for members.
        </p>
      </div>

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
            Pick a geographic location to save.
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
