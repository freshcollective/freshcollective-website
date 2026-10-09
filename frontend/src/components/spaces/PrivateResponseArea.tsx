'use client'

import { useState, type ReactNode } from 'react'

/**
 * The member writes something, saves it, and is told it saved.
 *
 * Extracted from ``StepActions``'s Pause & Reflect panel so Exercise
 * blocks can offer the same thing without a second copy of it. The two
 * callers differ in where they POST and in the chrome around them;
 * everything a member actually touches is here.
 *
 * Deliberately *controlled* for the text value rather than owning it.
 * Pause & Reflect's "Mark complete" also sends the current reflection
 * (``handleComplete`` posts ``reflection_text``), so the step page has
 * to be able to read what is in the box. Owning the value here would
 * have quietly broken that: completing a step would have stopped
 * persisting what the member had just written.
 *
 * What this component does own is the save feedback — in-flight, saved,
 * failed — because that is the part both callers were going to
 * reimplement slightly differently. ``onSave`` reports success and this
 * decides what the member sees.
 *
 * Explicit save only. There is no autosave here: both surfaces are
 * journalling, where a save the member did not ask for is worse than
 * one they did.
 */

export interface PrivateResponseAreaProps {
  /** Ties the visible label to the textarea. Must be unique on the page
   *  — Exercise blocks pass their block id, since a step can hold
   *  several. */
  textareaId: string
  /** The heading above the box. */
  label: ReactNode
  labelClassName?: string
  /** Optional line between the label and the box. */
  intro?: ReactNode
  value: string
  onChange: (next: string) => void
  /** Persist the current value. Resolve ``true`` when it saved. */
  onSave: () => Promise<boolean>
  saveLabel: string
  placeholder: string
  rows?: number
  /** Shown beside the label. The promise, not decoration. */
  privacyLabel?: string
  /** Read-only rendering for the Creator Studio preview: the member
   *  experience is visible, but nothing can be typed or sent. */
  readOnly?: boolean
}

export default function PrivateResponseArea({
  textareaId,
  label,
  labelClassName = 'font-serif text-[20px] leading-snug text-navy-900',
  intro,
  value,
  onChange,
  onSave,
  saveLabel,
  placeholder,
  rows = 6,
  privacyLabel = 'Private to you',
  readOnly = false,
}: PrivateResponseAreaProps) {
  // Three states, not two. The old reflection handler set "Saved." only
  // on ``res.ok`` and did nothing at all otherwise, so a failed save was
  // indistinguishable from never having pressed the button. A member
  // who writes something, saves, sees nothing and closes the tab has
  // lost it.
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [failed, setFailed] = useState(false)

  async function handleSave() {
    if (readOnly || saving) return
    setSaving(true)
    setFailed(false)
    setSaved(false)
    let ok = false
    try {
      ok = await onSave()
    } catch {
      ok = false
    }
    setSaving(false)
    if (ok) {
      setSaved(true)
      // Same 2.5s dwell the reflection panel has always used.
      setTimeout(() => setSaved(false), 2500)
    } else {
      setFailed(true)
    }
  }

  return (
    <>
      <div className="mb-4">
        <label htmlFor={textareaId} className={labelClassName}>
          {label}
        </label>
        {privacyLabel && (
          <p
            className="mt-1 text-[12px] font-medium uppercase tracking-[0.14em]"
            style={{ color: 'var(--fc-accent, #0f766e)' }}
          >
            {privacyLabel}
          </p>
        )}
      </div>

      {intro && (
        <p className="mb-5 text-[15px] leading-relaxed text-navy-900/80">{intro}</p>
      )}

      <textarea
        id={textareaId}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        rows={rows}
        placeholder={placeholder}
        readOnly={readOnly}
        aria-readonly={readOnly || undefined}
        className="w-full resize-none rounded-xl border bg-white px-5 py-4 text-[15px] leading-relaxed text-navy-900 placeholder:text-slate-300 transition-colors focus:outline-none focus:ring-2 read-only:cursor-default read-only:bg-slate-50"
        style={{
          borderColor: 'var(--fc-accent-line, rgba(56,160,158,0.20))',
          fontFamily: 'inherit',
        }}
      />

      <div className="mt-3 flex items-center justify-between gap-3">
        <button
          type="button"
          onClick={handleSave}
          disabled={readOnly || saving || !value.trim()}
          className="rounded-full px-4 py-1.5 text-[13px] font-medium text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
          style={{
            background:
              'linear-gradient(135deg, var(--fc-accent, #38A09E) 0%, var(--fc-accent-strong, #55B8B6) 100%)',
          }}
        >
          {saving ? 'Saving…' : saveLabel}
        </button>
        {saved && (
          <span
            className="text-[12px]"
            style={{ color: 'var(--fc-accent, #0f766e)' }}
            role="status"
          >
            Saved.
          </span>
        )}
        {failed && (
          <span className="text-[12px] text-amber-700" role="alert">
            That didn’t save. Your writing is still here — try again.
          </span>
        )}
      </div>
    </>
  )
}
