'use client'

import React, { useCallback, useEffect, useRef, useState } from 'react'
import { apiUrl } from '@/lib/api'
import type {
  OfferingFile, OfferingFileList, OfferingFileValidationStatus,
} from '@/types/platform'

interface Props {
  spaceSlug: string
  offeringSlug: string
  initial: OfferingFileList | null
}

/** In-flight uploads, tracked separately from stored files. */
interface Upload {
  id: string
  name: string
  percent: number
  /** Set when the upload itself failed — not a validation outcome. */
  error: string | null
  /** The file this upload will replace, if any. */
  replacingId: string | null
}

const MB = 1024 * 1024

function mb(bytes: number): string {
  if (bytes < MB) return `${Math.max(1, Math.round(bytes / 1024))} KB`
  return `${(bytes / MB).toFixed(bytes < 10 * MB ? 1 : 0)} MB`
}

/** Status pill colours. "Checking" is deliberately neutral rather than
 *  warning-coloured — waiting is the normal path, not a problem. */
const STATUS_STYLE: Record<OfferingFileValidationStatus, { bg: string; text: string }> = {
  pending: { bg: 'rgba(148,163,184,0.22)', text: '#334155' },
  passed: { bg: 'rgba(56,160,158,0.16)', text: '#0f766e' },
  rejected: { bg: 'rgba(220,38,38,0.12)', text: '#b91c1c' },
  error: { bg: 'rgba(212,176,72,0.20)', text: '#7A5A00' },
  quarantined: { bg: 'rgba(212,176,72,0.20)', text: '#7A5A00' },
}

/**
 * 📦 Files.
 *
 * Drives the B5 file API: upload, describe, reorder, replace, remove,
 * and the plan allowance that governs all of them.
 *
 * Progress is real
 * ----------------
 * Uploads go through ``XMLHttpRequest`` rather than ``fetch`` for one
 * reason: ``fetch`` has no upload-progress event, so a fetch-based
 * uploader can only show an indeterminate spinner. On a 50 MB file over
 * a domestic connection that is a minute of a creator not knowing
 * whether anything is happening. ``xhr.upload.onprogress`` reports
 * bytes actually sent.
 *
 * Polling, with backoff
 * ---------------------
 * Validation finishes seconds to minutes after an upload, so the list
 * re-fetches while anything is still ``Checking`` or ``On hold``. The
 * interval starts at 2s and backs off to 30s, and stops entirely once
 * every file has settled — a creator who leaves the tab open on a
 * finished Offering costs nothing. Deliberately not websockets: the
 * state is durable in the database, so leaving and returning gives the
 * same answer, which is the approved behaviour.
 */
