'use client'

/**
 * Stay Connected — client component that renders one card per
 * collective the member belongs to, with autosave against the
 * existing per-collective preferences API.
 *
 * Deliberately minimal:
 *   - No new backend model; reads/writes the existing
 *     ``SpaceMemberNotificationPrefs`` shape via the existing
 *     ``/api/spaces/{slug}/notification-settings`` endpoints.
 *   - No preference consolidation; the underlying stored values are
 *     preserved unchanged.
 *   - No global "email rhythm" enum, no per-collective mute — those
 *     were considered and deferred per the current task's constraints.
 *   - ``weekly_digest_email`` / ``daily_digest_email`` are stored on
 *     the backend but the delivery jobs do not yet exist. The controls
 *     are OMITTED from this page (see the page-level comment for
 *     rationale). Stored values are preserved untouched.
 */

import { useCallback, useState } from 'react'
import { apiUrl } from '@/lib/api'
import { Switch } from '@/components/platform'
import type { NotificationPrefs, SpaceMembership } from '@/types/platform'

// ---------------------------------------------------------------------------
// Types + section catalogue
// ---------------------------------------------------------------------------

/** The five boolean fields we surface today.
 *
 *  Fields stored on the underlying record but intentionally NOT shown:
 *   - ``weekly_digest_email`` / ``daily_digest_email`` — no delivery
 *     job exists yet; showing a toggle that does nothing is confusing.
 *   - ``pathway_comment_email`` — no trigger reads this preference on
 *     the backend today. Hidden until the trigger is added; the DB
 *     column is preserved so no migration is required.
 */
type SurfacedPrefKey =
  | 'admin_broadcast_email'
  | 'gathering_reminder_email'
  | 'new_post_email'
  | 'comment_reply_email'
  | 'new_pathway_email'

interface PrefControl {
  key: SurfacedPrefKey
  label: string
  description: string
}

interface Section {
  label: string
  controls: PrefControl[]
}

const SECTIONS: Section[] = [
  {
    label: 'Community Updates',
    controls: [
      {
        key: 'admin_broadcast_email',
        label: 'Creator announcements',
        description: 'Important updates from the creator or moderators.',
      },
    ],
  },
  {
    label: 'Gatherings',
    controls: [
      {
        key: 'gathering_reminder_email',
        label: 'Gathering reminders',
        description: 'Email reminders for upcoming live gatherings.',
      },
    ],
  },
  {
    label: 'Conversations',
    controls: [
      {
        key: 'new_post_email',
        label: 'New conversations',
        description: 'Hear when someone starts a new conversation.',
      },
      {
        key: 'comment_reply_email',
        label: 'Replies to you',
        description: 'Hear when someone responds to something you\u2019ve shared.',
      },
    ],
  },
  {
    label: 'Pathways',
    controls: [
      {
        key: 'new_pathway_email',
        label: 'New pathways',
        description: 'Hear when a new pathway is added.',
      },
    ],
  },
]

// ---------------------------------------------------------------------------
// Chevron — matches the inline-SVG house style used elsewhere.
// ---------------------------------------------------------------------------

function Chevron({ open }: { open: boolean }) {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className={[
        'shrink-0 text-slate-500 transition-transform duration-150',
        open ? '-rotate-180' : 'rotate-0',
      ].join(' ')}
    >
      <polyline points="6 9 12 15 18 9" />
    </svg>
  )
}

// ---------------------------------------------------------------------------
// Toggle
// ---------------------------------------------------------------------------

// Toggle used to live here inline; it duplicated (and mis-sized) the
// shared platform Switch. Replaced with `Switch` so thumb positioning
// stays consistent across notification settings and every other
// toggle-using surface. The small local adapter preserves the
// existing `(v: boolean) => void` callsite ergonomics.
function Toggle({
  id, checked, onChange, disabled,
}: {
  id: string
  checked: boolean
  onChange: (v: boolean) => void
  disabled?: boolean
}) {
  return (
    <Switch
      id={id}
      checked={checked}
      disabled={disabled}
      onChange={(e) => onChange(e.target.checked)}
    />
  )
}

