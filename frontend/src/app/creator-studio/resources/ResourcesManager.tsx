'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { apiUrl } from '@/lib/api'
import type { CreatorPathway, CreatorResource, ResourceType } from '@/types/platform'

const RESOURCE_TYPES: { value: ResourceType; label: string; hint: string }[] = [
  { value: 'link',     label: 'Link',     hint: 'Article, tool, or external resource' },
  { value: 'file',     label: 'File',     hint: 'PDF, doc, spreadsheet, or download' },
  { value: 'replay',   label: 'Replay',   hint: 'Recording of a past gathering' },
  { value: 'guide',    label: 'Guide',    hint: 'In-depth guide or reference doc' },
  { value: 'template', label: 'Template', hint: 'Worksheet or reusable template' },
  { value: 'audio',    label: 'Audio',    hint: 'Meditation, podcast, or audio guide' },
  { value: 'video',    label: 'Video',    hint: 'Short explainer or recorded content' },
  { value: 'other',    label: 'Other',    hint: 'Any other supporting material' },
]

const STATUS_PILLS: Record<string, string> = {
  published: 'bg-teal-50 text-teal-700 border-teal-200',
  draft:     'bg-slate-50 text-slate-500 border-slate-200',
}

interface FormState {
  title: string
  description: string
  resource_type: ResourceType
  url: string
  status: 'draft' | 'published'
  scope: 'general' | 'pathway'
  pathway_id: string
}

const EMPTY_FORM: FormState = {
  title: '',
  description: '',
  resource_type: 'link',
  url: '',
  status: 'draft',
  scope: 'general',
  pathway_id: '',
}

interface Props {
  spaceSlug: string
  initialResources: CreatorResource[]
  pathways: CreatorPathway[]
}

