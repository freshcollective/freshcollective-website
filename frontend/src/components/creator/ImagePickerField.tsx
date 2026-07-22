'use client'

/**
 * Unified image picker for pathway cover, section banner, and step banner.
 *
 * UX:
 *   - Single "Choose image" button (or "Replace" + "Remove" when a value is set)
 *   - Opens a modal with three tabs:
 *       1. Upload          — file input → POST /api/creator/spaces/{slug}/media
 *       2. Assets   — list of existing image assets, click to select
 *       3. External URL    — paste an https:// URL
 *   - All three paths produce a single URL string returned via onChange().
 *
 * Storage: the parent saves the URL into a model field (cover_image_url,
 * banner_image_url, etc.). Existing values keep working — pre-existing
 * banner URLs and Asset Library paths render unchanged.
 */

import { useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import { apiUrl } from '@/lib/api'
import type { CreatorMediaAsset } from '@/types/platform'

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'
const ACCEPTED_IMAGE_MIME = 'image/jpeg,image/png,image/webp,image/gif'

function bannerPreviewSrc(url: string): string {
  if (url.startsWith('http')) return url
  if (url.startsWith('/')) return `${API_BASE}${url}`
  return `${API_BASE}/${url}`
}

function assetToUrl(asset: CreatorMediaAsset): string {
  const u = asset.file_url
  if (u.startsWith('http') || u.startsWith('/')) return u
  return `/api/uploads/${u}`
}


interface Props {
  /** Current image URL, or null/'' for no image. */
  value: string | null
  /** Called with the new URL (Asset Library path, https URL, or upload result), or null to clear. */
  onChange: (next: string | null) => void
  /** Required — used for the upload endpoint and to fetch the collective's assets. */
  spaceSlug: string
  /**
   * Initial asset snapshot (optional). If omitted, the modal fetches
   * fresh on open. Newly uploaded assets are also prepended after upload.
   */
  initialAssets?: CreatorMediaAsset[]
  /** Small text under the picker. */
  helperText?: string
  /** Preview aspect ratio. Defaults to '16/9'. */
  aspectRatio?: string
}

export default function ImagePickerField({
  value,
  onChange,
  spaceSlug,
  initialAssets,
  helperText,
  aspectRatio = '16/9',
}: Props) {
  const [modalOpen, setModalOpen] = useState(false)

  return (
    <div className="space-y-3">
      {/* Preview */}
      {value ? (
        <div className="relative overflow-hidden rounded-xl border border-slate-200 bg-slate-100">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={bannerPreviewSrc(value)}
            alt="Image preview"
            className="block w-full object-cover"
            style={{ aspectRatio }}
          />
        </div>
      ) : (
        <div
          className="flex items-center justify-center rounded-xl border border-dashed border-slate-200 bg-slate-50 text-[13px] text-black"
          style={{ aspectRatio }}
        >
          No image selected
        </div>
      )}

      {/* Buttons */}
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => setModalOpen(true)}
          className="rounded-lg px-4 py-2 text-[13px] font-semibold text-white transition-opacity hover:opacity-90"
          style={{ background: '#38A09E' }}
        >
          {value ? 'Replace image' : 'Choose image'}
        </button>
        {value && (
          <button
            type="button"
            onClick={() => onChange(null)}
            className="rounded-lg border border-slate-200 px-3 py-2 text-[13px] font-medium text-black hover:bg-slate-50"
          >
            Remove
          </button>
        )}
      </div>

      {helperText && <p className="text-[12px] text-black">{helperText}</p>}

      {modalOpen && (
        <ImagePickerModal
          spaceSlug={spaceSlug}
          initialAssets={initialAssets}
          onClose={() => setModalOpen(false)}
          onPicked={(url) => {
            onChange(url)
            setModalOpen(false)
          }}
        />
      )}
    </div>
  )
}


// ---------------------------------------------------------------------------
// Modal
// ---------------------------------------------------------------------------

type Tab = 'upload' | 'library' | 'external'

