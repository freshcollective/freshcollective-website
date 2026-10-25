'use client'

import { useState } from 'react'
import { apiUrl } from '@/lib/api'
import {
  modeIsTappable,
  modeShowsBar,
  nextSelection,
  pollRowMode,
  showsClearVote,
  type PollRowMode,
} from '@/lib/pollInteraction'

/**
 * PollView — the poll surface rendered inside a PostCard when the post
 * has a poll attached.
 *
 * Two things are decided independently, and conflating them is what
 * made polls unvotable:
 *
 *   **Are results visible?** Entirely the server's call
 *   (`show_results`), which is true when the poll shows results early,
 *   OR the member has voted, OR the poll has closed.
 *
 *   **Can the member still act?** Only false once the poll has closed
 *   (or while a request is in flight).
 *
 * This used to render a static bar whenever results were visible, which
 * meant a poll set to "show results before voting" had no tap-target
 * from the moment it was created, and every poll became read-only the
 * instant somebody voted — so a vote could never be changed, despite
 * the API supporting it and the button below saying "Update vote".
 *
 * Both rules now live in `lib/pollInteraction`, so the component cannot
 * drift from them.
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
  const totalVotes = poll.options.reduce((sum, o) => sum + o.vote_count, 0)
  const rowMode = pollRowMode(poll, busy)
  const clearable = showsClearVote(poll)

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

  /**
   * One handler for both poll kinds, so a tap means the same thing
   * whether results happen to be on screen or not.
   *
   * Single choice submits immediately — there is one decision and no
   * reason to make the member confirm it. Multiple choice stages the
   * selection locally; the Cast/Update button below sends it.
   */
  function onOptionTap(id: string) {
    if (!modeIsTappable(rowMode)) return
    const next = nextSelection(selectedIds, id, poll.allow_multiple)
    setSelectedIds(next)
    if (!poll.allow_multiple) submit(next)
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
            mode={rowMode}
            totalVotes={totalVotes}
            selected={selectedIds.includes(o.id)}
            allowMultiple={poll.allow_multiple}
            onTap={() => onOptionTap(o.id)}
          />
        ))}
      </div>

      {/*
        The action row. Multiple choice needs a submit button because
        its selection is staged locally; single choice submits on tap
        and so needs only the retraction.

        ``Clear vote`` is shared by both kinds through
        ``showsClearVote`` — single choice had no way to retract at all,
        though the API has always read an empty selection as "remove my
        vote". Rendered only while the poll is open, so a closed poll
        offers nothing to press rather than pressing and being refused.
      */}
      {(poll.allow_multiple || clearable) && !closed && (
        <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-2">
          {poll.allow_multiple && (
            <button
              type="button"
              onClick={() => submit(selectedIds)}
              disabled={busy}
              className="rounded-full px-4 py-1.5 text-[12px] font-semibold text-white disabled:opacity-50"
              style={{ background: 'var(--fc-accent, #0d9488)' }}
            >
              {busy ? 'Saving…' : poll.user_has_voted ? 'Update vote' : 'Cast vote'}
            </button>
          )}
          {clearable && (
            <button
              type="button"
              onClick={() => submit([])}
              disabled={busy}
              className="min-h-[32px] px-1 text-[12px] text-slate-500 transition-colors hover:text-red-500 disabled:opacity-50"
            >
              {busy ? 'Saving…' : 'Clear vote'}
            </button>
          )}
        </div>
      )}

      {error && <p className="mt-2 text-[12px] text-red-500">{error}</p>}

      {poll.show_results && (
        <p className="mt-3 text-[11px] text-slate-500">
          {poll.total_voters === 1 ? '1 vote' : `${poll.total_voters} votes`}
          {poll.is_anonymous ? ' · Individual voters are hidden' : ''}
        </p>
      )}
    </div>
  )
}

function PollRow({
  option, mode, totalVotes, selected, allowMultiple, onTap,
}: {
  option: PollViewData['options'][number]
  mode: PollRowMode
  totalVotes: number
  selected: boolean
  allowMultiple: boolean
  onTap: () => void
}) {
  const pct = totalVotes > 0 ? Math.round((option.vote_count / totalVotes) * 100) : 0
  const tappable = modeIsTappable(mode)
  const showBar = modeShowsBar(mode)

  // Selection is drawn from the member's CURRENT selection, not from
  // what the server last stored — on a multiple-choice poll those differ
  // between a tap and pressing Update, and the border is what tells the
  // member their tap registered.
  const highlighted = selected || (!tappable && option.voted)

  const inner = (
    <>
      {showBar && (
        <span
          aria-hidden="true"
          className="absolute inset-y-0 left-0"
          style={{
            width: `${pct}%`,
            background: highlighted
              ? 'var(--fc-accent-soft, rgba(56,160,158,0.18))'
              : 'rgba(0,0,0,0.05)',
            transition: 'width 300ms ease',
          }}
        />
      )}
      <span className="relative flex w-full items-center justify-between gap-3">
        <span className="flex min-w-0 items-center gap-2 text-[13px] text-navy-900">
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
          {!allowMultiple && showBar && option.voted && (
            <span aria-hidden="true" style={{ color: 'var(--fc-accent, #0f766e)' }}>✓</span>
          )}
          <span className="truncate">{option.label}</span>
        </span>
        {showBar && (
          <span className="shrink-0 text-[12px] font-semibold text-slate-600">
            {pct}%{option.vote_count > 0 && ` · ${option.vote_count}`}
          </span>
        )}
      </span>
    </>
  )

  const shell =
    'relative flex w-full items-center overflow-hidden rounded-lg border px-3 py-2 text-left transition-colors'
  const style = {
    borderColor: highlighted
      ? 'var(--fc-accent, rgba(56,160,158,0.55))'
      : 'rgba(12,24,38,0.10)',
    background: showBar
      ? 'rgba(0,0,0,0.03)'
      : highlighted
        ? 'var(--fc-accent-soft, rgba(56,160,158,0.06))'
        : 'transparent',
  }

  // A real <button> when it is tappable, so the keyboard, screen
  // readers and mobile tap targets all behave — and a plain <div> when
  // the poll is closed, so nothing invites a press that would do
  // nothing. ``min-h`` keeps the target comfortable on a phone.
  if (!tappable) {
    return (
      <div className={shell} style={style}>
        {inner}
      </div>
    )
  }
  return (
    <button
      type="button"
      onClick={onTap}
      aria-pressed={allowMultiple ? selected : undefined}
      className={`${shell} min-h-[40px] disabled:opacity-50`}
      style={style}
    >
      {inner}
    </button>
  )
}
