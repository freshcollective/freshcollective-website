'use client'

import { useState } from 'react'
import { apiUrl } from '@/lib/api'
import type { ReactionCount } from '@/types/platform'

const REACTION_EMOJIS = ['❤️', '🙌', '🔥', '👏', '😂', '💡']

interface Props {
  spaceSlug: string
  postId: string
  commentId?: string
  initialReactions: ReactionCount[]
}

export default function ReactionBar({ spaceSlug, postId, commentId, initialReactions }: Props) {
  const [reactions, setReactions] = useState<ReactionCount[]>(initialReactions)
  const [pickerOpen, setPickerOpen] = useState(false)

  const reactionMap = new Map(reactions.map(r => [r.emoji, r]))

  async function toggle(emoji: string) {
    const url = commentId
      ? apiUrl(`/api/spaces/${spaceSlug}/community/${postId}/comments/${commentId}/reactions/${encodeURIComponent(emoji)}`)
      : apiUrl(`/api/spaces/${spaceSlug}/community/${postId}/reactions/${encodeURIComponent(emoji)}`)

    const res = await fetch(url, { method: 'POST', credentials: 'include' })
    if (!res.ok) return
    const { reacted } = await res.json()

    setReactions(prev => {
      const existing = prev.find(r => r.emoji === emoji)
      if (existing) {
        const updated = { ...existing, count: reacted ? existing.count + 1 : existing.count - 1, reacted }
        if (updated.count <= 0) return prev.filter(r => r.emoji !== emoji)
        return prev.map(r => r.emoji === emoji ? updated : r)
      }
      if (reacted) return [...prev, { emoji, count: 1, reacted: true }]
      return prev
    })
    setPickerOpen(false)
  }

  return (
    <div className="mt-2 flex flex-wrap items-center gap-1.5">
      {reactions.map(r => (
        <button
          key={r.emoji}
          onClick={() => toggle(r.emoji)}
          className={[
            'flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-sm transition-colors',
            r.reacted
              ? 'border-teal-300 bg-teal-50 text-teal-700'
              : 'border-slate-200 bg-white text-black hover:border-teal-200 hover:bg-teal-50',
          ].join(' ')}
        >
          <span>{r.emoji}</span>
          <span className="text-[11px] font-medium">{r.count}</span>
        </button>
      ))}

      <div className="relative">
        <button
          onClick={() => setPickerOpen(o => !o)}
          className="flex h-7 w-7 items-center justify-center rounded-full border border-slate-200 bg-white text-black transition-colors hover:border-teal-200 hover:bg-teal-50 hover:text-teal-600"
          title="Add reaction"
        >
          <span className="text-base leading-none">+</span>
        </button>
        {pickerOpen && (
          <div className="absolute bottom-full left-0 mb-1 flex gap-1 rounded-xl border border-slate-200 bg-white p-2 shadow-lg z-10">
            {REACTION_EMOJIS.map(e => (
              <button
                key={e}
                onClick={() => toggle(e)}
                className={[
                  'rounded-lg p-1.5 text-lg transition-colors hover:bg-teal-50',
                  reactionMap.get(e)?.reacted ? 'bg-teal-50 ring-1 ring-teal-300' : '',
                ].join(' ')}
                title={e}
              >
                {e}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