// ---------------------------------------------------------------------------
// Per-collective card
// ---------------------------------------------------------------------------

interface CardProps {
  membership: SpaceMembership
  initialPrefs: NotificationPrefs | null
  /** Whether the accordion is open. Controlled from the parent so the
   *  page can render the first card open + the rest closed on mount. */
  open: boolean
  onToggleOpen: () => void
}

function CollectiveCard({ membership, initialPrefs, open, onToggleOpen }: CardProps) {
  const [prefs, setPrefs] = useState<NotificationPrefs | null>(initialPrefs)
  const [savingKey, setSavingKey] = useState<SurfacedPrefKey | null>(null)
  const [savedKey, setSavedKey] = useState<SurfacedPrefKey | null>(null)
  const [error, setError] = useState<string | null>(null)

  const handleToggle = useCallback(async (key: SurfacedPrefKey, value: boolean) => {
    if (!prefs) return
    const previous = prefs
    setPrefs({ ...prefs, [key]: value })
    setSavingKey(key)
    setSavedKey(null)
    setError(null)
    try {
      const res = await fetch(
        apiUrl(`/api/spaces/${membership.space_slug}/notification-settings`),
        {
          method: 'PATCH',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ [key]: value }),
        },
      )
      if (!res.ok) throw new Error(`Save failed (${res.status})`)
      const updated: NotificationPrefs = await res.json()
      setPrefs(updated)
      setSavedKey(key)
      // Clear the saved indicator after a moment so it doesn't linger.
      window.setTimeout(() => {
        setSavedKey((current) => (current === key ? null : current))
      }, 1800)
    } catch {
      setPrefs(previous)
      setError('That change didn\u2019t save. Please try again.')
    } finally {
      setSavingKey((current) => (current === key ? null : current))
    }
  }, [prefs, membership.space_slug])

  const idPrefix = `stay-connected-${membership.space_slug}`
  const headerId = `${idPrefix}-header`
  const regionId = `${idPrefix}-region`
  const failedToLoad = initialPrefs === null && prefs === null

  // Failed-to-load card: no collapse chrome, no clickable header — the
  // error is the most important thing to see. The heading uses the same
  // typography as the collapsed accordion header for visual consistency.
  if (failedToLoad) {
    return (
      <section
        className="rounded-2xl border border-border bg-white p-6"
        aria-labelledby={headerId}
      >
        <h2
          id={headerId}
          className="font-serif text-[18px] leading-tight text-navy-900"
        >
          {membership.space_name}
        </h2>
        <p
          role="alert"
          className="mt-3 text-[13px] leading-relaxed text-red-700"
        >
          We couldn&rsquo;t load your preferences for this collective. Please refresh the page.
        </p>
      </section>
    )
  }

  return (
    <section
      className="overflow-hidden rounded-2xl border border-border bg-white"
      aria-labelledby={headerId}
    >
      {/* Header — a real button so keyboard Enter/Space toggles and
          screen readers announce the disclosure. Whole row is clickable. */}
      <h2 id={headerId}>
        <button
          type="button"
          onClick={onToggleOpen}
          aria-expanded={open}
          aria-controls={regionId}
          className="flex w-full items-center justify-between gap-3 px-6 py-5 text-left transition-colors hover:bg-slate-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400 focus-visible:ring-inset"
        >
          <span className="font-serif text-[18px] leading-tight text-navy-900">
            {membership.space_name}
          </span>
          <Chevron open={open} />
        </button>
      </h2>

      {/* Collapsible region. Hidden with `hidden` instead of `display:none`
          so `aria-controls` still points to a real element in the DOM. */}
      <div
        id={regionId}
        role="region"
        aria-labelledby={headerId}
        hidden={!open}
        className="px-6 pb-6"
      >
        {error && (
          <p role="alert" className="mb-4 text-[12.5px] text-red-700">
            {error}
          </p>
        )}

        <div className="divide-y divide-slate-100">
          {SECTIONS.map((section) => (
            <div key={section.label} className="py-3 first:pt-0 last:pb-0">
              <p className="mb-1 text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-500">
                {section.label}
              </p>
              {section.controls.map((c) => (
                <div key={c.key} className="flex items-start gap-4 py-2.5">
                  <div className="min-w-0 flex-1">
                    <label
                      htmlFor={`${idPrefix}-${c.key}`}
                      className="block cursor-pointer text-[13.5px] font-medium text-navy-900"
                    >
                      {c.label}
                    </label>
                    <p
                      id={`${idPrefix}-${c.key}-desc`}
                      className="mt-0.5 text-[12px] leading-relaxed text-slate-600"
                    >
                      {c.description}
                    </p>
                    {/* Screen-reader-only status. Visible "Saved" flash sits
                        opposite the toggle; this line is what assistive tech
                        hears, so it never relies on colour alone. */}
                    <span
                      aria-live="polite"
                      aria-atomic="true"
                      className="sr-only"
                    >
                      {savingKey === c.key ? 'Saving' : savedKey === c.key ? 'Saved' : ''}
                    </span>
                  </div>
                  <div className="flex shrink-0 items-center gap-2 pt-1">
                    <span
                      className={[
                        'text-[11px] font-medium transition-opacity',
                        savedKey === c.key ? 'opacity-100 text-teal-700' : 'opacity-0',
                      ].join(' ')}
                      aria-hidden="true"
                    >
                      Saved
                    </span>
                    <Toggle
                      id={`${idPrefix}-${c.key}`}
                      checked={Boolean(prefs?.[c.key])}
                      onChange={(v) => void handleToggle(c.key, v)}
                      disabled={!prefs || savingKey === c.key}
                    />
                  </div>
                </div>
              ))}
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}

// ---------------------------------------------------------------------------
// Top-level list
// ---------------------------------------------------------------------------

interface Props {
  collectives: {
    membership: SpaceMembership
    prefs: NotificationPrefs | null
  }[]
}

export default function StayConnectedClient({ collectives }: Props) {
  // Default open-state:
  //   - The first successfully-loaded card opens on mount.
  //   - Every other successfully-loaded card starts collapsed.
  //   - A single collective is always open (falls out of the first rule).
  //   - Error cards render outside the accordion — see CollectiveCard —
  //     so no entry is needed for them here.
  //
  // Kept in useState so React initialises it exactly once. Toggling a
  // card mutates a shallow copy; per-card state (autosave, error) lives
  // on the card itself and survives collapse/expand.
  const [openMap, setOpenMap] = useState<Record<string, boolean>>(() => {
    const map: Record<string, boolean> = {}
    let firstOpenAssigned = false
    for (const c of collectives) {
      const loaded = c.prefs !== null
      if (loaded && !firstOpenAssigned) {
        map[c.membership.space_id] = true
        firstOpenAssigned = true
      } else {
        map[c.membership.space_id] = false
      }
    }
    return map
  })

  const toggleOpen = useCallback((spaceId: string) => {
    setOpenMap((prev) => ({ ...prev, [spaceId]: !prev[spaceId] }))
  }, [])

  if (collectives.length === 0) {
    return (
      <div className="rounded-2xl border border-dashed border-border bg-surface px-6 py-10 text-center">
        <p className="mb-2 font-serif text-[17px] text-navy-900">
          No collective preferences yet
        </p>
        <p className="mx-auto max-w-md text-[13.5px] leading-relaxed text-black">
          Your connection choices will appear here when you join a collective.
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {collectives.map((c) => (
        <CollectiveCard
          key={c.membership.space_id}
          membership={c.membership}
          initialPrefs={c.prefs}
          open={openMap[c.membership.space_id] ?? false}
          onToggleOpen={() => toggleOpen(c.membership.space_id)}
        />
      ))}
    </div>
  )
}
