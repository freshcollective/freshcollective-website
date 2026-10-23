'use client'

import { useCallback, useEffect, useState } from 'react'

import { apiUrl } from '@/lib/api'

/**
 * The welcome email this Collective sends to first-time members.
 *
 * Its own save, like JoinPolicyForm and for the same reason: the copy
 * and the on/off switch go to one endpoint of their own, and folding
 * them into the big settings form would put two unrelated saves behind
 * one button.
 *
 * What a creator controls here is **voice** — five slots and a switch.
 * The button's destination is not among them: it is generated from the
 * Collective's slug and shown read-only below the button label, so it
 * is visible without being editable. That is deliberate, and matches
 * the platform-wide stance that an editable slot carries wording, never
 * a link.
 *
 * Unsaved slots inherit. A Collective that rewrites only its subject
 * keeps receiving later improvements to Fresh Collective's heading, and
 * "Restore default" deletes this Collective's rows rather than copying
 * today's wording into them — which is what keeps that inheritance
 * alive afterwards.
 */

interface SlotView {
  slot_id: string
  label: string
  help_text: string
  multiline: boolean
  max_length: number
  value: string
  inherited_default: string
  customised: boolean
}

interface MergeFieldView {
  name: string
  description: string
  sample: string
}

interface WelcomeEmailDetail {
  space_slug: string
  collective_name: string
  enabled: boolean
  collective_url: string
  slots: SlotView[]
  merge_fields: MergeFieldView[]
  customised: boolean
}

interface PreviewResult {
  subject: string
  html: string
  text: string
  errors: Record<string, string[]>
}

