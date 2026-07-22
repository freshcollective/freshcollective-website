'use client'

import { useRef, useState, useTransition } from 'react'
import { useRouter } from 'next/navigation'
import { apiUrl } from '@/lib/api'
import EmojiPicker from './EmojiPicker'
import MentionTextarea, { type MentionTextareaHandle } from './MentionTextarea'

interface ReplyTarget {
  commentId: string
  authorName: string
}

interface Props {
  spaceSlug: string
  postId: string
  /** When set, the composer submits as a reply to this comment and
   *  shows a "Replying to @name · cancel" chip above the textarea. */
  replyTo?: ReplyTarget | null
  onCancelReply?: () => void
}

export default function CreateCommentForm({
  spaceSlug, postId, replyTo, onCancelReply,
}: Props) {
  const router = useRouter()
  const [body, setBody] = useState('')
  const [mentionedIds, setMentionedIds] = useState<string[]>([])
  const [imageUrl, setImageUrl] = useState<string | null>(null)
  const [imagePreview, setImagePreview] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState('')
  const [isPending, startTransition] = useTransition()
  const mentionRef = useRef<MentionTextareaHandle>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  function insertEmoji(emoji: string) {
    setBody((b) => b + emoji)
  }

  async function handleImageChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    setImagePreview(URL.createObjectURL(file))
    setUploading(true)
    setError('')
    try {
      const form = new FormData()
      form.append('file', file)
      const res = await fetch(apiUrl(`/api/spaces/${spaceSlug}/community/upload-image`), {
        method: 'POST',
        credentials: 'include',
        body: form,
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        setError(data.detail || 'Image upload failed.')
        setImagePreview(null)
        return
      }
      const { url } = await res.json()
      setImageUrl(url)
    } finally {
      setUploading(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!body.trim()) return
    setError('')

    const res = await fetch(apiUrl(`/api/spaces/${spaceSlug}/community/${postId}/comments`), {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        body: body.trim(),
        image_url: imageUrl || null,
        parent_comment_id: replyTo?.commentId ?? null,
        mentioned_user_ids: mentionedIds,
      }),
    })

    if (res.ok) {
      setBody('')
      setMentionedIds([])
      setImageUrl(null)
      setImagePreview(null)
      onCancelReply?.()
      startTransition(() => router.refresh())
    } else {
      setError('Something went wrong. Please try again.')
    }
  }

  return (
    <form onSubmit={handleSubmit} className="mt-6">
      {replyTo && (
        <div
          className="mb-2 inline-flex items-center gap-2 rounded-full px-3 py-1 text-[12px]"
          style={{
            background: 'var(--fc-accent-soft, rgba(56,160,158,0.10))',
            color: 'var(--fc-accent, #0f766e)',
          }}
        >
          <span>Replying to @{replyTo.authorName}</span>
          <button
            type="button"
            onClick={() => onCancelReply?.()}
            className="opacity-70 hover:opacity-100"
            aria-label="Cancel reply"
          >
            ✕
          </button>
        </div>
      )}

      <MentionTextarea
        ref={mentionRef}
        spaceSlug={spaceSlug}
        value={body}
        onChange={setBody}
        mentionedIds={mentionedIds}
        onMentionedIdsChange={setMentionedIds}
        rows={3}
        placeholder={replyTo ? `Reply to @${replyTo.authorName}…` : 'Add a reply…'}
      />

      {/* Image preview */}
      {imagePreview && (
        <div className="relative mt-2 inline-block">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={imagePreview} alt="Upload preview" className="max-h-40 rounded-lg object-cover" />
          {uploading && (
            <div className="absolute inset-0 flex items-center justify-center rounded-lg bg-white/60">
              <span className="text-xs text-black">Uploading…</span>
            </div>
          )}
          {!uploading && (
            <button
              type="button"
              onClick={() => { setImageUrl(null); setImagePreview(null) }}
              className="absolute -right-2 -top-2 flex h-5 w-5 items-center justify-center rounded-full bg-slate-700 text-[10px] text-white hover:bg-red-500"
            >
              ✕
            </button>
          )}
        </div>
      )}

      {error && <p className="mt-1 text-xs text-red-500">{error}</p>}

      <div className="mt-2 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <input
            ref={fileInputRef}
            type="file"
            accept="image/jpeg,image/png,image/webp"
            className="hidden"
            onChange={handleImageChange}
          />
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading || !!imagePreview}
            className="flex items-center gap-1 rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs text-black transition-colors hover:border-teal-300 hover:text-teal-600 disabled:opacity-40"
            title="Attach image"
          >
            <span>🖼</span>
            <span>Photo</span>
          </button>
          <EmojiPicker onSelect={insertEmoji} />
        </div>

        <button
          type="submit"
          disabled={isPending || !body.trim() || uploading}
          className="rounded-full px-5 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50"
          style={{ background: 'var(--fc-accent, #14b8a6)' }}
        >
          {isPending ? 'Posting…' : 'Reply'}
        </button>
      </div>
    </form>
  )
}