export default function OfferingFilesClient({
  spaceSlug, offeringSlug, initial,
}: Props) {
  const [data, setData] = useState<OfferingFileList | null>(initial)
  const [uploads, setUploads] = useState<Upload[]>([])
  const [dragging, setDragging] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const fileInput = useRef<HTMLInputElement | null>(null)
  const replaceInput = useRef<HTMLInputElement | null>(null)
  const replaceTarget = useRef<string | null>(null)

  const base = apiUrl(
    `/api/creator/spaces/${spaceSlug}/offerings/${offeringSlug}/files`,
  )

  const refresh = useCallback(async () => {
    try {
      const res = await fetch(base, { credentials: 'include' })
      if (!res.ok) return
      setData(await res.json())
    } catch {
      /* transient — the next poll will try again */
    }
  }, [base])

  // ── Polling with backoff ──────────────────────────────────────────
  const settling = (data?.files ?? []).some(
    (f) => f.validation_status === 'pending' || f.validation_status === 'error',
  ) || uploads.length > 0

  useEffect(() => {
    if (!settling) return
    let cancelled = false
    let delay = 2000
    let timer: ReturnType<typeof setTimeout>

    const tick = async () => {
      if (cancelled) return
      await refresh()
      if (cancelled) return
      // 2s → 3s → 4.5s → … capped at 30s. Fast while a creator is
      // watching, cheap if they walk away.
      delay = Math.min(Math.round(delay * 1.5), 30_000)
      timer = setTimeout(tick, delay)
    }
    timer = setTimeout(tick, delay)
    return () => { cancelled = true; clearTimeout(timer) }
  }, [settling, refresh])

  // ── Upload ────────────────────────────────────────────────────────
  const send = useCallback((file: File, replacingId: string | null) => {
    const id = `up_${Math.random().toString(36).slice(2)}_${file.name}`
    setUploads((prev) => [
      ...prev,
      { id, name: file.name, percent: 0, error: null, replacingId },
    ])
    setError(null)

    const url = replacingId ? `${base}/${replacingId}/replace` : base
    const form = new FormData()
    form.append('file', file)

    const xhr = new XMLHttpRequest()
    xhr.open('POST', url)
    xhr.withCredentials = true

    xhr.upload.onprogress = (e) => {
      if (!e.lengthComputable) return
      const percent = Math.round((e.loaded / e.total) * 100)
      setUploads((prev) =>
        prev.map((u) => (u.id === id ? { ...u, percent } : u)),
      )
    }

    const finish = (message: string | null) => {
      if (message) {
        setUploads((prev) =>
          prev.map((u) => (u.id === id ? { ...u, error: message } : u)),
        )
      } else {
        setUploads((prev) => prev.filter((u) => u.id !== id))
      }
      void refresh()
    }

    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) { finish(null); return }
      let message = `That upload didn't work (${xhr.status}).`
      try {
        const body = JSON.parse(xhr.responseText)
        const detail = body?.detail
        if (detail?.message) message = detail.message
        else if (typeof detail === 'string') message = detail
      } catch { /* keep the generic message */ }
      finish(message)
    }
    xhr.onerror = () => finish(
      'The connection dropped during that upload. Nothing was saved — please try again.',
    )
    xhr.onabort = () => finish('That upload was cancelled.')

    xhr.send(form)
  }, [base, refresh])

  function addFiles(list: FileList | null, replacingId: string | null = null) {
    if (!list || list.length === 0) return
    // One at a time when replacing — a replacement targets one file.
    const chosen = replacingId ? [list[0]] : Array.from(list)
    chosen.forEach((f) => send(f, replacingId))
  }

  // ── Mutations ─────────────────────────────────────────────────────
  async function call(path: string, init: RequestInit) {
    setError(null)
    try {
      const res = await fetch(path, { credentials: 'include', ...init })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        const detail = body?.detail
        setError(
          detail?.message
            ?? (typeof detail === 'string' ? detail : `That didn't work (${res.status}).`),
        )
        return false
      }
      const next = await res.json().catch(() => null)
      if (next && Array.isArray(next.files)) setData(next)
      else await refresh()
      return true
    } catch {
      setError("That didn't work. Please try again.")
      return false
    }
  }

  const describe = (fileId: string, description: string | null) =>
    call(`${base}/${fileId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ description }),
    })

  const remove = (fileId: string) =>
    call(`${base}/${fileId}`, { method: 'DELETE' })

  const reorder = (ids: string[]) =>
    call(`${base}/reorder`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ file_ids: ids }),
    })

  function move(index: number, direction: -1 | 1) {
    const orderable = (data?.files ?? []).filter((f) => !f.replaces_file_id)
    const target = index + direction
    if (target < 0 || target >= orderable.length) return
    const next = [...orderable]
    ;[next[index], next[target]] = [next[target], next[index]]
    void reorder(next.map((f) => f.id))
  }

  const files = data?.files ?? []
  const resourcesLeft = data ? data.resources_allowed - data.resources_used : 0
  const bytesLeft = data ? data.bytes_allowed - data.bytes_used : 0
  const full = resourcesLeft <= 0

  return (
    <div className="max-w-[860px]">
      <div className="mb-6">
        <h2 className="text-[18px] font-semibold text-navy-900">Files</h2>
        <p className="mt-1 text-[14px] text-black">
          The resources people download when they get this Offering.
        </p>
      </div>

      {/* ── Allowance ──────────────────────────────────────────────── */}
      {data && (
        <div className="mb-5 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <p className="text-[13px] font-semibold text-navy-900">
              {data.resources_used} of {data.resources_allowed} file
              {data.resources_allowed === 1 ? '' : 's'} ·{' '}
              {mb(data.bytes_used)} of {mb(data.bytes_allowed)}
            </p>
            <p className="text-[12.5px]" style={{ color: 'rgba(12,24,38,0.55)' }}>
              {data.plan_name} plan · up to {mb(data.max_file_bytes)} per file
              {data.zip_bundles_allowed ? '' : ' · no ZIP bundles'}
            </p>
          </div>
          <div
            className="mt-2 h-1.5 w-full overflow-hidden rounded-full"
            style={{ background: 'rgba(12,24,38,0.08)' }}
            role="img"
            aria-label={`${data.bytes_used} of ${data.bytes_allowed} bytes used`}
          >
            <div
              className="h-full rounded-full"
              style={{
                width: `${Math.min(100, (data.bytes_used / Math.max(1, data.bytes_allowed)) * 100)}%`,
                background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)',
              }}
            />
          </div>
          {data.resources_allowed === 1 && (
            <p className="mt-2 text-[12.5px]" style={{ color: 'rgba(12,24,38,0.55)' }}>
              Your plan includes one downloadable file per Offering.
              Upgrade to Creator to add more, or to sell a ZIP bundle.
            </p>
          )}
        </div>
      )}

      {/* ── Drop zone ──────────────────────────────────────────────── */}
      <div
        onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault()
          setDragging(false)
          if (!full) addFiles(e.dataTransfer.files)
        }}
        className="rounded-2xl border-2 border-dashed p-8 text-center transition-colors"
        style={{
          borderColor: dragging ? '#38A09E' : 'rgba(12,24,38,0.16)',
          background: dragging ? 'rgba(56,160,158,0.05)' : 'white',
          opacity: full ? 0.6 : 1,
        }}
      >
        <p className="text-[15px] font-semibold text-navy-900">
          {full ? 'No room for more files' : 'Drag files here'}
        </p>
        <p className="mx-auto mt-1 max-w-[44ch] text-[13px] leading-relaxed text-black">
          {full
            ? 'Remove a file, or upgrade your plan, to add another.'
            : `or choose them from your computer. ${mb(bytesLeft)} of room left.`}
        </p>
        {!full && (
          <button
            type="button"
            onClick={() => fileInput.current?.click()}
            className="mt-4 rounded-xl px-5 py-2.5 text-[14px] font-semibold text-white transition-opacity hover:opacity-90"
            style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
          >
            Choose files
          </button>
        )}
        <input
          ref={fileInput}
          type="file"
          multiple
          className="hidden"
          onChange={(e) => { addFiles(e.target.files); e.target.value = '' }}
        />
      </div>

      {error && (
        <p className="mt-4 rounded-lg bg-red-50 px-3 py-2 text-[13px] text-red-700">
          {error}
        </p>
      )}

      {/* ── In-flight uploads ──────────────────────────────────────── */}
      {uploads.length > 0 && (
        <div className="mt-5 space-y-2">
          {uploads.map((u) => (
            <div
              key={u.id}
              className="rounded-xl border border-slate-200 bg-white px-4 py-3"
            >
              <div className="flex items-baseline justify-between gap-3">
                <p className="truncate text-[13.5px] font-medium text-navy-900">
                  {u.name}
                  {u.replacingId && (
                    <span className="ml-1 font-normal" style={{ color: 'rgba(12,24,38,0.5)' }}>
                      (replacement)
                    </span>
                  )}
                </p>
                <span className="shrink-0 text-[12.5px]" style={{ color: 'rgba(12,24,38,0.55)' }}>
                  {u.error ? '' : `${u.percent}%`}
                </span>
              </div>
              {u.error ? (
                <div className="mt-2 flex items-start justify-between gap-3">
                  <p className="text-[13px] text-red-700">{u.error}</p>
                  <button
                    type="button"
                    onClick={() => setUploads((p) => p.filter((x) => x.id !== u.id))}
                    className="shrink-0 text-[12.5px] underline"
                    style={{ color: 'rgba(12,24,38,0.55)' }}
                  >
                    Dismiss
                  </button>
                </div>
              ) : (
                <div
                  className="mt-2 h-1.5 w-full overflow-hidden rounded-full"
                  style={{ background: 'rgba(12,24,38,0.08)' }}
                >
                  <div
                    className="h-full rounded-full transition-[width] duration-200"
                    style={{
                      width: `${u.percent}%`,
                      background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)',
                    }}
                  />
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* ── Stored files ───────────────────────────────────────────── */}
      <div className="mt-6 space-y-3">
        {files.length === 0 && uploads.length === 0 && (
          <div className="rounded-xl border border-dashed border-slate-200 bg-white p-8 text-center">
            <p className="text-[14px] text-black">
              No files yet. Add at least one before publishing.
            </p>
          </div>
        )}

        {files
          .filter((f) => !f.replaces_file_id)
          .map((file, index, orderable) => (
            <FileRow
              key={file.id}
              file={file}
              index={index}
              total={orderable.length}
              onDescribe={describe}
              onRemove={remove}
              onMove={move}
              onReplace={(id) => {
                replaceTarget.current = id
                replaceInput.current?.click()
              }}
            />
          ))}
      </div>

      <input
        ref={replaceInput}
        type="file"
        className="hidden"
        onChange={(e) => {
          addFiles(e.target.files, replaceTarget.current)
          replaceTarget.current = null
          e.target.value = ''
        }}
      />

      {settling && (
        <p className="mt-5 text-[12.5px]" style={{ color: 'rgba(12,24,38,0.55)' }} aria-live="polite">
          Checking files… this usually takes under a minute. You can leave this
          page and come back — nothing is lost.
        </p>
      )}
    </div>
  )
}

function FileRow({
  file, index, total, onDescribe, onRemove, onMove, onReplace,
}: {
  file: OfferingFile
  index: number
  total: number
  onDescribe: (id: string, description: string | null) => Promise<boolean>
  onRemove: (id: string) => Promise<boolean>
  onMove: (index: number, direction: -1 | 1) => void
  onReplace: (id: string) => void
}) {
  const [description, setDescription] = useState(file.description ?? '')
  const [editing, setEditing] = useState(false)
  const [saving, setSaving] = useState(false)
  const style = STATUS_STYLE[file.validation_status] ?? STATUS_STYLE.pending

  return (
    <div className="rounded-xl border border-slate-200 bg-white px-4 py-3.5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <p className="truncate text-[14px] font-medium text-navy-900">
              {file.filename}
            </p>
            <span
              className="shrink-0 rounded-full px-2 py-0.5 text-[10.5px] font-semibold uppercase tracking-[0.1em]"
              style={{ background: style.bg, color: style.text }}
            >
              {file.status_label}
            </span>
            {file.replacement_pending && (
              <span
                className="shrink-0 rounded-full px-2 py-0.5 text-[10.5px] font-semibold uppercase tracking-[0.1em]"
                style={{ background: 'rgba(148,163,184,0.22)', color: '#334155' }}
              >
                Replacing
              </span>
            )}
          </div>
          <p className="mt-1 text-[12.5px]" style={{ color: 'rgba(12,24,38,0.55)' }}>
            {mb(file.byte_size)}
            {file.resource_count > 1 && ` · ${file.resource_count} files inside`}
            {file.available_to_purchasers && ' · available to members'}
          </p>

          {file.rejection_reason && (
            <p
              className="mt-2 rounded-lg px-3 py-2 text-[12.5px] leading-relaxed"
              style={{
                background: file.validation_status === 'rejected'
                  ? 'rgba(220,38,38,0.07)'
                  : 'rgba(212,176,72,0.10)',
                color: file.validation_status === 'rejected' ? '#991b1b' : '#6B4F00',
              }}
            >
              {file.rejection_reason}
            </p>
          )}

          {file.replacement_pending && (
            <p className="mt-2 text-[12.5px]" style={{ color: 'rgba(12,24,38,0.55)' }}>
              A new version is being checked. This one stays available until it
              passes — and stays if it doesn&rsquo;t.
            </p>
          )}

          {/* Description */}
          <div className="mt-2">
            {editing ? (
              <div className="flex flex-wrap items-center gap-2">
                <input
                  value={description}
                  maxLength={300}
                  autoFocus
                  placeholder="A 15-minute guided audio practice"
                  onChange={(e) => setDescription(e.target.value)}
                  className="min-w-0 flex-1 rounded-lg border border-slate-200 px-3 py-1.5 text-[13px] outline-none focus:border-teal-400"
                />
                <button
                  type="button"
                  disabled={saving}
                  onClick={async () => {
                    setSaving(true)
                    await onDescribe(file.id, description.trim() || null)
                    setSaving(false)
                    setEditing(false)
                  }}
                  className="rounded-lg border border-slate-200 px-3 py-1.5 text-[12.5px] font-medium text-black hover:border-teal-200"
                >
                  {saving ? 'Saving…' : 'Save'}
                </button>
              </div>
            ) : (
              <button
                type="button"
                onClick={() => setEditing(true)}
                className="text-left text-[12.5px] underline-offset-2 hover:underline"
                style={{ color: file.description ? 'rgba(12,24,38,0.7)' : 'rgba(12,24,38,0.45)' }}
              >
                {file.description || 'Add a description'}
              </button>
            )}
          </div>
        </div>

        {/* Actions */}
        <div className="flex shrink-0 flex-wrap items-center gap-1.5">
          <IconButton
            label="Move up"
            disabled={index === 0}
            onClick={() => onMove(index, -1)}
          >
            ↑
          </IconButton>
          <IconButton
            label="Move down"
            disabled={index === total - 1}
            onClick={() => onMove(index, 1)}
          >
            ↓
          </IconButton>
          <button
            type="button"
            onClick={() => onReplace(file.id)}
            disabled={file.replacement_pending}
            className="rounded-lg border border-slate-200 px-2.5 py-1 text-[12px] font-medium text-black transition-colors hover:border-teal-200 hover:text-teal-700 disabled:opacity-40"
          >
            Replace
          </button>
          <button
            type="button"
            onClick={() => {
              if (confirm(`Remove "${file.filename}" from this Offering?`)) {
                void onRemove(file.id)
              }
            }}
            disabled={file.replacement_pending}
            className="rounded-lg border border-slate-200 px-2.5 py-1 text-[12px] font-medium transition-colors hover:border-red-200 hover:text-red-700 disabled:opacity-40"
            style={{ color: 'rgba(12,24,38,0.7)' }}
          >
            Remove
          </button>
        </div>
      </div>
    </div>
  )
}

function IconButton({
  label, disabled, onClick, children,
}: {
  label: string
  disabled: boolean
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      disabled={disabled}
      onClick={onClick}
      className="rounded-lg border border-slate-200 px-2 py-1 text-[12px] text-black transition-colors hover:border-teal-200 disabled:opacity-30"
    >
      {children}
    </button>
  )
}
