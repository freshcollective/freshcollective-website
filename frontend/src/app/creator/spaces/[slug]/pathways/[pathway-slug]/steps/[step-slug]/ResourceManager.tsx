'use client'

import { useRef, useState } from 'react'
import { apiUrl } from '@/lib/api'
import type { StepResource } from '@/types/platform'

const LINK_TYPES = [
  { value: 'link', label: 'Link' },
  { value: 'video', label: 'Video' },
  { value: 'audio', label: 'Audio' },
]

const TYPE_LABEL: Record<string, string> = {
  link: 'Link',
  video: 'Video',
  audio: 'Audio',
  pdf: 'PDF',
  file: 'File',
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

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
// Inline edit form
// ---------------------------------------------------------------------------

function EditForm({
  resource,
  base,
  onSave,
  onCancel,
}: {
  resource: StepResource
  base: string
  onSave: (updated: StepResource) => void
  onCancel: () => void
}) {
  const [title, setTitle] = useState(resource.title)
  const [description, setDescription] = useState(resource.description ?? '')
  const [url, setUrl] = useState(resource.url ?? '')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const isUpload = Boolean(resource.file_name)

  async function handleSave(e: React.FormEvent) {
    e.preventDefault()
    if (!title.trim()) return
    setSaving(true)
    setError(null)
    try {
      const body: Record<string, string | null> = {
        title: title.trim(),
        description: description.trim() || null,
      }
      if (!isUpload) body.url = url.trim() || null
      const res = await apiFetch(`${base}/${resource.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      onSave(await res.json())
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <form
      onSubmit={handleSave}
      className="flex flex-col gap-3 rounded-xl border border-teal-200 bg-teal-50/30 px-4 py-3"
    >
      <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-400">
        Editing resource
      </p>
      <input
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        required
        placeholder="Title"
        className="w-full rounded-lg border border-border bg-white px-3 py-2 text-sm text-navy-900 placeholder-slate-400 focus:outline-none focus:ring-1 focus:ring-navy-300"
      />
      <input
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        placeholder="Description (optional)"
        className="w-full rounded-lg border border-border bg-white px-3 py-2 text-sm text-navy-900 placeholder-slate-400 focus:outline-none focus:ring-1 focus:ring-navy-300"
      />
      {!isUpload && (
        <input
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="URL"
          className="w-full rounded-lg border border-border bg-white px-3 py-2 text-sm text-navy-900 placeholder-slate-400 focus:outline-none focus:ring-1 focus:ring-navy-300"
        />
      )}
      <div className="flex items-center justify-end gap-3">
        {error && <span className="text-xs text-red-500">{error}</span>}
        <button
          type="button"
          onClick={onCancel}
          className="text-sm text-slate-400 hover:text-slate-600"
        >
          Cancel
        </button>
        <button
          type="submit"
          disabled={saving || !title.trim()}
          className="rounded-lg bg-navy-900 px-4 py-1.5 text-sm font-medium text-white disabled:opacity-50 hover:opacity-90"
        >
          {saving ? 'Saving…' : 'Save'}
        </button>
      </div>
    </form>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function ResourceManager({
  stepId,
  spaceSlug,
  pathwaySlug,
  stepSlug,
  initialResources,
}: {
  stepId: string
  spaceSlug: string
  pathwaySlug: string
  stepSlug: string
  initialResources: StepResource[]
}) {
  const base = `/api/creator/spaces/${spaceSlug}/pathways/${pathwaySlug}/steps/${stepSlug}/resources`

  const [resources, setResources] = useState<StepResource[]>(initialResources)
  const [mode, setMode] = useState<'idle' | 'add-link' | 'upload'>('idle')
  const [editingId, setEditingId] = useState<string | null>(null)

  // Link form state
  const [linkTitle, setLinkTitle] = useState('')
  const [linkDesc, setLinkDesc] = useState('')
  const [linkType, setLinkType] = useState('link')
  const [linkUrl, setLinkUrl] = useState('')

  // Upload form state
  const [uploadTitle, setUploadTitle] = useState('')
  const [uploadDesc, setUploadDesc] = useState('')
  const [uploadFile, setUploadFile] = useState<File | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function resetForms() {
    setMode('idle')
    setLinkTitle(''); setLinkDesc(''); setLinkType('link'); setLinkUrl('')
    setUploadTitle(''); setUploadDesc(''); setUploadFile(null)
    setError(null)
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  async function handleAddLink(e: React.FormEvent) {
    e.preventDefault()
    if (!linkTitle.trim() || !linkUrl.trim()) return
    setSubmitting(true)
    setError(null)
    try {
      const res = await apiFetch(base, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: linkTitle.trim(),
          description: linkDesc.trim() || null,
          resource_type: linkType,
          url: linkUrl.trim(),
        }),
      })
      const created: StepResource = await res.json()
      setResources((prev) => [...prev, created])
      resetForms()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not add link.')
    } finally {
      setSubmitting(false)
    }
  }

  async function handleUpload(e: React.FormEvent) {
    e.preventDefault()
    if (!uploadTitle.trim() || !uploadFile) return
    setSubmitting(true)
    setError(null)
    try {
      const form = new FormData()
      form.append('title', uploadTitle.trim())
      if (uploadDesc.trim()) form.append('description', uploadDesc.trim())
      form.append('file', uploadFile)
      const res = await apiFetch(`${base}/upload`, { method: 'POST', body: form })
      const created: StepResource = await res.json()
      setResources((prev) => [...prev, created])
      resetForms()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not upload file.')
    } finally {
      setSubmitting(false)
    }
  }

  function handleEditSave(updated: StepResource) {
    setResources((prev) => prev.map((r) => (r.id === updated.id ? updated : r)))
    setEditingId(null)
  }

  async function handleDelete(resource: StepResource) {
    if (!confirm(`Delete "${resource.title}"? This cannot be undone.`)) return
    try {
      await apiFetch(`${base}/${resource.id}`, { method: 'DELETE' })
      setResources((prev) => prev.filter((r) => r.id !== resource.id))
    } catch (err) {
      console.error('Delete failed:', err)
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-400">
          Resources
        </p>
        <p className="mt-1 text-xs text-slate-400">
          Supplementary materials learners see below the step content.
        </p>
      </div>

      {/* Resource list */}
      {resources.length > 0 && (
        <div className="flex flex-col gap-2">
          {resources.map((resource) =>
            editingId === resource.id ? (
              <EditForm
                key={resource.id}
                resource={resource}
                base={base}
                onSave={handleEditSave}
                onCancel={() => setEditingId(null)}
              />
            ) : (
              <div
                key={resource.id}
                className="flex items-start justify-between gap-4 rounded-xl border border-border bg-surface px-4 py-3"
              >
                <div className="min-w-0 flex-1">
                  <div className="mb-0.5 flex items-center gap-2">
                    <span className="rounded-full border border-slate-200 bg-white px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.1em] text-slate-500">
                      {TYPE_LABEL[resource.resource_type] ?? resource.resource_type}
                    </span>
                    {resource.file_size && (
                      <span className="text-xs text-slate-400">{formatBytes(resource.file_size)}</span>
                    )}
                  </div>
                  <p className="text-sm font-medium text-navy-900">{resource.title}</p>
                  {resource.description && (
                    <p className="mt-0.5 text-xs text-slate-500">{resource.description}</p>
                  )}
                  {resource.url && (
                    <p className="mt-0.5 truncate text-xs text-slate-400">
                      {resource.file_name ?? resource.url}
                    </p>
                  )}
                </div>
                <div className="flex shrink-0 items-center gap-3 pt-0.5">
                  <button
                    onClick={() => setEditingId(resource.id)}
                    className="text-xs text-slate-400 hover:text-navy-700"
                  >
                    Edit
                  </button>
                  <button
                    onClick={() => handleDelete(resource)}
                    className="text-xs text-slate-400 hover:text-red-500"
                  >
                    Delete
                  </button>
                </div>
              </div>
            ),
          )}
        </div>
      )}

      {/* Add buttons */}
      {mode === 'idle' && (
        <div className="flex flex-wrap gap-2">
          <button
            onClick={() => setMode('add-link')}
            className="rounded-lg border border-border bg-white px-3.5 py-2 text-sm text-slate-600 transition-colors hover:border-navy-300 hover:text-navy-700"
          >
            + Add link
          </button>
          <button
            onClick={() => setMode('upload')}
            className="rounded-lg border border-border bg-white px-3.5 py-2 text-sm text-slate-600 transition-colors hover:border-navy-300 hover:text-navy-700"
          >
            + Upload file
          </button>
        </div>
      )}

      {/* Add link form */}
      {mode === 'add-link' && (
        <form
          onSubmit={handleAddLink}
          className="flex flex-col gap-3 rounded-xl border border-border bg-surface px-5 py-4"
        >
          <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-400">
            Add external link
          </p>

          <div className="flex flex-wrap gap-2">
            {LINK_TYPES.map((t) => (
              <button
                key={t.value}
                type="button"
                onClick={() => setLinkType(t.value)}
                className={[
                  'rounded-full border px-3 py-1 text-xs transition-colors',
                  linkType === t.value
                    ? 'border-navy-900 bg-navy-900 text-white'
                    : 'border-border text-slate-500 hover:border-slate-400',
                ].join(' ')}
              >
                {t.label}
              </button>
            ))}
          </div>

          <input
            value={linkTitle}
            onChange={(e) => setLinkTitle(e.target.value)}
            required
            placeholder="Title"
            className="w-full rounded-lg border border-border bg-white px-3 py-2 text-sm text-navy-900 placeholder-slate-400 focus:outline-none focus:ring-1 focus:ring-navy-300"
          />
          <input
            value={linkDesc}
            onChange={(e) => setLinkDesc(e.target.value)}
            placeholder="Description (optional)"
            className="w-full rounded-lg border border-border bg-white px-3 py-2 text-sm text-navy-900 placeholder-slate-400 focus:outline-none focus:ring-1 focus:ring-navy-300"
          />
          <input
            type="url"
            value={linkUrl}
            onChange={(e) => setLinkUrl(e.target.value)}
            required
            placeholder="https://…"
            className="w-full rounded-lg border border-border bg-white px-3 py-2 text-sm text-navy-900 placeholder-slate-400 focus:outline-none focus:ring-1 focus:ring-navy-300"
          />

          <div className="flex items-center justify-between">
            <button
              type="button"
              onClick={resetForms}
              className="text-sm text-slate-400 hover:text-slate-600"
            >
              Cancel
            </button>
            <div className="flex items-center gap-3">
              {error && <span className="text-xs text-red-500">{error}</span>}
              <button
                type="submit"
                disabled={submitting || !linkTitle.trim() || !linkUrl.trim()}
                className="rounded-lg bg-navy-900 px-4 py-1.5 text-sm font-medium text-white disabled:opacity-50 hover:opacity-90"
              >
                {submitting ? 'Adding…' : 'Add link'}
              </button>
            </div>
          </div>
        </form>
      )}

      {/* Upload form */}
      {mode === 'upload' && (
        <form
          onSubmit={handleUpload}
          className="flex flex-col gap-3 rounded-xl border border-border bg-surface px-5 py-4"
        >
          <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-400">
            Upload file
          </p>
          <p className="text-xs text-slate-400">
            Allowed: PDF, MP4, MOV, MP3, WAV, M4A, DOCX, PNG, JPG · Max 200 MB
          </p>

          <input
            value={uploadTitle}
            onChange={(e) => setUploadTitle(e.target.value)}
            required
            placeholder="Title"
            className="w-full rounded-lg border border-border bg-white px-3 py-2 text-sm text-navy-900 placeholder-slate-400 focus:outline-none focus:ring-1 focus:ring-navy-300"
          />
          <input
            value={uploadDesc}
            onChange={(e) => setUploadDesc(e.target.value)}
            placeholder="Description (optional)"
            className="w-full rounded-lg border border-border bg-white px-3 py-2 text-sm text-navy-900 placeholder-slate-400 focus:outline-none focus:ring-1 focus:ring-navy-300"
          />

          <label className="flex cursor-pointer flex-col items-center gap-2 rounded-xl border-2 border-dashed border-slate-200 bg-white px-4 py-6 text-center transition-colors hover:border-navy-300">
            <span className="text-sm text-slate-500">
              {uploadFile ? uploadFile.name : 'Choose a file…'}
            </span>
            {uploadFile && (
              <span className="text-xs text-slate-400">{formatBytes(uploadFile.size)}</span>
            )}
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf,.mp4,.mov,.mp3,.wav,.m4a,.docx,.png,.jpg,.jpeg"
              className="sr-only"
              onChange={(e) => setUploadFile(e.target.files?.[0] ?? null)}
            />
          </label>

          <div className="flex items-center justify-between">
            <button
              type="button"
              onClick={resetForms}
              className="text-sm text-slate-400 hover:text-slate-600"
            >
              Cancel
            </button>
            <div className="flex items-center gap-3">
              {error && <span className="text-xs text-red-500">{error}</span>}
              <button
                type="submit"
                disabled={submitting || !uploadTitle.trim() || !uploadFile}
                className="rounded-lg bg-navy-900 px-4 py-1.5 text-sm font-medium text-white disabled:opacity-50 hover:opacity-90"
              >
                {submitting ? 'Uploading…' : 'Upload'}
              </button>
            </div>
          </div>
        </form>
      )}
    </div>
  )
}
