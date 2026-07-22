'use client'

import { useState } from 'react'
import { apiUrl, extractErrorMessage, type ApiError } from '@/lib/api'
import type { SpaceSummary } from '@/types/platform'

/**
 * CreatorSupportForm — client half of the Request Fresh Collective
 * Support flow. Renders inside `/creator/support/page.tsx` which
 * handles the intro copy and fetches the list of the creator's own
 * collectives (so the picker only ever shows what they own).
 */

const SCOPES: [value: string, label: string, hint: string][] = [
  ['community_wellbeing', 'Community wellbeing', 'A member is struggling; a difficult dynamic is unfolding.'],
  ['member_concern', 'Member concern', 'A specific member needs attention or intervention.'],
  ['platform_feature', 'Platform feature', 'Something is not working how you expected, or you need help using a feature.'],
  ['technical_issue', 'Technical issue', 'A bug, an error, an upload that will not go through.'],
  ['community_expectations', 'Community expectations', 'Something in your collective is not aligning with the FC expectations.'],
]

interface Props {
  spaces: SpaceSummary[]
}

export default function CreatorSupportForm({ spaces }: Props) {
  const [scope, setScope] = useState('')
  const [spaceId, setSpaceId] = useState<string>('')
  const [description, setDescription] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [submittedCaseNumber, setSubmittedCaseNumber] = useState<string | null>(null)

  const canSubmit = !!scope && description.trim().length > 0 && !submitting

  async function submit() {
    setSubmitting(true)
    setError(null)
    try {
      const res = await fetch(apiUrl('/api/community-care/creator-support'), {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          scope,
          subject_space_id: spaceId || null,
          description: description.trim(),
        }),
      })
      if (!res.ok) {
        if (res.status === 429) {
          setError("You've submitted several requests recently. Please try again a little later.")
          setSubmitting(false)
          return
        }
        const body = (await res.json().catch(() => ({}))) as Partial<ApiError>
        setError(
          body.detail
            ? extractErrorMessage(body as ApiError)
            : 'Could not send your request. Please try again.',
        )
        setSubmitting(false)
        return
      }
      const data = (await res.json().catch(() => ({}))) as { case_number?: string }
      setSubmittedCaseNumber(data.case_number ?? '')
    } catch {
      setError('Could not send your request. Please try again.')
      setSubmitting(false)
    }
  }

  if (submittedCaseNumber !== null) {
    return (
      <div className="rounded-2xl border border-slate-200 bg-white p-7">
        <h2 className="mb-2 font-serif text-2xl text-navy-900">Your request has been received</h2>
        <p className="text-[14px] leading-relaxed text-black">
          A Fresh Collective administrator will be in touch.
          {submittedCaseNumber && (
            <>
              {' '}You can reference this request as{' '}
              <span className="font-semibold">{submittedCaseNumber}</span>.
            </>
          )}
        </p>
        <p className="mt-3 text-[12.5px] italic text-slate-600">
          We hold these conversations with care. If your concern involves a
          serious safety matter, immediate protective measures may be taken
          pending review.
        </p>
        <div className="mt-6 flex gap-2">
          <button
            type="button"
            onClick={() => {
              setSubmittedCaseNumber(null)
              setScope('')
              setSpaceId('')
              setDescription('')
              setError(null)
              setSubmitting(false)
            }}
            className="rounded-full border border-slate-200 px-4 py-1.5 text-[13px] text-black hover:bg-slate-50"
          >
            Submit another request
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-6 sm:p-7">
      <fieldset className="mb-5">
        <legend className="mb-2 block text-[12.5px] font-semibold uppercase tracking-wide text-slate-500">
          What kind of support do you need?
        </legend>
        <div className="space-y-1.5">
          {SCOPES.map(([value, label, hint]) => (
            <label
              key={value}
              className={[
                'flex cursor-pointer items-start gap-3 rounded-lg border px-3 py-2.5 transition-colors',
                scope === value
                  ? 'border-teal-400 bg-teal-50/60'
                  : 'border-slate-200 hover:border-slate-300 hover:bg-slate-50',
              ].join(' ')}
            >
              <input
                type="radio"
                name="fc-support-scope"
                value={value}
                checked={scope === value}
                onChange={() => setScope(value)}
                className="mt-1 h-4 w-4 accent-teal-600"
              />
              <span>
                <span className="block text-[14px] font-medium text-navy-900">{label}</span>
                <span className="mt-0.5 block text-[12.5px] text-slate-600">{hint}</span>
              </span>
            </label>
          ))}
        </div>
      </fieldset>

      {spaces.length > 1 && (
        <label className="mb-5 block">
          <span className="mb-1 block text-[12.5px] font-semibold uppercase tracking-wide text-slate-500">
            Which collective? (optional)
          </span>
          <select
            value={spaceId}
            onChange={(e) => setSpaceId(e.target.value)}
            className="w-full cursor-pointer rounded-lg border border-slate-200 bg-white px-3 py-2 text-[14px] text-navy-900 focus:border-teal-400 focus:outline-none focus:ring-2 focus:ring-teal-100"
          >
            <option value="">Not specific to one collective</option>
            {spaces.map((s) => (
              <option key={s.id} value={s.id}>{s.name}</option>
            ))}
          </select>
        </label>
      )}
      {spaces.length === 1 && (
        <input type="hidden" name="fc-support-space" value={spaces[0].id} />
      )}

      <label className="mb-4 block">
        <span className="mb-1 block text-[12.5px] font-semibold uppercase tracking-wide text-slate-500">
          Tell us what is happening
        </span>
        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          rows={5}
          placeholder="Share what you are noticing and what you would like our help with."
          className="w-full resize-none rounded-lg border border-slate-200 bg-white px-3 py-2 text-[14px] leading-relaxed text-navy-900 focus:border-teal-400 focus:outline-none focus:ring-2 focus:ring-teal-100"
        />
      </label>

      {error && <p className="mb-3 text-[13px] text-red-600">{error}</p>}

      <div className="mt-4 flex items-center justify-end">
        <button
          type="button"
          onClick={submit}
          disabled={!canSubmit}
          className="rounded-full bg-navy-700 px-5 py-2 text-[13px] font-semibold text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {submitting ? 'Sending…' : 'Send request'}
        </button>
      </div>
    </div>
  )
}
