'use client'

import { useEffect, useState, useCallback } from 'react'
import { apiUrl } from '@/lib/api'
import type { NotificationPrefs } from '@/types/platform'

// ---------------------------------------------------------------------------
// Toggle — matches the style used across the platform
// ---------------------------------------------------------------------------

interface ToggleProps {
  checked: boolean
  onChange: (val: boolean) => void
  disabled?: boolean
  id: string
}

function Toggle({ checked, onChange, disabled, id }: ToggleProps) {
  return (
    <button
      type="button"
      role="switch"
      id={id}
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={[
        'relative h-6 w-10 shrink-0 rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-teal-300 focus:ring-offset-1 disabled:opacity-40',
        checked ? 'bg-teal-500' : 'bg-slate-200',
      ].join(' ')}
    >
      <span
        className={[
          'absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform',
          checked ? 'translate-x-4' : 'translate-x-0.5',
        ].join(' ')}
      />
    </button>
  )
}

// ---------------------------------------------------------------------------
// Toggle row
// ---------------------------------------------------------------------------

interface ToggleRowProps {
  id: string
  label: string
  description: string
  checked: boolean
  onChange: (val: boolean) => void
  disabled?: boolean
}

function ToggleRow({ id, label, description, checked, onChange, disabled }: ToggleRowProps) {
  return (
    <div className="flex items-start gap-4 py-3">
      <div className="flex-1 min-w-0">
        <label htmlFor={id} className="block text-[14px] font-medium text-navy-900 cursor-pointer">
          {label}
        </label>
        <p className="mt-0.5 text-[12px] leading-relaxed text-slate-400">{description}</p>
      </div>
      <div className="mt-0.5">
        <Toggle id={id} checked={checked} onChange={onChange} disabled={disabled} />
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Section header
// ---------------------------------------------------------------------------

function SectionHeader({ label }: { label: string }) {
  return (
    <p className="mb-1 pt-5 text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-400 first:pt-0">
      {label}
    </p>
  )
}

// ---------------------------------------------------------------------------
// Active tab types — extend here when Invite / Membership are added
// ---------------------------------------------------------------------------

type Tab = 'notifications'

// ---------------------------------------------------------------------------
// Main modal
// ---------------------------------------------------------------------------

interface Props {
  spaceSlug: string
  spaceName: string
  onClose: () => void
}

export default function CollectiveSettingsModal({ spaceSlug, spaceName, onClose }: Props) {
  const [activeTab, setActiveTab] = useState<Tab>('notifications')
  const [prefs, setPrefs] = useState<NotificationPrefs | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [savedAt, setSavedAt] = useState<number | null>(null)

  // Load on mount
  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    fetch(apiUrl(`/api/spaces/${spaceSlug}/notification-settings`), {
      credentials: 'include',
    })
      .then((r) => {
        if (!r.ok) throw new Error(`Failed to load (${r.status})`)
        return r.json()
      })
      .then((data: NotificationPrefs) => {
        if (!cancelled) { setPrefs(data); setLoading(false) }
      })
      .catch((err) => {
        if (!cancelled) { setError(err.message ?? 'Could not load settings.'); setLoading(false) }
      })
    return () => { cancelled = true }
  }, [spaceSlug])

  // Auto-save a single field change
  const handleToggle = useCallback(
    async (field: keyof NotificationPrefs, value: boolean) => {
      if (!prefs) return
      const next = { ...prefs, [field]: value }
      setPrefs(next)
      try {
        const res = await fetch(apiUrl(`/api/spaces/${spaceSlug}/notification-settings`), {
          method: 'PATCH',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ [field]: value }),
        })
        if (!res.ok) throw new Error()
        const updated: NotificationPrefs = await res.json()
        setPrefs(updated)
        setSavedAt(Date.now())
      } catch {
        setPrefs(prefs) // revert on error
      }
    },
    [prefs, spaceSlug],
  )

  // Close saved flash after 2 s
  useEffect(() => {
    if (!savedAt) return
    const t = setTimeout(() => setSavedAt(null), 2000)
    return () => clearTimeout(t)
  }, [savedAt])

  // Trap ESC
  useEffect(() => {
    function onKey(e: KeyboardEvent) { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const tabs: { id: Tab; label: string }[] = [
    { id: 'notifications', label: 'Notifications' },
    // Future: { id: 'invite', label: 'Invite' },
    // Future: { id: 'membership', label: 'Membership' },
  ]

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center md:items-center md:px-4 md:py-6"
      style={{ background: 'rgba(7,24,36,0.55)' }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div
        className="flex w-full flex-col overflow-hidden rounded-t-2xl bg-white shadow-2xl md:max-w-2xl md:rounded-2xl"
        style={{ maxHeight: '90vh' }}
      >
        {/* Mobile drag handle */}
        <div className="flex shrink-0 justify-center pt-3 md:hidden" aria-hidden="true">
          <div className="h-1 w-10 rounded-full bg-slate-200" />
        </div>

        {/* ── Header ── */}
        <div
          className="flex shrink-0 items-center justify-between border-b border-border px-6 py-4"
        >
          <div>
            <div
              className="mb-1 h-[2px] w-5 rounded-full"
              style={{ background: 'linear-gradient(90deg, #BF9830 0%, transparent 100%)' }}
            />
            <h2 className="text-[15px] font-semibold text-navy-900">{spaceName}</h2>
          </div>
          <button
            onClick={onClose}
            className="text-slate-400 transition-colors hover:text-navy-900"
            aria-label="Close"
          >
            ✕
          </button>
        </div>

        {/* ── Body: tab rail + content ── */}
        {/* Mobile: vertical stack (tab rail on top). Desktop: side-by-side. */}
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden md:flex-row">

          {/* Tab rail — horizontal on mobile, vertical sidebar on desktop */}
          <div className="flex shrink-0 flex-row overflow-x-auto border-b border-border bg-slate-50/60 px-3 py-2 md:w-40 md:flex-col md:overflow-visible md:border-b-0 md:border-r md:py-4">
            {tabs.map((t) => (
              <button
                key={t.id}
                onClick={() => setActiveTab(t.id)}
                className={[
                  'shrink-0 rounded-xl px-3 py-1.5 text-left text-[13px] font-medium transition-colors md:w-full md:py-2',
                  activeTab === t.id
                    ? 'bg-white text-navy-900 shadow-sm'
                    : 'text-slate-500 hover:text-navy-800',
                ].join(' ')}
              >
                {t.label}
              </button>
            ))}
          </div>

          {/* Content pane — full width on mobile */}
          <div className="flex-1 overflow-y-auto px-6 py-5">
            {activeTab === 'notifications' && (
              <>
                <div className="mb-4 flex items-center justify-between">
                  <p className="text-[13px] leading-relaxed text-slate-500">
                    Choose what you want to hear about from this collective.
                  </p>
                  {savedAt && (
                    <span className="text-[12px] font-medium text-teal-600">Saved</span>
                  )}
                </div>

                {loading && (
                  <div className="py-8 text-center text-[13px] text-slate-400">Loading…</div>
                )}

                {!loading && error && (
                  <div className="rounded-xl px-4 py-3 text-[13px] text-red-600"
                    style={{ background: 'rgba(239,68,68,0.06)', border: '1px solid rgba(239,68,68,0.18)' }}>
                    {error}
                  </div>
                )}

                {!loading && !error && prefs && (
                  <div className="divide-y divide-border">

                    <div>
                      <SectionHeader label="Email updates" />
                      <ToggleRow
                        id="weekly_digest_email"
                        label="Weekly digest email"
                        description="A weekly summary of what's happening inside this collective."
                        checked={prefs.weekly_digest_email}
                        onChange={(v) => handleToggle('weekly_digest_email', v)}
                      />
                      <ToggleRow
                        id="daily_digest_email"
                        label="Daily notifications email"
                        description="A daily summary when there is activity to catch up on."
                        checked={prefs.daily_digest_email}
                        onChange={(v) => handleToggle('daily_digest_email', v)}
                      />
                      <ToggleRow
                        id="admin_broadcast_email"
                        label="Admin broadcast email"
                        description="Important updates from the creator or moderators."
                        checked={prefs.admin_broadcast_email}
                        onChange={(v) => handleToggle('admin_broadcast_email', v)}
                      />
                    </div>

                    <div>
                      <SectionHeader label="Gatherings" />
                      <ToggleRow
                        id="gathering_reminder_email"
                        label="Gathering reminder email"
                        description="Reminders for upcoming live gatherings."
                        checked={prefs.gathering_reminder_email}
                        onChange={(v) => handleToggle('gathering_reminder_email', v)}
                      />
                    </div>

                    <div>
                      <SectionHeader label="Community" />
                      <ToggleRow
                        id="new_post_email"
                        label="New post email"
                        description="Get notified when someone shares something new."
                        checked={prefs.new_post_email}
                        onChange={(v) => handleToggle('new_post_email', v)}
                      />
                      <ToggleRow
                        id="comment_reply_email"
                        label="Comment reply email"
                        description="Get notified when someone replies to you."
                        checked={prefs.comment_reply_email}
                        onChange={(v) => handleToggle('comment_reply_email', v)}
                      />
                    </div>

                    <div>
                      <SectionHeader label="Pathways" />
                      <ToggleRow
                        id="pathway_comment_email"
                        label="Pathway comment email"
                        description="Get notified when someone comments on a pathway step."
                        checked={prefs.pathway_comment_email}
                        onChange={(v) => handleToggle('pathway_comment_email', v)}
                      />
                      <ToggleRow
                        id="new_pathway_email"
                        label="New pathway email"
                        description="Get notified when a new pathway is added."
                        checked={prefs.new_pathway_email}
                        onChange={(v) => handleToggle('new_pathway_email', v)}
                      />
                    </div>

                    {/* Push — coming soon */}
                    <div>
                      <SectionHeader label="Push notifications" />
                      <div className="py-3">
                        <p className="text-[13px] text-slate-400">
                          Push notifications — coming soon.
                        </p>
                      </div>
                    </div>

                  </div>
                )}

                {/* Honest delivery note */}
                <div className="mt-6 rounded-xl px-4 py-3"
                  style={{ background: 'rgba(55,160,158,0.06)', border: '1px solid rgba(55,160,158,0.12)' }}>
                  <p className="text-[12px] leading-relaxed text-slate-500">
                    Your preferences are saved immediately. Email delivery will be connected as notification features are released.
                  </p>
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