export default function WelcomeEmailForm({ slug }: { slug: string }) {
  const base = apiUrl(`/api/creator/spaces/${slug}/welcome-email`)

  const [detail, setDetail] = useState<WelcomeEmailDetail | null>(null)
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [enabled, setEnabled] = useState(true)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string[]>>({})
  const [saved, setSaved] = useState(false)
  const [preview, setPreview] = useState<PreviewResult | null>(null)
  const [previewing, setPreviewing] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(base, { credentials: 'include' })
      if (!res.ok) throw new Error(`Could not load the welcome email (${res.status}).`)
      const body: WelcomeEmailDetail = await res.json()
      setDetail(body)
      setEnabled(body.enabled)
      setDrafts(Object.fromEntries(body.slots.map((s) => [s.slot_id, s.value])))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load the welcome email.')
    } finally {
      setLoading(false)
    }
  }, [base])

  useEffect(() => { void load() }, [load])

  async function save() {
    setSaving(true)
    setError(null)
    setFieldErrors({})
    setSaved(false)
    try {
      const res = await fetch(base, {
        method: 'PUT',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled, overrides: drafts }),
      })
      if (res.status === 422) {
        const body = await res.json()
        setFieldErrors(body?.detail?.errors ?? {})
        setError('Some wording needs a change before this can be saved.')
        return
      }
      if (!res.ok) throw new Error(`Could not save (${res.status}).`)
      const body: WelcomeEmailDetail = await res.json()
      setDetail(body)
      setEnabled(body.enabled)
      setDrafts(Object.fromEntries(body.slots.map((s) => [s.slot_id, s.value])))
      setSaved(true)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save.')
    } finally {
      setSaving(false)
    }
  }

  async function restoreDefault() {
    setSaving(true)
    setError(null)
    setFieldErrors({})
    try {
      const res = await fetch(base, { method: 'DELETE', credentials: 'include' })
      if (!res.ok) throw new Error(`Could not restore the default (${res.status}).`)
      const body: WelcomeEmailDetail = await res.json()
      setDetail(body)
      setDrafts(Object.fromEntries(body.slots.map((s) => [s.slot_id, s.value])))
      setPreview(null)
      setSaved(false)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not restore the default.')
    } finally {
      setSaving(false)
    }
  }

  async function showPreview() {
    setPreviewing(true)
    setError(null)
    try {
      const res = await fetch(`${base}/preview`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode: 'effective', drafts }),
      })
      if (!res.ok) throw new Error(`Could not build a preview (${res.status}).`)
      setPreview(await res.json())
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not build a preview.')
    } finally {
      setPreviewing(false)
    }
  }

  if (loading) {
    return (
      <section className="rounded-2xl border border-teal-100 bg-white p-5">
        <p className="text-[13.5px] text-navy-500">Loading the welcome email…</p>
      </section>
    )
  }
  if (!detail) {
    return (
      <section className="rounded-2xl border border-rose-200 bg-rose-50/60 p-5">
        <p className="text-[13.5px] text-rose-800">
          {error ?? 'The welcome email could not be loaded.'}
        </p>
      </section>
    )
  }

  return (
    <section className="rounded-2xl border border-teal-100 bg-white p-5">
      <h2 className="text-[17px] font-semibold text-navy-900">Welcome Email</h2>
      <p className="mt-1 max-w-2xl text-[13.5px] leading-relaxed text-navy-600">
        Sent once, the first time somebody becomes a member of{' '}
        {detail.collective_name} — however they arrived. Existing members
        are never sent it again, and somebody rejoining does not receive a
        second one.
      </p>

      {/* ── Enable / disable ── */}
      <label className="mt-4 flex items-start gap-3">
        <input
          type="checkbox"
          checked={enabled}
          onChange={(e) => { setEnabled(e.target.checked); setSaved(false) }}
          className="mt-0.5 h-4 w-4 rounded border-teal-300"
        />
        <span className="text-[13.5px] text-navy-700">
          Send a welcome email to new members
          <span className="mt-0.5 block text-[12.5px] text-navy-500">
            Turning this off stops future welcomes. It never sends a
            backlog to people who joined while it was off.
          </span>
        </span>
      </label>

      {/* ── Editable copy ── */}
      <div className={enabled ? 'mt-5 space-y-4' : 'mt-5 space-y-4 opacity-60'}>
        {detail.slots.map((slot) => {
          const problems = fieldErrors[slot.slot_id] ?? []
          const value = drafts[slot.slot_id] ?? ''
          return (
            <div key={slot.slot_id}>
              <div className="flex items-baseline justify-between gap-3">
                <label
                  htmlFor={`welcome-${slot.slot_id}`}
                  className="text-[13px] font-medium text-navy-800"
                >
                  {slot.label}
                </label>
                {slot.customised && (
                  <span className="text-[11.5px] text-teal-700">Customised</span>
                )}
              </div>
              {slot.help_text && (
                <p className="mt-0.5 text-[12.5px] text-navy-500">{slot.help_text}</p>
              )}
              {slot.multiline ? (
                <textarea
                  id={`welcome-${slot.slot_id}`}
                  value={value}
                  rows={slot.slot_id === 'body.message' ? 8 : 3}
                  maxLength={slot.max_length}
                  disabled={!enabled}
                  onChange={(e) => {
                    setDrafts({ ...drafts, [slot.slot_id]: e.target.value })
                    setSaved(false)
                  }}
                  className="mt-1.5 w-full rounded-lg border border-teal-200 px-3 py-2 text-[13.5px] leading-relaxed"
                />
              ) : (
                <input
                  id={`welcome-${slot.slot_id}`}
                  type="text"
                  value={value}
                  maxLength={slot.max_length}
                  disabled={!enabled}
                  onChange={(e) => {
                    setDrafts({ ...drafts, [slot.slot_id]: e.target.value })
                    setSaved(false)
                  }}
                  className="mt-1.5 w-full rounded-lg border border-teal-200 px-3 py-2 text-[13.5px]"
                />
              )}
              {problems.length > 0 && (
                <ul className="mt-1 space-y-0.5">
                  {problems.map((p) => (
                    <li key={p} className="text-[12.5px] text-rose-700">{p}</li>
                  ))}
                </ul>
              )}
            </div>
          )
        })}

        {/* The destination: shown, never editable. */}
        <div>
          <p className="text-[13px] font-medium text-navy-800">Button destination</p>
          <p className="mt-0.5 text-[12.5px] text-navy-500">
            Generated by Fresh Collective so a welcome always leads to your
            Collective.
          </p>
          <p className="mt-1.5 break-all rounded-lg bg-teal-50/60 px-3 py-2 text-[12.5px] text-navy-700">
            {detail.collective_url}
          </p>
        </div>
      </div>

      {/* ── Available merge fields ── */}
      {detail.merge_fields.length > 0 && (
        <div className="mt-5 rounded-lg bg-teal-50/40 px-3.5 py-3">
          <p className="text-[12.5px] font-medium text-navy-700">
            You can use these anywhere above
          </p>
          <ul className="mt-1.5 space-y-1">
            {detail.merge_fields.map((f) => (
              <li key={f.name} className="text-[12.5px] text-navy-600">
                <code className="text-teal-800">{`{{${f.name}}}`}</code>
                {' — '}{f.description}
              </li>
            ))}
          </ul>
        </div>
      )}

      {error && (
        <p className="mt-4 text-[13px] text-rose-700">{error}</p>
      )}
      {saved && !error && (
        <p className="mt-4 text-[13px] text-teal-700">Saved.</p>
      )}

      {/* ── Actions ── */}
      <div className="mt-5 flex flex-wrap items-center gap-2.5">
        <button
          type="button"
          onClick={() => void save()}
          disabled={saving}
          className="rounded-full px-4 py-1.5 text-[13px] font-medium text-white disabled:opacity-60"
          style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
        >
          {saving ? 'Saving…' : 'Save'}
        </button>
        <button
          type="button"
          onClick={() => void showPreview()}
          disabled={previewing}
          className="rounded-full border border-teal-200 bg-white px-4 py-1.5 text-[13px] font-medium text-teal-800 disabled:opacity-60"
        >
          {previewing ? 'Building…' : 'Preview'}
        </button>
        {detail.customised && (
          <button
            type="button"
            onClick={() => void restoreDefault()}
            disabled={saving}
            className="rounded-full border border-teal-200 bg-white px-4 py-1.5 text-[13px] text-navy-600 disabled:opacity-60"
          >
            Restore default
          </button>
        )}
      </div>

      {/* ── Preview ── */}
      {preview && (
        <div className="mt-5 rounded-xl border border-teal-100">
          <div className="border-b border-teal-100 px-4 py-2.5">
            <p className="text-[12.5px] text-navy-500">Subject</p>
            <p className="text-[13.5px] font-medium text-navy-900">
              {preview.subject}
            </p>
          </div>
          {Object.keys(preview.errors).length > 0 && (
            <p className="border-b border-teal-100 px-4 py-2.5 text-[12.5px] text-rose-700">
              Some wording was left out of this preview because it needs a
              change first.
            </p>
          )}
          {/* Rendered through the same template and shell a real send
              uses, so what is shown here is what a member receives. */}
          <iframe
            title="Welcome email preview"
            srcDoc={preview.html}
            className="h-[520px] w-full rounded-b-xl"
          />
        </div>
      )}
    </section>
  )
}
