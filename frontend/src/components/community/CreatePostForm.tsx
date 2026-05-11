'use client'

import { useState, useTransition } from 'react'
import { useRouter } from 'next/navigation'
import { apiUrl } from '@/lib/api'

const POST_TYPES = [
  { value: 'reflection', label: 'Reflection' },
  { value: 'discussion', label: 'Discussion' },
  { value: 'prompt',     label: 'Prompt' },
]

export default function CreatePostForm({ spaceSlug }: { spaceSlug: string }) {
  const router = useRouter()
  const [open, setOpen] = useState(false)
  const [postType, setPostType] = useState('reflection')
  const [title, setTitle] = useState('')
  const [body, setBody] = useState('')
  const [error, setError] = useState('')
  const [isPending, startTransition] = useTransition()

  function reset() {
    setOpen(false)
    setTitle('')
    setBody('')
    setPostType('reflection')
    setError('')
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!body.trim()) {
      setError('Please write something before sharing.')
      return
    }
    setError('')

    const res = await fetch(apiUrl(`/api/spaces/${spaceSlug}/community`), {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        post_type: postType,
        title: title.trim() || null,
        body: body.trim(),
      }),
    })

    if (res.ok) {
      reset()
      startTransition(() => router.refresh())
    } else {
      setError('Something went wrong. Please try again.')
    }
  }

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="w-full rounded-xl border border-dashed border-border bg-surface px-5 py-4 text-left text-sm text-slate-400 transition-colors hover:border-teal-300 hover:text-teal-600"
      >
        Share a reflection, question, or thought…
      </button>
    )
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="rounded-xl border border-teal-200 bg-surface px-6 py-5"
    >
      <div className="mb-4 flex items-center justify-between">
        <select
          value={postType}
          onChange={(e) => setPostType(e.target.value)}
          className="rounded-full border border-border bg-background px-3 py-1 text-xs text-slate-600 focus:border-teal-400 focus:outline-none"
        >
          {POST_TYPES.map((t) => (
            <option key={t.value} value={t.value}>{t.label}</option>
          ))}
        </select>
        <button
          type="button"
          onClick={reset}
          className="text-xs text-slate-400 hover:text-slate-600"
        >
          Cancel
        </button>
      </div>

      <input
        type="text"
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        placeholder="Title (optional)"
        className="mb-3 w-full rounded-lg border border-border bg-surface px-4 py-2 text-sm text-navy-900 placeholder:text-slate-300 focus:border-teal-400 focus:outline-none focus:ring-2 focus:ring-teal-100"
      />

      <textarea
        value={body}
        onChange={(e) => setBody(e.target.value)}
        rows={4}
        placeholder="Write something…"
        required
        className="w-full resize-none rounded-lg border border-border bg-surface px-4 py-3 text-sm leading-relaxed text-navy-900 placeholder:text-slate-300 focus:border-teal-400 focus:outline-none focus:ring-2 focus:ring-teal-100"
      />

      {error && <p className="mt-2 text-xs text-red-500">{error}</p>}

      <div className="mt-3 flex justify-end">
        <button
          type="submit"
          disabled={isPending || !body.trim()}
          className="rounded-full bg-teal-500 px-5 py-2 text-sm font-medium text-white transition-colors hover:bg-teal-600 disabled:opacity-50"
        >
          {isPending ? 'Sharing…' : 'Share'}
        </button>
      </div>
    </form>
  )
}
