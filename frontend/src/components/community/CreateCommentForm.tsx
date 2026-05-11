'use client'

import { useState, useTransition } from 'react'
import { useRouter } from 'next/navigation'
import { apiUrl } from '@/lib/api'

interface Props {
  spaceSlug: string
  postId: string
}

export default function CreateCommentForm({ spaceSlug, postId }: Props) {
  const router = useRouter()
  const [body, setBody] = useState('')
  const [error, setError] = useState('')
  const [isPending, startTransition] = useTransition()

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!body.trim()) return
    setError('')

    const res = await fetch(apiUrl(`/api/spaces/${spaceSlug}/community/${postId}/comments`), {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ body: body.trim() }),
    })

    if (res.ok) {
      setBody('')
      startTransition(() => router.refresh())
    } else {
      setError('Something went wrong. Please try again.')
    }
  }

  return (
    <form onSubmit={handleSubmit} className="mt-6">
      <textarea
        value={body}
        onChange={(e) => setBody(e.target.value)}
        rows={3}
        placeholder="Add a reply…"
        className="w-full resize-none rounded-lg border border-border bg-surface px-4 py-3 text-sm leading-relaxed text-navy-900 placeholder:text-slate-300 focus:border-teal-400 focus:outline-none focus:ring-2 focus:ring-teal-100"
      />
      {error && <p className="mt-1 text-xs text-red-500">{error}</p>}
      <div className="mt-2 flex justify-end">
        <button
          type="submit"
          disabled={isPending || !body.trim()}
          className="rounded-full bg-teal-500 px-5 py-2 text-sm font-medium text-white transition-colors hover:bg-teal-600 disabled:opacity-50"
        >
          {isPending ? 'Posting…' : 'Reply'}
        </button>
      </div>
    </form>
  )
}
