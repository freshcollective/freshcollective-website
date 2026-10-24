'use client'

/**
 * Collective welcome emails — the one setting on this page that is not
 * per-Collective.
 *
 * Every other control here belongs to a membership: it reads and writes
 * ``SpaceMemberNotificationPrefs`` for one (user, space) pair through
 * ``/api/spaces/{slug}/notification-settings``. This one cannot work
 * that way, because it governs Collectives the member has not joined
 * yet — "when you join a new Collective" has no space to attach to.
 *
 * So it reads the member's communications matrix instead:
 *
 *   GET   /api/comms/preferences/me   → find the
 *         (collective_welcome × email_transactional) cell
 *   PATCH /api/comms/preferences/me   → set that cell's priority
 *
 * Both endpoints already existed; nothing of Milestone 7's unfinished
 * preference architecture is built or rebuilt here. ``immediate`` and
 * ``silent`` are the only two priorities this control uses — on and
 * off — and clearing the override is deliberately not offered, because
 * "back to default" is not a state a member needs to name when the
 * default is simply "on".
 *
 * It sits above the per-Collective cards because it applies to all of
 * them and to the ones not yet joined.
 */

import { useCallback, useEffect, useState } from 'react'
import { apiUrl } from '@/lib/api'
import { Switch } from '@/components/platform'

const CATEGORY = 'collective_welcome'
const CHANNEL = 'email_transactional'
const ON = 'immediate'
const OFF = 'silent'

interface PreferenceCell {
  channel: string
  priority: string
  is_locked: boolean
  origin: 'override' | 'default'
}

interface PreferenceCategoryRow {
  category_key: string
  cells: PreferenceCell[]
}

interface MyPreferences {
  categories: PreferenceCategoryRow[]
}

function readCell(body: MyPreferences): PreferenceCell | null {
  const row = body.categories.find((c) => c.category_key === CATEGORY)
  return row?.cells.find((c) => c.channel === CHANNEL) ?? null
}

export default function WelcomeEmailPreference() {
  const [enabled, setEnabled] = useState(true)
  const [locked, setLocked] = useState(false)
  const [loaded, setLoaded] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // Absent when the category has not been seeded — an older backend,
  // or a frontend deployed ahead of migration 165. The control hides
  // itself rather than offering a switch that writes nowhere.
  const [present, setPresent] = useState(true)

  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const res = await fetch(apiUrl('/api/comms/preferences/me'), {
          credentials: 'include',
        })
        if (!res.ok) throw new Error(String(res.status))
        const body: MyPreferences = await res.json()
        const cell = readCell(body)
        if (cancelled) return
        if (cell === null) {
          setPresent(false)
          return
        }
        setEnabled(cell.priority !== OFF)
        setLocked(cell.is_locked)
      } catch {
        // A read failure leaves the switch alone rather than guessing.
        // The member's real setting is whatever the server holds, and
        // showing "off" because a request failed would be a lie they
        // might act on.
        if (!cancelled) setPresent(false)
      } finally {
        if (!cancelled) setLoaded(true)
      }
    })()
    return () => { cancelled = true }
  }, [])

  const onToggle = useCallback(async (next: boolean) => {
    const previous = enabled
    setEnabled(next)
    setSaving(true)
    setSaved(false)
    setError(null)
    try {
      const res = await fetch(apiUrl('/api/comms/preferences/me'), {
        method: 'PATCH',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          preferences: [{
            category_key: CATEGORY,
            channel: CHANNEL,
            priority: next ? ON : OFF,
          }],
        }),
      })
      if (!res.ok) throw new Error(String(res.status))
      const body: MyPreferences = await res.json()
      const cell = readCell(body)
      // Trust what came back, not what was sent.
      if (cell) setEnabled(cell.priority !== OFF)
      setSaved(true)
      window.setTimeout(() => setSaved(false), 1800)
    } catch {
      setEnabled(previous)
      setError('That change didn’t save. Please try again.')
    } finally {
      setSaving(false)
    }
  }, [enabled])

  if (!present) return null

  return (
    <section className="mb-5 rounded-2xl border border-slate-200 bg-white px-5 py-4">
      <h2 className="text-[15px] font-medium text-navy-900">
        Welcome emails
      </h2>
      <div className="mt-3 flex items-start gap-4">
        <div className="min-w-0 flex-1">
          <label
            htmlFor="stay-connected-collective-welcome"
            className="block cursor-pointer text-[13.5px] font-medium text-navy-900"
          >
            Collective welcome emails
          </label>
          <p className="mt-0.5 text-[12px] leading-relaxed text-slate-600">
            Receive a welcome email when you join a new Collective.
          </p>
          <span aria-live="polite" aria-atomic="true" className="sr-only">
            {saving ? 'Saving' : saved ? 'Saved' : ''}
          </span>
          {error && (
            <p className="mt-1 text-[12px] text-rose-700">{error}</p>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-2 pt-1">
          <span
            className={[
              'text-[11px] font-medium transition-opacity',
              saved ? 'opacity-100 text-teal-700' : 'opacity-0',
            ].join(' ')}
            aria-hidden="true"
          >
            Saved
          </span>
          <Switch
            id="stay-connected-collective-welcome"
            checked={enabled}
            disabled={!loaded || saving || locked}
            onChange={(e) => void onToggle(e.target.checked)}
          />
        </div>
      </div>
    </section>
  )
}
