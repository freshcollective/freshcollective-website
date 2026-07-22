'use client'

import { useState } from 'react'
import { apiUrl } from '@/lib/api'

/**
 * PollView — the poll surface rendered inside a PostCard when the post
 * has a poll attached. Two visual modes:
 *
 *   pre-vote  · options listed as tap-targets. On tap, we POST the vote
 *              and swap to results mode.
 *   results   · each option a labelled progress bar showing the vote
 *              share (only when the poll config or state permits).
 *
 * All result-visibility decisions come from the server (`show_results`)
 * — the client just renders what it's told.
 */

export interface PollViewData {
  allow_multiple: boolean
  is_anonymous: boolean
  show_results_before_vote: boolean
  closes_at: string | null
  total_voters: number
  user_has_voted: boolean
  can_edit: boolean
  is_closed: boolean
  show_results: boolean
  options: {
    id: string
    label: string
    position: number
    vote_count: number
    voted: boolean
  }[]
}

interface Props {
  spaceSlug: string
  postId: string
  poll: PollViewData
  onVote?: (updated: PollViewData) => void
}

export default function PollView({ spaceSlug, postId, poll: initial, onVote }: Props) {
  const [poll, setPoll] = useState<PollViewData>(initial)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Local checkbox state for multi-choice pre-vote.
  const [selectedIds, setSelectedIds] = useState<string[]>(
    poll.options.filter((o) => o.voted).map((o) => o.id),
  )

  const closed = poll.is_closed
  const showResults = poll.show_results
  const totalVotes = poll.options.reduce((sum, o) => sum + o.vote_count, 0)

  async function submit(optionIds: string[]) {
    setBusy(true)
    setError(null)
    try {
      const res = await fetch(apiUrl(`/api/spaces/${spaceSlug}/community/${postId}/poll/vote`), {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ option_ids: optionIds }),
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(typeof data.detail === 'string' ? data.detail : 'Vote failed.')
      }
      const updated = (await res.json()) as PollViewData
      setPoll(updated)
      setSelectedIds(updated.options.filter((o) => o.voted).map((o) => o.id))
      onVote?.(updated)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Vote failed.')
    } finally {
      setBusy(false)
    }
  }

  function onSingleChoiceClick(id: string) {
    if (closed || busy) return
    submit([id])
  }

  function toggleMulti(id: string) {
    setSelectedIds((prev) => prev.includes(id)
      ? prev.filter((x) => x !== id)
      : [...prev, id])
  }

  return (
    <div className="mt-3">
      <div className="mb-2 flex flex-wrap items-center gap-2 text-[11px] uppercase tracking-[0.14em] text-slate-500">
        <span>Poll</span>
        {poll.is_anonymous && <span>· Anonymous</span>}
        {poll.allow_multiple && <span>· Multiple choice</span>}
        {closed
          ? <span style={{ color: '#8A6A15' }}>· Closed</span>
          : poll.closes_at && <span>· Closes {new Date(poll.closes_at).toLocaleString()}</span>}
      </div>

      <div className="space-y-2">
        {poll.options.map((o) => (
          <PollRow
            key={o.id}
            option={o}
            showResults={showResults}
            totalVotes={totalVotes}
            selected={selectedIds.includes(o.id)}
            disabled={closed || busy}
            allowMultiple={poll.allow_multiple}
            onSingleClick={() => onSingleChoiceClick(o.id)}
            onToggle={() => toggleMulti(o.id)}
          />
        ))}
      </div>

      {poll.allow_multiple && !closed && (
        <div className="mt-3 flex items-center gap-3">
          <button
            type="button"
            onClick={() => submit(selectedIds)}
            disabled={busy}
            className="rounded-full px-4 py-1.5 text-[12px] font-semibold text-white disabled:opacity-50"
            style={{ background: 'var(--fc-accent, #0d9488)' }}
          >
            {busy ? 'Saving…' : poll.user_has_voted ? 'Update vote' : 'Cast vote'}
          </button>
          {poll.user_has_voted && (
            <button
              type="button"
              onClick={() => submit([])}
              disabled={busy}
              className="text-[12px] text-slate-500 hover:text-red-500"
            >
              Clear vote
            </button>
          )}
        </div>
      )}

      {error && <p className="mt-2 text-[12px] text-red-500">{error}</p>}

      {showResults && (
        <p className="mt-3 text-[11px] text-slate-500">
          {poll.total_voters === 1 ? '1 vote' : `${poll.total_voters} votes`}
          {poll.is_anonymous ? ' · Individual voters are hidden' : ''}
        </p>
      )}
    </div>
  )
}

function PollRow({
  option, showResults, totalVotes, selected, disabled, allowMultiple,
  onSingleClick, onToggle,
}: {
  option: PollViewData['options'][number]
  showResults: boolean
  totalVotes: number
  selected: boolean
  disabled: boolean
  allowMultiple: boolean
  onSingleClick: () => void
  onToggle: () => void
}) {
  const pct = totalVotes > 0 ? Math.round((option.vote_count / totalVotes) * 100) : 0

  if (showResults) {
    return (
      <div
        className="relative overflow-hidden rounded-lg px-3 py-2"
        style={{
          background: 'rgba(0,0,0,0.03)',
          border: option.voted
            ? '1px solid var(--fc-accent-line, rgba(56,160,158,0.35))'
            : '1px solid rgba(12,24,38,0.08)',
        }}
      >
        <div
          className="absolute inset-y-0 left-0"
          style={{
            width: `${pct}%`,
            background: option.voted
              ? 'var(--fc-accent-soft, rgba(56,160,158,0.18))'
              : 'rgba(0,0,0,0.05)',
            transition: 'width 300ms ease',
          }}
        />
        <div className="relative flex items-center justify-between gap-3">
          <span className="text-[13px] text-navy-900">
            {option.voted && (
              <span aria-hidden="true" className="mr-1" style={{ color: 'var(--fc-accent, #0f766e)' }}>✓</span>
            )}
            {option.label}
          </span>
          <span className="text-[12px] font-semibold text-slate-600">
            {pct}%{option.vote_count > 0 && ` · ${option.vote_count}`}
          </span>
        </div>
      </div>
    )
  }

  // Pre-vote — options are tap-targets (single) or checkboxes (multi).
  return (
    <button
      type="button"
      onClick={allowMultiple ? onToggle : onSingleClick}
      disabled={disabled}
      className="flex w-full items-center gap-2 rounded-lg border px-3 py-2 text-left text-[13px] text-navy-900 transition-colors disabled:opacity-50"
      style={{
        borderColor: selected
          ? 'var(--fc-accent, rgba(56,160,158,0.55))'
          : 'rgba(12,24,38,0.10)',
        background: selected
          ? 'var(--fc-accent-soft, rgba(56,160,158,0.06))'
          : 'transparent',
      }}
    >
      {allowMultiple && (
        <span
          className="inline-flex h-4 w-4 shrink-0 items-center justify-center rounded"
          style={{
            border: '1px solid rgba(12,24,38,0.30)',
            background: selected ? 'var(--fc-accent, #0d9488)' : 'transparent',
            color: '#FFFFFF',
            fontSize: '10px',
          }}
          aria-hidden="true"
        >
          {selected ? '✓' : ''}
        </span>
      )}
      <span className="flex-1">{option.label}</span>
    </button>
  )
}
