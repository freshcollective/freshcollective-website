'use client'

import { useState, useRef, useEffect, useCallback } from 'react'
import { apiUrl, resolveMediaUrl } from '@/lib/api'
import EmojiPicker from '@/components/community/EmojiPicker'
import CommunityImage from '@/components/community/CommunityImage'
import type { CreatorPost } from '@/types/platform'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const POST_TYPES = [
  { value: 'announcement', label: 'Announcement' },
  { value: 'prompt', label: 'Prompt' },
  { value: 'discussion', label: 'Discussion' },
]

const TYPE_LABELS: Record<string, string> = {
  announcement: 'Announcement',
  prompt: 'Prompt',
  discussion: 'Discussion',
  reflection: 'Reflection',
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString('en-AU', { day: 'numeric', month: 'short', year: 'numeric' })
}

// ---------------------------------------------------------------------------
// HTML sanitizer (runs in browser before submission)
// ---------------------------------------------------------------------------

function sanitizeHtml(html: string): string {
  const div = document.createElement('div')
  div.innerHTML = html

  const ALLOWED_TAGS = new Set(['b', 'strong', 'i', 'em', 'u', 'a', 'br', 'p', 'div', 'span'])

  function cleanNode(node: Node): void {
    if (node.nodeType !== Node.ELEMENT_NODE) return
    const el = node as Element
    const tag = el.tagName.toLowerCase()

    // Clean children first (depth-first so we don't invalidate iteration)
    Array.from(el.childNodes).forEach(cleanNode)

    if (!ALLOWED_TAGS.has(tag)) {
      // Unwrap: replace element with its children
      const parent = el.parentNode
      if (parent) {
        while (el.firstChild) parent.insertBefore(el.firstChild, el)
        parent.removeChild(el)
      }
      return
    }

    // Scrub all attributes; for <a> restore safe href only
    const attrNames = Array.from(el.attributes).map(a => a.name)
    attrNames.forEach(name => el.removeAttribute(name))
    if (tag === 'a') {
      const href = (el as HTMLAnchorElement).getAttribute('href') ?? ''
      if (/^https?:\/\//.test(href)) {
        el.setAttribute('href', href)
        el.setAttribute('target', '_blank')
        el.setAttribute('rel', 'noopener noreferrer')
      }
    }
  }

  Array.from(div.childNodes).forEach(cleanNode)
  return div.innerHTML
}

// Is the editor visually empty?
function isEditorEmpty(html: string) {
  return !html || html === '<br>' || html === '<p><br></p>' || !html.replace(/<[^>]+>/g, '').trim()
}

// ---------------------------------------------------------------------------
// API helper
// ---------------------------------------------------------------------------

async function apiFetch(url: string, options?: RequestInit) {
  const res = await fetch(apiUrl(url), { credentials: 'include', ...options })
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try {
      const b = await res.json()
      detail = typeof b.detail === 'string' ? b.detail : JSON.stringify(b.detail)
    } catch {}
    throw new Error(detail)
  }
  return res
}

// ---------------------------------------------------------------------------
// Formatting toolbar
// ---------------------------------------------------------------------------

function ToolbarBtn({
  title, active, onClick, children,
}: {
  title: string
  active?: boolean
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      title={title}
      onMouseDown={(e) => { e.preventDefault(); onClick() }}
      className={[
        'flex h-7 w-7 items-center justify-center rounded text-[13px] transition-colors',
        active
          ? 'bg-navy-100 text-navy-900'
          : 'text-black hover:bg-slate-100 hover:text-navy-700',
      ].join(' ')}
    >
      {children}
    </button>
  )
}

// ---------------------------------------------------------------------------
// Rich editor — shared between create and edit
// ---------------------------------------------------------------------------

interface RichEditorProps {
  initialHtml?: string
  placeholder?: string
  onChange: (html: string) => void
  editorRef: React.RefObject<HTMLDivElement | null>
}

