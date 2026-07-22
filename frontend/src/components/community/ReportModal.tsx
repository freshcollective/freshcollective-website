'use client'

import { useEffect, useState } from 'react'
import { apiUrl, extractErrorMessage, type ApiError } from '@/lib/api'

/**
 * ReportModal — member-facing intake for a post or comment.
 *
 * The tone is deliberately calm. Members are told what happens to a
 * report, what does not (their identity is never shared with the
 * person reported), and that a Fresh Collective administrator will
 * review it. Nothing here suggests automatic enforcement.
 */

type Kind = 'post' | 'comment'

interface Props {
  kind: Kind
  targetId: string
  onClose: () => void
  onSubmitted?: () => void
}

const CATEGORIES: [value: string, label: string][] = [
  ['harassment_or_bullying', 'Harassment or bullying'],
  ['hate_or_discrimination', 'Hate or discrimination'],
  ['spam_or_scam', 'Spam or scam'],
  ['unsafe_behaviour', 'Unsafe behaviour'],
  ['misinformation', 'Misinformation'],
  ['inappropriate_content', 'Inappropriate content'],
  ['privacy_information', 'Privacy information'],
  ['something_else', 'Something else'],
]

export default function ReportModal({ kind, targetId, onClose, onSubmitted }: Props) {
  const [category, setCategory] = useState<string>('')
  const [note, setNote] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [submittedAt, setSubmittedAt] = useState<string | null>(null)

  useEffect(() => {
    function onKeydown(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKeydown)
    return () => document.removeEventListener('keydown', onKeydown)
  }, [onClose])

  const noteRequired = category === 'something_else'
  const canSubmit =
    !!category &&
    !submitting &&
    (!noteRequired || note.trim().length > 0)

  async function submit() {
    setSubmitting(true)
    setError(null)
    try {
      const res = await fetch(apiUrl('/api/community-care/reports'), {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          [kind === 'post' ? 'target_post_id' : 'target_comment_id']: targetId,
          category,
          reporter_note: note.trim() || null,
        }),
      })
      if (!res.ok) {
        if (res.status === 429) {
          setError("You've submitted several reports recently. Please try again a little later.")
          setSubmitting(false)
          return
        }
        const body = (await res.json().catch(() => ({}))) as Partial<ApiError>
        setError(
          body.detail
            ? extractErrorMessage(body as ApiError)
            : 'Could not submit the report. Please try again.',
        )
        setSubmitting(false)
        return
      }
      const data = (await res.json().catch(() => ({}))) as { received_at?: string }
      setSubmittedAt(data.received_at ?? new Date().toISOString())
      onSubmitted?.()
    } catch {
      setError('Could not submit the report. Please try again.')
      setSubmitting(false)
    }
  }

  const label = kind === 'post' ? 'post' : 'comment'

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/40 px-4 pt-16 sm:pt-24"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}
      role="dialog"
      aria-modal="true"
      aria-labelledby="fc-report-heading"
    >
      <div className="w-full max-w-lg rounded-2xl bg-white p-6 shadow-xl sm:p-7">
        {submittedAt ? (
          <>
            <div className="mb-4 flex items-start justify-between">
              <h2
                id="fc-report-heading"
                className="font-serif text-xl leading-tight text-navy-900"
              >
                Thank you for letting us know
              </h2>
              <button
                type="button"
                onClick={onClose}
                className="ml-3 text-slate-400 transition-colors hover:text-slate-600"
                aria-label="Close"
              >
                ✕
              </button>
            </div>
            <p className="text-[13.5px] leading-relaxed text-black">
              A Fresh Collective administrator will review this. Reports are
              handled with care and your identity is never disclosed to the
              person reported.
            </p>
            <p className="mt-3 text-[12.5px] italic text-slate-600">
              Serious matters may result in immediate protective measures
              pending review.
            </p>
            <div className="mt-6 flex justify-end">
              <button
                type="button"
                onClick={onClose}
                className="rounded-full bg-navy-700 px-5 py-2 text-[13px] font-semibold text-white transition-opacity hover:opacity-90"
              >
                Close
              </button>
            </div>
          </>
        ) : (
          <>
            <div className="mb-4 flex items-start justify-between">
              <h2
                id="fc-report-heading"
                className="font-serif text-xl leading-tight text-navy-900"
              >
                Report this {label}
              </h2>
              <button
                type="button"
                onClick={onClose}
                className="ml-3 text-slate-400 transition-colors hover:text-slate-600"
                aria-label="Close"
              >
                ✕
              </button>
            </div>

            <div className="mb-5 rounded-lg bg-slate-50 px-4 py-3 text-[12.5px] leading-relaxed text-slate-700">
              Every report is reviewed by a Fresh Collective administrator.
              Reports do not automatically result in action, and your identity
              is never disclosed to the person reported.
            </div>

            <fieldset className="mb-4">
              <legend className="mb-2 block text-[12.5px] font-semibold uppercase tracking-wide text-slate-500">
                What is happening?
              </legend>
              <div className="space-y-1.5">
                {CATEGORIES.map(([value, cat_label]) => (
                  <label
                    key={value}
                    className={[
                      'flex cursor-pointer items-start gap-3 rounded-lg border px-3 py-2 transition-colors',
                      category === value
                        ? 'border-teal-400 bg-teal-50/60'
                        : 'border-slate-200 hover:border-slate-300 hover:bg-slate-50',
                    ].join(' ')}
                  >
                    <input
                      type="radio"
                      name="fc-report-category"
                      value={value}
                      checked={category === value}
                      onChange={() => setCategory(value)}
                      className="mt-0.5 h-4 w-4 accent-teal-600"
                    />
                    <span className="text-[13.5px] text-navy-900">{cat_label}</span>
                  </label>
                ))}
              </div>
            </fieldset>

            <label className="mb-4 block">
              <span className="mb-1 block text-[12.5px] font-semibold uppercase tracking-wide text-slate-500">
                {noteRequired ? 'Please explain' : 'Anything else to add? (optional)'}
              </span>
              <textarea
                value={note}
                onChange={(e) => setNote(e.target.value)}
                rows={3}
                required={noteRequired}
                placeholder={
                  noteRequired
                    ? 'Tell us what happened.'
                    : 'Add a short note to help the reviewer.'
                }
                className="w-full resize-none rounded-lg border border-slate-200 bg-white px-3 py-2 text-[13.5px] leading-relaxed text-navy-900 focus:border-teal-400 focus:outline-none focus:ring-2 focus:ring-teal-100"
              />
            </label>

            {error && (
              <p className="mb-3 text-[12.5px] text-red-600">{error}</p>
            )}

            <div className="mt-2 flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={onClose}
                className="rounded-full border border-slate-200 px-4 py-1.5 text-[13px] text-black hover:bg-slate-50"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={submit}
                disabled={!canSubmit}
                className="rounded-full bg-navy-700 px-5 py-2 text-[13px] font-semibold text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {submitting ? 'Sending…' : 'Send report'}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