function ImagePickerModal({
  spaceSlug,
  initialAssets,
  onClose,
  onPicked,
}: {
  spaceSlug: string
  initialAssets?: CreatorMediaAsset[]
  onClose: () => void
  onPicked: (url: string) => void
}) {
  const [tab, setTab] = useState<Tab>('upload')
  const [assets, setAssets] = useState<CreatorMediaAsset[]>(initialAssets ?? [])
  // Loading state initialised based on whether we have a snapshot; the effect
  // never sets it synchronously (lint rule react-hooks/set-state-in-effect).
  const [assetsLoading, setAssetsLoading] = useState(!initialAssets || initialAssets.length === 0)

  // Fetch latest assets on open so newly added items appear without page refresh
  useEffect(() => {
    let cancelled = false
    fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/media`), { credentials: 'include' })
      .then((r) => r.ok ? r.json() : [])
      .then((data: CreatorMediaAsset[]) => {
        if (!cancelled) {
          setAssets(data)
          setAssetsLoading(false)
        }
      })
      .catch(() => {
        if (!cancelled) setAssetsLoading(false)
      })
    return () => { cancelled = true }
  }, [spaceSlug])

  function handleAssetUploaded(asset: CreatorMediaAsset) {
    // Prepend so the new asset is visible if user flips to Assets next
    setAssets((prev) => [asset, ...prev.filter((a) => a.id !== asset.id)])
    onPicked(assetToUrl(asset))
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/40" onClick={onClose} aria-hidden="true" />
      <div className="relative w-full max-w-2xl overflow-hidden rounded-2xl bg-white shadow-2xl">
        <div className="flex items-center justify-between border-b border-slate-100 px-6 py-4">
          <h2 className="text-[16px] font-semibold text-navy-900">Choose image</h2>
          <button
            type="button"
            onClick={onClose}
            className="flex h-8 w-8 items-center justify-center rounded text-slate-400 hover:bg-slate-100 hover:text-slate-700"
            aria-label="Close"
          >
            ✕
          </button>
        </div>

        {/* Tabs */}
        <div className="flex gap-1 border-b border-slate-100 px-6">
          {([
            { value: 'upload',   label: 'Upload new image' },
            { value: 'library',  label: 'Assets' },
            { value: 'external', label: 'External URL' },
          ] as const).map((t) => (
            <button
              key={t.value}
              type="button"
              onClick={() => setTab(t.value)}
              className={`px-3 py-3 text-[13px] font-semibold transition-colors ${
                tab === t.value ? 'border-b-2 border-teal-500 text-teal-700' : 'text-black hover:text-navy-900'
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>

        <div className="max-h-[60vh] overflow-y-auto px-6 py-5">
          {tab === 'upload'   && <UploadTab spaceSlug={spaceSlug} onUploaded={handleAssetUploaded} />}
          {tab === 'library'  && <LibraryTab assets={assets} loading={assetsLoading} onPick={(a) => onPicked(assetToUrl(a))} />}
          {tab === 'external' && <ExternalUrlTab onPick={onPicked} />}
        </div>
      </div>
    </div>
  )
}


// ---------------------------------------------------------------------------
// Tab: Upload
// ---------------------------------------------------------------------------

function UploadTab({
  spaceSlug,
  onUploaded,
}: {
  spaceSlug: string
  onUploaded: (asset: CreatorMediaAsset) => void
}) {
  const fileRef = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [title, setTitle] = useState('')
  const [previewSrc, setPreviewSrc] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0] ?? null
    setFile(f)
    setError(null)
    if (f) {
      if (!title.trim()) setTitle(f.name.replace(/\.[^/.]+$/, ''))
      const reader = new FileReader()
      reader.onload = (ev) => setPreviewSrc(ev.target?.result as string)
      reader.readAsDataURL(f)
    } else {
      setPreviewSrc(null)
    }
  }

  async function handleUpload(e: React.FormEvent) {
    e.preventDefault()
    if (!file) { setError('Please select a file.'); return }
    setUploading(true)
    setError(null)
    try {
      const fd = new FormData()
      fd.append('file', file)
      fd.append('title', title.trim() || file.name)
      const res = await fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/media`), {
        method: 'POST',
        body: fd,
        credentials: 'include',
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(typeof body.detail === 'string' ? body.detail : `Upload failed (${res.status})`)
      }
      const asset: CreatorMediaAsset = await res.json()
      onUploaded(asset)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Upload failed.')
    } finally {
      setUploading(false)
    }
  }

  return (
    <form onSubmit={handleUpload} className="space-y-4">
      <div>
        <label className="field-label">Image file</label>
        <input
          ref={fileRef}
          type="file"
          accept={ACCEPTED_IMAGE_MIME}
          onChange={handleFileChange}
          className="block w-full text-[13px] text-black file:mr-3 file:rounded-lg file:border-0 file:bg-teal-500 file:px-4 file:py-2 file:text-[13px] file:font-semibold file:text-white hover:file:bg-teal-600"
        />
        <p className="mt-1.5 text-[12px] text-black">JPG, PNG, WebP, or GIF · up to 10 MB</p>
      </div>

      {previewSrc && (
        <div className="overflow-hidden rounded-lg border border-slate-200">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={previewSrc} alt="Preview" className="block w-full object-cover" style={{ aspectRatio: '16/9' }} />
        </div>
      )}

      {file && (
        <div>
          <label className="field-label">Title (added to Assets)</label>
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            className="field-input"
            placeholder="e.g. Week 1 banner"
            maxLength={300}
          />
        </div>
      )}

      {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-[13px] text-red-600">{error}</p>}

      <div className="flex justify-end">
        <button
          type="submit"
          disabled={!file || uploading}
          className="rounded-lg px-5 py-2.5 text-[14px] font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-50"
          style={{ background: '#38A09E' }}
        >
          {uploading ? 'Uploading…' : 'Upload + use this image'}
        </button>
      </div>
    </form>
  )
}


// ---------------------------------------------------------------------------
// Tab: Assets
// ---------------------------------------------------------------------------

function LibraryTab({
  assets,
  loading,
  onPick,
}: {
  assets: CreatorMediaAsset[]
  loading: boolean
  onPick: (asset: CreatorMediaAsset) => void
}) {
  const images = assets.filter((a) => a.media_type === 'image' && a.status === 'active')

  if (loading && images.length === 0) {
    return <p className="py-8 text-center text-[13px] text-black">Loading Assets…</p>
  }

  if (images.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-slate-200 p-6 text-center">
        <p className="text-[13px] text-black">No images in this collective&apos;s Assets yet.</p>
        <p className="mt-1 text-[12px] text-black">
          Switch to <strong>Upload new image</strong> to add one — it&apos;ll be saved here for reuse.
        </p>
        <Link
          href="/creator-studio/assets"
          className="mt-3 inline-block text-[13px] font-medium text-teal-600 hover:underline"
        >
          Open Assets →
        </Link>
      </div>
    )
  }

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
      {images.map((a) => (
        <button
          key={a.id}
          type="button"
          onClick={() => onPick(a)}
          className="group overflow-hidden rounded-lg border border-slate-200 bg-white text-left transition-all hover:border-teal-400 hover:shadow-sm"
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={bannerPreviewSrc(assetToUrl(a))}
            alt={a.title}
            className="block w-full object-cover"
            style={{ aspectRatio: '16/9' }}
          />
          <div className="p-2">
            <p className="truncate text-[12px] font-medium text-navy-900">{a.title}</p>
            <p className="truncate text-[11px] text-black">{a.original_filename}</p>
          </div>
        </button>
      ))}
    </div>
  )
}


// ---------------------------------------------------------------------------
// Tab: External URL
// ---------------------------------------------------------------------------

function ExternalUrlTab({ onPick }: { onPick: (url: string) => void }) {
  const [url, setUrl] = useState('')
  const [error, setError] = useState<string | null>(null)

  function validate(raw: string): string | null {
    const s = raw.trim()
    if (!s) return 'URL is required.'
    if (s.startsWith('//')) return 'Protocol-relative URLs are not allowed.'
    if (!s.toLowerCase().startsWith('https://')) return 'URL must use https://.'
    try { new URL(s) } catch { return 'Not a valid URL.' }
    return null
  }

  function handleApply() {
    const e = validate(url)
    if (e) { setError(e); return }
    onPick(url.trim())
  }

  return (
    <div className="space-y-4">
      <div>
        <label className="field-label">Image URL</label>
        <input
          type="url"
          value={url}
          onChange={(e) => { setUrl(e.target.value); setError(null) }}
          placeholder="https://example.com/banner.jpg"
          className="field-input"
        />
        <p className="mt-1.5 text-[12px] text-black">Only https:// URLs are accepted.</p>
        {error && <p className="mt-2 text-[12px] text-amber-600">⚠ {error}</p>}
      </div>

      <div className="flex justify-end">
        <button
          type="button"
          onClick={handleApply}
          className="rounded-lg px-5 py-2.5 text-[14px] font-semibold text-white transition-opacity hover:opacity-90"
          style={{ background: '#38A09E' }}
        >
          Use this URL
        </button>
      </div>
    </div>
  )
}