function RichEditor({ initialHtml = '', placeholder, onChange, editorRef }: RichEditorProps) {
  const [mounted, setMounted] = useState(false)

  useEffect(() => {
    setMounted(true)
    if (editorRef.current && initialHtml) {
      editorRef.current.innerHTML = initialHtml
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function exec(cmd: string, value?: string) {
    editorRef.current?.focus()
    document.execCommand(cmd, false, value ?? '')
  }

  function handleInsertLink() {
    const url = prompt('Enter URL (must start with https://):')
    if (!url) return
    const safe = /^https?:\/\//.test(url) ? url : `https://${url}`
    exec('createLink', safe)
    // Ensure target=_blank on inserted link
    editorRef.current?.querySelectorAll('a').forEach(a => {
      a.setAttribute('target', '_blank')
      a.setAttribute('rel', 'noopener noreferrer')
    })
  }

  function handleEmojiInsert(emoji: string) {
    const el = editorRef.current
    if (!el) return
    el.focus()
    document.execCommand('insertText', false, emoji)
  }

  if (!mounted) return null

  return (
    <div className="overflow-hidden rounded-xl border border-border bg-white focus-within:border-teal-300 focus-within:ring-1 focus-within:ring-teal-100">
      {/* Toolbar */}
      <div className="flex items-center gap-0.5 border-b border-border bg-slate-50 px-2 py-1.5">
        <ToolbarBtn title="Bold (Ctrl+B)" onClick={() => exec('bold')}><b>B</b></ToolbarBtn>
        <ToolbarBtn title="Italic (Ctrl+I)" onClick={() => exec('italic')}><i>I</i></ToolbarBtn>
        <ToolbarBtn title="Underline (Ctrl+U)" onClick={() => exec('underline')}><u>U</u></ToolbarBtn>
        <div className="mx-1.5 h-4 w-px bg-slate-200" />
        <ToolbarBtn title="Insert link" onClick={handleInsertLink}>
          <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="2.5">
            <path d="M10 13a5 5 0 007.54.54l3-3a5 5 0 00-7.07-7.07l-1.72 1.71" strokeLinecap="round"/>
            <path d="M14 11a5 5 0 00-7.54-.54l-3 3a5 5 0 007.07 7.07l1.71-1.71" strokeLinecap="round"/>
          </svg>
        </ToolbarBtn>
        <EmojiPicker onSelect={handleEmojiInsert} />
      </div>

      {/* Editable area */}
      <div
        ref={editorRef}
        contentEditable
        suppressContentEditableWarning
        data-placeholder={placeholder}
        onInput={() => onChange(editorRef.current?.innerHTML ?? '')}
        className="min-h-[120px] px-4 py-3 text-[14px] leading-relaxed text-navy-900 outline-none empty:before:text-slate-400 empty:before:content-[attr(data-placeholder)]"
        style={{ wordBreak: 'break-word' }}
      />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Image upload control — shared
// ---------------------------------------------------------------------------

function ImageUpload({
  spaceSlug,
  imageUrl,
  imagePreview,
  uploading,
  onUpload,
  onRemove,
}: {
  spaceSlug: string
  imageUrl: string | null
  imagePreview: string | null
  uploading: boolean
  onUpload: (url: string, preview: string) => void
  onRemove: () => void
}) {
  const fileRef = useRef<HTMLInputElement>(null)

  async function handleFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    const preview = URL.createObjectURL(file)
    const form = new FormData()
    form.append('file', file)
    const res = await fetch(apiUrl(`/api/spaces/${spaceSlug}/community/upload-image`), {
      method: 'POST', credentials: 'include', body: form,
    })
    if (res.ok) {
      const { url } = await res.json()
      onUpload(url, preview)
    }
    if (fileRef.current) fileRef.current.value = ''
  }

  const hasImage = !!(imageUrl || imagePreview)

  return (
    <div>
      <input ref={fileRef} type="file" accept="image/jpeg,image/png,image/webp" className="hidden" onChange={handleFile} />
      {!hasImage && (
        <button
          type="button"
          onClick={() => fileRef.current?.click()}
          disabled={uploading}
          className="flex items-center gap-1.5 rounded-lg border border-slate-200 px-2.5 py-1.5 text-[12px] text-black transition-colors hover:border-teal-300 hover:text-teal-600 disabled:opacity-40"
        >
          🖼 Photo
        </button>
      )}
      {hasImage && (
        <div className="relative mt-2 inline-block">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={imagePreview ?? resolveMediaUrl(imageUrl) ?? ''} alt="preview" className="max-h-48 rounded-lg object-cover" />
          {uploading && (
            <div className="absolute inset-0 flex items-center justify-center rounded-lg bg-white/70">
              <span className="text-xs text-black">Uploading…</span>
            </div>
          )}
          {!uploading && (
            <button
              type="button"
              onClick={onRemove}
              className="absolute -right-2 -top-2 flex h-5 w-5 items-center justify-center rounded-full bg-slate-700 text-[10px] text-white hover:bg-red-500"
            >✕</button>
          )}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Edit form
// ---------------------------------------------------------------------------

function EditForm({
  post, base, spaceSlug, onSave, onCancel,
}: {
  post: CreatorPost
  base: string
  spaceSlug: string
  onSave: (updated: CreatorPost) => void
  onCancel: () => void
}) {
  const [postType, setPostType] = useState(post.post_type)
  const [title, setTitle] = useState(post.title ?? '')
  const [bodyHtml, setBodyHtml] = useState(post.body)
  const [isPinned, setIsPinned] = useState(post.is_pinned)
  const [imageUrl, setImageUrl] = useState<string | null>(post.image_url ?? null)
  const [imagePreview, setImagePreview] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const editorRef = useRef<HTMLDivElement>(null)

  async function handleSave(e: React.FormEvent) {
    e.preventDefault()
    const sanitized = sanitizeHtml(bodyHtml)
    if (isEditorEmpty(sanitized)) return
    setSaving(true); setError(null)
    try {
      const res = await apiFetch(`${base}/${post.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          post_type: postType,
          title: title.trim() || null,
          body: sanitized,
          is_pinned: isPinned,
          image_url: imageUrl,
        }),
      })
      const updated: CreatorPost = await res.json()
      onSave(updated)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <form onSubmit={handleSave} className="flex flex-col gap-3 rounded-xl border border-teal-200 bg-teal-50/30 px-5 py-4">
      <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-black">Editing post</p>

      <div className="flex flex-wrap gap-2">
        {POST_TYPES.map((pt) => (
          <button key={pt.value} type="button" onClick={() => setPostType(pt.value)}
            className={['rounded-full border px-3 py-1 text-xs transition-colors', postType === pt.value ? 'border-navy-900 bg-navy-900 text-white' : 'border-border text-black hover:border-slate-400'].join(' ')}
          >{pt.label}</button>
        ))}
      </div>

      <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Title (optional)"
        className="w-full rounded-lg border border-border bg-white px-3 py-2 text-sm text-navy-900 placeholder-slate-400 focus:outline-none focus:ring-1 focus:ring-navy-300" />

      <RichEditor
        initialHtml={post.body}
        placeholder="Write something…"
        onChange={setBodyHtml}
        editorRef={editorRef}
      />

      <ImageUpload
        spaceSlug={spaceSlug}
        imageUrl={imageUrl}
        imagePreview={imagePreview}
        uploading={uploading}
        onUpload={(url, preview) => { setImageUrl(url); setImagePreview(preview); setUploading(false) }}
        onRemove={() => { setImageUrl(null); setImagePreview(null) }}
      />

      <div className="flex items-center justify-between">
        <label className="flex items-center gap-2 text-sm text-black">
          <input type="checkbox" checked={isPinned} onChange={(e) => setIsPinned(e.target.checked)} className="rounded border-border" />
          Pinned
        </label>
        <div className="flex items-center gap-3">
          {error && <span className="text-xs text-red-500">{error}</span>}
          <button type="button" onClick={onCancel} className="text-sm text-black hover:text-slate-600">Cancel</button>
          <button type="submit" disabled={saving || isEditorEmpty(bodyHtml)}
            className="rounded-lg bg-navy-900 px-4 py-1.5 text-sm font-medium text-white disabled:opacity-50 hover:opacity-90">
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </form>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function CommunityManager({
  posts: initialPosts,
  spaceSlug,
}: {
  posts: CreatorPost[]
  spaceSlug: string
}) {
  const [posts, setPosts] = useState(initialPosts)
  const [postType, setPostType] = useState('announcement')
  const [title, setTitle] = useState('')
  const [bodyHtml, setBodyHtml] = useState('')
  const [imageUrl, setImageUrl] = useState<string | null>(null)
  const [imagePreview, setImagePreview] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)
  const [isPinned, setIsPinned] = useState(false)
  const [posting, setPosting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [editingId, setEditingId] = useState<string | null>(null)
  const editorRef = useRef<HTMLDivElement>(null)

  const base = `/api/creator/spaces/${spaceSlug}/community`

  // Reset compose form
  const resetCompose = useCallback(() => {
    setTitle('')
    setBodyHtml('')
    setImageUrl(null)
    setImagePreview(null)
    setIsPinned(false)
    setError(null)
    if (editorRef.current) editorRef.current.innerHTML = ''
  }, [])

  async function handlePost(e: React.FormEvent) {
    e.preventDefault()
    const sanitized = sanitizeHtml(bodyHtml)
    if (isEditorEmpty(sanitized)) return
    setPosting(true); setError(null)
    try {
      const res = await apiFetch(base, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          post_type: postType,
          title: title.trim() || null,
          body: sanitized,
          is_pinned: isPinned,
          image_url: imageUrl,
        }),
      })
      const data: CreatorPost = await res.json()
      setPosts((prev) => [data, ...prev])
      resetCompose()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not post.')
    } finally {
      setPosting(false)
    }
  }

  function handleEditSave(updated: CreatorPost) {
    setPosts((prev) => prev.map((p) => (p.id === updated.id ? updated : p)))
    setEditingId(null)
  }

  async function togglePin(post: CreatorPost) {
    try {
      await apiFetch(`${base}/${post.id}/pin`, { method: 'PATCH' })
      setPosts((prev) => prev.map((p) => (p.id === post.id ? { ...p, is_pinned: !p.is_pinned } : p)))
    } catch {}
  }

  async function toggleVisibility(post: CreatorPost) {
    const action = post.is_visible ? 'hide' : 'unhide'
    try {
      await apiFetch(`${base}/${post.id}/${action}`, { method: 'PATCH' })
      setPosts((prev) => prev.map((p) => (p.id === post.id ? { ...p, is_visible: !p.is_visible } : p)))
    } catch {}
  }

  async function deletePost(post: CreatorPost) {
    if (!confirm(`Permanently delete this post? This cannot be undone.`)) return
    try {
      await apiFetch(`${base}/${post.id}`, { method: 'DELETE' })
      setPosts((prev) => prev.filter((p) => p.id !== post.id))
    } catch {}
  }

  return (
    <div className="flex flex-col gap-10">

      {/* ── Compose form ── */}
      <form onSubmit={handlePost} className="flex flex-col gap-4 rounded-2xl border border-border bg-white p-6">
        <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-black">New post</p>

        {/* Type tabs */}
        <div className="flex flex-wrap gap-2">
          {POST_TYPES.map((pt) => (
            <button key={pt.value} type="button" onClick={() => setPostType(pt.value)}
              className={['rounded-full border px-4 py-1.5 text-[13px] transition-colors',
                postType === pt.value ? 'border-navy-900 bg-navy-900 text-white' : 'border-border text-black hover:border-slate-400',
              ].join(' ')}
            >{pt.label}</button>
          ))}
        </div>

        {/* Title */}
        {postType !== 'discussion' && (
          <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Title (optional)"
            className="w-full rounded-lg border border-border bg-white px-4 py-2.5 text-sm text-navy-900 placeholder-slate-400 focus:border-teal-300 focus:outline-none focus:ring-1 focus:ring-teal-100" />
        )}

        {/* Rich editor */}
        <RichEditor
          placeholder={
            postType === 'prompt' ? 'What question or invitation do you want to offer the community?'
            : postType === 'announcement' ? 'Share an update, reminder, or moment with your community…'
            : 'Start the conversation…'
          }
          onChange={setBodyHtml}
          editorRef={editorRef}
        />

        {/* Image */}
        <ImageUpload
          spaceSlug={spaceSlug}
          imageUrl={imageUrl}
          imagePreview={imagePreview}
          uploading={uploading}
          onUpload={(url, preview) => { setImageUrl(url); setImagePreview(preview); setUploading(false) }}
          onRemove={() => { setImageUrl(null); setImagePreview(null) }}
        />

        {/* Footer */}
        <div className="flex items-center justify-between">
          <label className="flex items-center gap-2 text-sm text-black">
            <input type="checkbox" checked={isPinned} onChange={(e) => setIsPinned(e.target.checked)} className="rounded border-border" />
            Pin to top
          </label>
          <div className="flex items-center gap-3">
            {error && <span className="text-xs text-red-500">{error}</span>}
            <button type="submit" disabled={posting || isEditorEmpty(bodyHtml) || uploading}
              className="rounded-lg bg-navy-900 px-5 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50">
              {posting ? 'Posting…' : 'Post'}
            </button>
          </div>
        </div>
      </form>

      {/* ── Post list ── */}
      {posts.length === 0 ? (
        <div className="rounded-2xl border border-border bg-white px-8 py-10 text-center">
          <p className="font-serif text-lg text-navy-700">Nothing posted yet</p>
          <p className="mt-1 text-sm text-black">Start with an announcement or a reflection prompt.</p>
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          {posts.map((post) => (
            <div key={post.id} className="rounded-2xl border border-border bg-white">
              {editingId === post.id ? (
                <div className="p-1">
                  <EditForm post={post} base={base} spaceSlug={spaceSlug} onSave={handleEditSave} onCancel={() => setEditingId(null)} />
                </div>
              ) : (
                <div className="px-5 py-4">
                  {/* Status badges */}
                  <div className="mb-2 flex flex-wrap items-center gap-2">
                    <span className="text-[10px] font-semibold uppercase tracking-[0.1em] text-black">
                      {TYPE_LABELS[post.post_type] ?? post.post_type}
                    </span>
                    {post.is_pinned && (
                      <span className="rounded-full bg-teal-50 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.1em] text-teal-600">Pinned</span>
                    )}
                    {!post.is_visible && (
                      <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.1em] text-amber-600">Hidden</span>
                    )}
                  </div>

                  {/* Content */}
                  {post.title && <p className="mb-1 font-medium text-navy-900">{post.title}</p>}
                  {/* Render HTML body or plain text */}
                  {/<[a-z][\s\S]*>/i.test(post.body) ? (
                    <div
                      className="prose-community line-clamp-3 text-sm text-black"
                      dangerouslySetInnerHTML={{ __html: post.body }}
                    />
                  ) : (
                    <p className="line-clamp-3 text-sm text-black">{post.body}</p>
                  )}

                  {/* Image thumbnail */}
                  {post.image_url && (
                    <div className="mt-2">
                      <CommunityImage
                        src={resolveMediaUrl(post.image_url) ?? ''}
                        alt="Post image"
                        className="max-h-32 rounded-lg object-cover"
                      />
                    </div>
                  )}

                  <p className="mt-2 text-xs text-black">
                    {post.author_name} · {formatDate(post.created_at)}
                  </p>

                  {/* Actions */}
                  <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-border pt-3">
                    <button onClick={() => setEditingId(post.id)} className="text-xs text-black hover:text-navy-700">Edit</button>
                    <button onClick={() => togglePin(post)} className="text-xs text-black hover:text-navy-700">{post.is_pinned ? 'Unpin' : 'Pin'}</button>
                    <button onClick={() => toggleVisibility(post)} className="text-xs text-black hover:text-navy-700">{post.is_visible ? 'Hide' : 'Unhide'}</button>
                    <button onClick={() => deletePost(post)} className="ml-auto text-xs text-black hover:text-red-500">Delete</button>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
