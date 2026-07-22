'use client'

import { useState } from 'react'

/**
 * PollComposer — the config surface embedded inside CreatePostForm when
 * the composer's type is set to `poll`. Emits the poll input structure
 * the API expects (see backend `PollInput`).
 *
 * Kept intentionally simple: no drag-and-drop reorder, no per-option
 * subtitles, no vote-limits. Add these later if members ask for them.
 */

export interface PollComposerValue {
  options: { label: string }[]
  allow_multiple: boolean
  is_anonymous: boolean
  show_results_before_vote: boolean
  closes_at: string | null // ISO string
}

export const EMPTY_POLL: PollComposerValue = {
  options: [{ label: '' }, { label: '' }],
  allow_multiple: false,
  is_anonymous: false,
  show_results_before_vote: false,
  closes_at: null,
}

interface Props {
  value: PollComposerValue
  onChange: (next: PollComposerValue) => void
}

export default function PollComposer({ value, onChange }: Props) {
  const [showClose, setShowClose] = useState(!!value.closes_at)

  const setOption = (i: number, label: string) => {
    const options = [...value.options]
    options[i] = { label }
    onChange({ ...value, options })
  }
  const addOption = () => {
    if (value.options.length >= 20) return
    onChange({ ...value, options: [...value.options, { label: '' }] })
  }
  const removeOption = (i: number) => {
    if (value.options.length <= 2) return
    const options = value.options.filter((_, idx) => idx !== i)
    onChange({ ...value, options })
  }

  return (
    <div
      className="mt-3 rounded-lg px-4 py-4"
      style={{ background: 'rgba(212,176,72,0.06)', border: '1px solid rgba(212,176,72,0.20)' }}
    >
      <p className="mb-3 text-[11px] font-semibold uppercase tracking-[0.16em] text-black">
        Poll options
      </p>

      <div className="space-y-2">
        {value.options.map((opt, i) => (
          <div key={i} className="flex items-center gap-2">
            <span className="text-[12px] text-slate-400 w-4 text-right">{i + 1}.</span>
            <input
              type="text"
              value={opt.label}
              onChange={(e) => setOption(i, e.target.value)}
              placeholder={`Option ${i + 1}`}
              maxLength={300}
              className="flex-1 rounded-lg border border-slate-200 bg-white px-3 py-2 text-[13px] text-navy-900 placeholder:text-slate-300 focus:border-teal-400 focus:outline-none focus:ring-2 focus:ring-teal-100"
            />
            {value.options.length > 2 && (
              <button
                type="button"
                onClick={() => removeOption(i)}
                className="text-[12px] text-slate-400 hover:text-red-500"
                aria-label={`Remove option ${i + 1}`}
              >
                ✕
              </button>
            )}
          </div>
        ))}
      </div>

      <button
        type="button"
        onClick={addOption}
        disabled={value.options.length >= 20}
        className="mt-3 text-[12px] font-medium disabled:opacity-40"
        style={{ color: 'var(--fc-accent, #0f766e)' }}
      >
        + Add option
      </button>

      <div className="mt-4 grid grid-cols-1 gap-2 sm:grid-cols-2">
        <ToggleRow
          label="Allow multiple choices"
          checked={value.allow_multiple}
          onChange={(v) => onChange({ ...value, allow_multiple: v })}
        />
        <ToggleRow
          label="Anonymous voting"
          checked={value.is_anonymous}
          onChange={(v) => onChange({ ...value, is_anonymous: v })}
        />
        <ToggleRow
          label="Show results before voting"
          checked={value.show_results_before_vote}
          onChange={(v) => onChange({ ...value, show_results_before_vote: v })}
        />
        <ToggleRow
          label="Set closing date"
          checked={showClose}
          onChange={(v) => {
            setShowClose(v)
            if (!v) onChange({ ...value, closes_at: null })
          }}
        />
      </div>

      {showClose && (
        <div className="mt-3">
          <label className="mb-1 block text-[11px] font-semibold uppercase tracking-[0.16em] text-black">
            Poll closes
          </label>
          <input
            type="datetime-local"
            value={value.closes_at ? isoToLocalInput(value.closes_at) : ''}
            onChange={(e) => onChange({
              ...value,
              closes_at: e.target.value ? new Date(e.target.value).toISOString() : null,
            })}
            className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-[13px] text-navy-900 focus:border-teal-400 focus:outline-none focus:ring-2 focus:ring-teal-100"
          />
        </div>
      )}
    </div>
  )
}

function ToggleRow({
  label, checked, onChange,
}: { label: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex cursor-pointer items-center gap-2 text-[13px] text-navy-900">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="h-4 w-4 accent-teal-500"
      />
      {label}
    </label>
  )
}

function isoToLocalInput(iso: string): string {
  // datetime-local expects "YYYY-MM-DDTHH:MM" in the browser's local zone.
  const d = new Date(iso)
  const pad = (n: number) => n.toString().padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}