export default function ResourcesManager({ spaceSlug, initialResources, pathways }: Props) {
  const router = useRouter()
  const [resources, setResources] = useState<CreatorResource[]>(initialResources)

  const [formMode, setFormMode] = useState<null | 'create' | string>(null)
  const [form, setForm] = useState<FormState>(EMPTY_FORM)
  const [uploadFile, setUploadFile] = useState<File | null>(null)
  const [saving, setSaving] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const [deletingId, setDeletingId] = useState<string | null>(null)

  const inputCls = 'w-full rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 text-[14px] text-navy-900 placeholder-slate-400 shadow-sm outline-none transition-colors focus:border-teal-400'
  const tealBtn = 'inline-flex items-center rounded-xl px-4 py-2 text-[13px] font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-50'
  const tealStyle = { background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }
  const ghostBtn = 'inline-flex items-center rounded-xl border border-slate-200 px-3.5 py-2 text-[13px] font-medium text-slate-600 transition-colors hover:border-teal-200 hover:text-teal-700 disabled:opacity-50'

  const activePaths = pathways.filter((p) => p.status !== 'archived')

  function pathwayTitle(id: string | null) {
    if (!id) return null
    return activePaths.find((p) => p.id === id)?.title ?? null
  }

  function openCreate() {
    setForm(EMPTY_FORM)
    setUploadFile(null)
    setFormError(null)
    setFormMode('create')
  }

  function openEdit(r: CreatorResource) {
    setForm({
      title: r.title,
      description: r.description ?? '',
      resource_type: r.resource_type as ResourceType,
      url: r.url ?? '',
      status: r.status,
      scope: r.scope ?? 'general',
      pathway_id: r.pathway_id ?? '',
    })
    setUploadFile(null)
    setFormError(null)
    setFormMode(r.id)
  }

  function cancelForm() {
    setFormMode(null)
    setFormError(null)
    setUploadFile(null)
  }

  async function handleSave() {
    if (!form.title.trim()) { setFormError('Title is required.'); return }
    if (form.scope === 'pathway' && !form.pathway_id) {
      setFormError('Please select a pathway for pathway-specific resources.')
      return
    }
    setSaving(true); setFormError(null)
    try {
      let res: Response

      const scopePayload = {
        scope: form.scope,
        pathway_id: form.scope === 'pathway' ? form.pathway_id : null,
      }

      if (uploadFile) {
        const fd = new FormData()
        fd.append('file', uploadFile)
        fd.append('title', form.title.trim())
        fd.append('description', form.description.trim())
        fd.append('resource_type', form.resource_type)
        fd.append('status', form.status)
        fd.append('scope', scopePayload.scope)
        if (scopePayload.pathway_id) fd.append('pathway_id', scopePayload.pathway_id)
        res = await fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/resources/upload`), {
          method: 'POST',
          credentials: 'include',
          body: fd,
        })
      } else if (formMode === 'create') {
        res = await fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/resources`), {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            title: form.title.trim(),
            description: form.description.trim() || null,
            resource_type: form.resource_type,
            url: form.url.trim() || null,
            status: form.status,
            ...scopePayload,
          }),
        })
      } else {
        res = await fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/resources/${formMode}`), {
          method: 'PATCH',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            title: form.title.trim(),
            description: form.description.trim() || null,
            resource_type: form.resource_type,
            url: form.url.trim() || null,
            status: form.status,
            ...scopePayload,
          }),
        })
      }

      if (!res.ok) {
        const b = await res.json().catch(() => ({}))
        throw new Error(typeof b.detail === 'string' ? b.detail : `Save failed (${res.status})`)
      }

      const saved: CreatorResource = await res.json()

      if (formMode === 'create' || uploadFile) {
        setResources((prev) => [...prev, saved])
      } else {
        setResources((prev) => prev.map((r) => r.id === saved.id ? saved : r))
      }
      setFormMode(null)
      router.refresh()
    } catch (err) {
      setFormError(err instanceof Error ? err.message : 'Something went wrong.')
    } finally {
      setSaving(false)
    }
  }

  async function handleDelete(id: string) {
    if (!confirm('Delete this resource? This cannot be undone.')) return
    setDeletingId(id)
    try {
      const res = await fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/resources/${id}`), {
        method: 'DELETE',
        credentials: 'include',
      })
      if (!res.ok) throw new Error(`Delete failed (${res.status})`)
      setResources((prev) => prev.filter((r) => r.id !== id))
      router.refresh()
    } catch {
      // silently ignore
    } finally {
      setDeletingId(null)
    }
  }

  async function handleTogglePublish(r: CreatorResource) {
    const newStatus = r.status === 'published' ? 'draft' : 'published'
    try {
      const res = await fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/resources/${r.id}`), {
        method: 'PATCH',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: newStatus }),
      })
      if (!res.ok) return
      const updated: CreatorResource = await res.json()
      setResources((prev) => prev.map((x) => x.id === updated.id ? updated : x))
    } catch { /* silent */ }
  }

  const published = resources.filter((r) => r.status === 'published').length
  const drafts = resources.filter((r) => r.status === 'draft').length

  return (
    <div>
      {/* Stats row */}
      <div className="mb-6 grid grid-cols-3 gap-4">
        {[
          { label: 'Total', value: resources.length },
          { label: 'Published', value: published },
          { label: 'Drafts', value: drafts },
        ].map(({ label, value }) => (
          <div key={label} className="rounded-2xl border border-border bg-white px-5 py-4">
            <p className="font-serif text-[26px] text-navy-900">{value}</p>
            <p className="text-[12px] text-slate-400">{label}</p>
          </div>
        ))}
      </div>

      {formMode === null && (
        <div className="mb-6">
          <button onClick={openCreate} className={tealBtn} style={tealStyle}>
            + Add resource
          </button>
        </div>
      )}

      {/* Create / Edit form */}
      {formMode !== null && (
        <div className="mb-6 rounded-2xl border border-border bg-white p-6">
          <h3 className="mb-5 text-[16px] font-semibold text-navy-900">
            {formMode === 'create' ? 'Add resource' : 'Edit resource'}
          </h3>

          <div className="space-y-4">
            {/* Title */}
            <div>
              <label className="mb-1.5 block text-[13px] font-semibold text-navy-900">
                Title <span style={{ color: '#38A09E' }}>*</span>
              </label>
              <input
                type="text"
                value={form.title}
                onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))}
                maxLength={300}
                placeholder="e.g. Breath awareness practice"
                className={inputCls}
              />
            </div>

            {/* Resource type */}
            <div>
              <label className="mb-1.5 block text-[13px] font-semibold text-navy-900">Type</label>
              <select
                value={form.resource_type}
                onChange={(e) => setForm((f) => ({ ...f, resource_type: e.target.value as ResourceType }))}
                className={inputCls}
              >
                {RESOURCE_TYPES.map((t) => (
                  <option key={t.value} value={t.value}>{t.label} — {t.hint}</option>
                ))}
              </select>
            </div>

            {/* Description */}
            <div>
              <label className="mb-1.5 block text-[13px] font-semibold text-navy-900">
                Description <span className="font-normal text-slate-400">(optional)</span>
              </label>
              <textarea
                value={form.description}
                onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
                rows={2}
                placeholder="Brief description of this resource"
                className={inputCls + ' resize-none'}
              />
            </div>

            {/* URL */}
            {!uploadFile && (
              <div>
                <label className="mb-1.5 block text-[13px] font-semibold text-navy-900">
                  URL <span className="font-normal text-slate-400">(for links, replays, etc.)</span>
                </label>
                <input
                  type="url"
                  value={form.url}
                  onChange={(e) => setForm((f) => ({ ...f, url: e.target.value }))}
                  placeholder="https://…"
                  className={inputCls}
                />
              </div>
            )}

            {/* File upload — only for new resources */}
            {formMode === 'create' && (
              <div>
                <label className="mb-1.5 block text-[13px] font-semibold text-navy-900">
                  Or upload a file <span className="font-normal text-slate-400">(PDF, doc, audio, video…)</span>
                </label>
                <input
                  type="file"
                  accept=".pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.jpg,.jpeg,.png,.webp,.mp3,.wav,.m4a,.mp4,.mov"
                  onChange={(e) => {
                    const f = e.target.files?.[0] ?? null
                    setUploadFile(f)
                    if (f) setForm((prev) => ({ ...prev, url: '' }))
                  }}
                  className="block w-full text-[13px] text-slate-600 file:mr-3 file:rounded-lg file:border-0 file:bg-slate-100 file:px-3 file:py-1.5 file:text-[12px] file:font-medium file:text-slate-600"
                />
                {uploadFile && (
                  <p className="mt-1 text-[12px] text-slate-400">
                    {uploadFile.name} ({(uploadFile.size / 1024).toFixed(0)} KB)
                  </p>
                )}
              </div>
            )}

            {/* Resource access (scope) */}
            <div>
              <label className="mb-1.5 block text-[13px] font-semibold text-navy-900">
                Resource access
              </label>
              <p className="mb-2.5 text-[12px] text-slate-400">
                General resources are visible to all members. Pathway resources only appear for
                members who have access to that pathway.
              </p>
              <div className="flex gap-3">
                {([
                  { value: 'general', label: 'General', hint: 'Visible to all members' },
                  { value: 'pathway', label: 'Pathway-specific', hint: 'Pathway members only' },
                ] as const).map((s) => (
                  <label
                    key={s.value}
                    className="flex cursor-pointer items-center gap-2.5 rounded-xl border px-4 py-2.5 text-[13px] font-medium transition-all"
                    style={{
                      borderColor: form.scope === s.value ? 'rgba(56,160,158,0.40)' : '#e2e8f0',
                      background: form.scope === s.value ? 'rgba(56,160,158,0.06)' : 'transparent',
                      color: form.scope === s.value ? '#1E6E6C' : '#6B7A8D',
                    }}
                  >
                    <input
                      type="radio"
                      name="res-scope"
                      value={s.value}
                      checked={form.scope === s.value}
                      onChange={() => setForm((f) => ({ ...f, scope: s.value, pathway_id: '' }))}
                      className="accent-teal-500"
                    />
                    {s.label}
                  </label>
                ))}
              </div>

              {/* Pathway dropdown */}
              {form.scope === 'pathway' && (
                <div className="mt-3">
                  <label className="mb-1.5 block text-[13px] font-semibold text-navy-900">
                    Pathway <span style={{ color: '#38A09E' }}>*</span>
                  </label>
                  {activePaths.length === 0 ? (
                    <p className="text-[13px] text-slate-400">No pathways found. Create a pathway first.</p>
                  ) : (
                    <select
                      value={form.pathway_id}
                      onChange={(e) => setForm((f) => ({ ...f, pathway_id: e.target.value }))}
                      className={inputCls}
                    >
                      <option value="">Select a pathway…</option>
                      {activePaths.map((p) => (
                        <option key={p.id} value={p.id}>{p.title}</option>
                      ))}
                    </select>
                  )}
                </div>
              )}
            </div>

            {/* Status */}
            <div>
              <label className="mb-2 block text-[13px] font-semibold text-navy-900">Status</label>
              <div className="flex gap-3">
                {(['draft', 'published'] as const).map((s) => (
                  <label
                    key={s}
                    className="flex cursor-pointer items-center gap-2.5 rounded-xl border px-4 py-2.5 text-[13px] font-medium transition-all"
                    style={{
                      borderColor: form.status === s ? 'rgba(56,160,158,0.40)' : '#e2e8f0',
                      background: form.status === s ? 'rgba(56,160,158,0.06)' : 'transparent',
                      color: form.status === s ? '#1E6E6C' : '#6B7A8D',
                    }}
                  >
                    <input
                      type="radio"
                      name="res-status"
                      value={s}
                      checked={form.status === s}
                      onChange={() => setForm((f) => ({ ...f, status: s }))}
                      className="accent-teal-500"
                    />
                    {s === 'draft' ? 'Draft' : 'Published'}
                  </label>
                ))}
              </div>
            </div>

            {formError && <p className="text-[13px] text-red-500">{formError}</p>}

            <div className="flex items-center gap-3 pt-1">
              <button onClick={handleSave} disabled={saving} className={tealBtn} style={tealStyle}>
                {saving ? 'Saving…' : formMode === 'create' ? 'Add resource' : 'Save changes'}
              </button>
              <button onClick={cancelForm} disabled={saving} className={ghostBtn}>
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Resource list */}
      {resources.length === 0 && formMode === null ? (
        <div className="rounded-2xl border border-dashed border-slate-200 bg-white py-16 text-center">
          <p className="mb-1 text-[16px] font-semibold text-navy-900">No resources yet</p>
          <p className="mb-5 text-[14px] text-slate-500">Add links, files, guides, and tools for your members.</p>
          <button onClick={openCreate} className={tealBtn} style={tealStyle}>+ Add first resource</button>
        </div>
      ) : resources.length > 0 ? (
        <div className="space-y-3">
          {resources.map((r) => {
            const scopeLabel = r.scope === 'pathway'
              ? (pathwayTitle(r.pathway_id ?? null) ?? 'Pathway')
              : 'General'
            const scopePillCls = r.scope === 'pathway'
              ? 'bg-indigo-50 text-indigo-700 border-indigo-200'
              : 'bg-slate-50 text-slate-500 border-slate-200'

            return (
              <div
                key={r.id}
                className="rounded-2xl border border-border bg-white px-5 py-4"
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0 flex-1">
                    <div className="mb-1 flex flex-wrap items-center gap-2">
                      <p className="text-[14px] font-semibold text-navy-900">{r.title}</p>
                      <span className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${STATUS_PILLS[r.status] ?? STATUS_PILLS.draft}`}>
                        {r.status}
                      </span>
                      <span className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${scopePillCls}`}>
                        {scopeLabel}
                      </span>
                      <span className="rounded-full border border-slate-100 bg-slate-50 px-2 py-0.5 text-[10px] text-slate-500">
                        {r.resource_type}
                      </span>
                    </div>
                    {r.description && (
                      <p className="mb-1 line-clamp-1 text-[13px] text-slate-500">{r.description}</p>
                    )}
                    {(r.file_name || r.url) && (
                      <p className="truncate text-[11.5px] text-slate-400">{r.file_name ?? r.url}</p>
                    )}
                  </div>

                  <div className="flex shrink-0 items-center gap-2">
                    <button onClick={() => handleTogglePublish(r)} className={ghostBtn}>
                      {r.status === 'published' ? 'Unpublish' : 'Publish'}
                    </button>
                    <button onClick={() => openEdit(r)} className={ghostBtn}>
                      Edit
                    </button>
                    <button
                      onClick={() => handleDelete(r.id)}
                      disabled={deletingId === r.id}
                      className="inline-flex items-center rounded-xl border border-red-100 px-3.5 py-2 text-[13px] font-medium text-red-500 transition-colors hover:border-red-200 hover:bg-red-50 disabled:opacity-50"
                    >
                      {deletingId === r.id ? '…' : 'Delete'}
                    </button>
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      ) : null}
    </div>
  )
}
