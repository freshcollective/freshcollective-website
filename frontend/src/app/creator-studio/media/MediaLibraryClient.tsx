'use client'

import { useRef, useState } from 'react'
import { apiUrl } from '@/lib/api'
import type { CreatorMediaAsset, MediaAssetType } from '@/types/platform'

// TODO: Attach media assets to pathway steps via pathway_step_media join table.
// TODO: Use media assets in Resources via resource_media join table.
// TODO: Add replay videos to Gatherings via gathering_replay_media join table.
// TODO: Protect member-only downloads behind authenticated access checks before production.
// TODO: Move video hosting to Mux, Cloudflare Stream, or S3 before production scale.

interface Props {
  initialAssets: CreatorMediaAsset[]
  spaceSlug: string
  spaceName: string
}

const TYPE_FILTERS = ['all', 'image', 'video', 'audio', 'other'] as const
type TypeFilter = typeof TYPE_FILTERS[number]

const ACCEPTED_MIME =
  'image/jpeg,image/png,image/webp,' +
  'application/pdf,application/msword,' +
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document,' +
  'application/vnd.ms-excel,' +
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,' +
  'application/vnd.ms-powerpoint,' +
  'application/vnd.openxmlformats-officedocument.presentationml.presentation,' +
  'audio/mpeg,audio/wav,audio/x-m4a,audio/mp4,' +
  'video/mp4,video/quicktime,video/webm'

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString('en-AU', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  })
}

function typeLabel(t: MediaAssetType): string {
  return { image: 'Image', video: 'Video', audio: 'Audio', document: 'Document', other: 'File' }[t]
}

function TypeBadge({ type }: { type: MediaAssetType }) {
  const colors: Record<MediaAssetType, { bg: string; text: string }> = {
    image:    { bg: 'rgba(56,160,158,0.10)',  text: '#38A09E' },
    video:    { bg: 'rgba(124,58,237,0.10)',  text: '#7C3AED' },
    audio:    { bg: 'rgba(217,119,6,0.10)',   text: '#D97706' },
    document: { bg: 'rgba(7,24,36,0.08)',     text: '#334155' },
    other:    { bg: 'rgba(100,116,139,0.10)', text: '#64748B' },
  }
  const { bg, text } = colors[type]
  return (
    <span
      className="inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide"
      style={{ background: bg, color: text }}
    >
      {typeLabel(type)}
    </span>
  )
}

function FileIcon({ type }: { type: MediaAssetType }) {
  const strokeColor: Record<MediaAssetType, string> = {
    image:    '#38A09E',
    video:    '#7C3AED',
    audio:    '#D97706',
    document: '#334155',
    other:    '#64748B',
  }
  const stroke = strokeColor[type]

  if (type === 'image') {
    return (
      <svg width="20" height="20" fill="none" viewBox="0 0 24 24" stroke={stroke} strokeWidth="1.5" aria-hidden="true">
        <rect x="3" y="3" width="18" height="18" rx="2" />
        <circle cx="8.5" cy="8.5" r="1.5" />
        <path d="M21 15l-5-5L5 21" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    )
  }
  if (type === 'video') {
    return (
      <svg width="20" height="20" fill="none" viewBox="0 0 24 24" stroke={stroke} strokeWidth="1.5" aria-hidden="true">
        <rect x="2" y="6" width="15" height="12" rx="2" />
        <path d="M17 9l5-3v12l-5-3V9z" strokeLinejoin="round" />
      </svg>
    )
  }
  if (type === 'audio') {
    return (
      <svg width="20" height="20" fill="none" viewBox="0 0 24 24" stroke={stroke} strokeWidth="1.5" aria-hidden="true">
        <path d="M9 18V5l12-2v13" strokeLinecap="round" strokeLinejoin="round" />
        <circle cx="6" cy="18" r="3" />
        <circle cx="18" cy="16" r="3" />
      </svg>
    )
  }
  // document / other
  return (
    <svg width="20" height="20" fill="none" viewBox="0 0 24 24" stroke={stroke} strokeWidth="1.5" aria-hidden="true">
      <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" strokeLinejoin="round" />
      <polyline points="14 2 14 8 20 8" strokeLinejoin="round" />
      <line x1="8" y1="13" x2="16" y2="13" strokeLinecap="round" />
      <line x1="8" y1="17" x2="12" y2="17" strokeLinecap="round" />
    </svg>
  )
}

// ---------------------------------------------------------------------------
// Upload Modal
// ---------------------------------------------------------------------------

interface UploadModalProps {
  spaceSlug: string
  onClose: () => void
  onUploaded: (asset: CreatorMediaAsset) => void
}

function UploadModal({ spaceSlug, onClose, onUploaded }: UploadModalProps) {
  const fileRef = useRef<HTMLInputElement>(null)
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0] ?? null
    setSelectedFile(f)
    setError(null)
    if (f && !title.trim()) {
      // Auto-fill title from filename (strip extension)
      setTitle(f.name.replace(/\.[^/.]+$/, ''))
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!selectedFile) {
      setError('Please select a file.')
      return
    }
    setUploading(true)
    setError(null)
    try {
      const fd = new FormData()
      fd.append('file', selectedFile)
      fd.append('title', title.trim())
      fd.append('description', description.trim())

      const res = await fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/media`), {
        method: 'POST',
        body: fd,
        credentials: 'include',
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body?.detail ?? `Upload failed (${res.status})`)
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
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div
        className="absolute inset-0 bg-black/40"
        onClick={onClose}
        aria-hidden="true"
      />
      <div
        className="relative w-full max-w-md rounded-2xl bg-white shadow-2xl"
        style={{ border: '1px solid rgba(0,0,0,0.08)' }}
      >
        <div className="px-6 py-5" style={{ borderBottom: '1px solid rgba(0,0,0,0.07)' }}>
          <h2 className="text-[16px] font-semibold text-navy-900">Upload asset</h2>
        </div>

        <form onSubmit={handleSubmit} className="px-6 py-5 space-y-4">
          {/* File picker */}
          <div>
            <label className="mb-1.5 block text-[13px] font-medium text-navy-900">
              File <span className="text-red-500">*</span>
            </label>
            <input
              ref={fileRef}
              type="file"
              accept={ACCEPTED_MIME}
              onChange={handleFileChange}
              className="block w-full text-[13px] text-slate-500 file:mr-3 file:rounded-lg file:border-0 file:px-3 file:py-1.5 file:text-[12px] file:font-semibold file:text-white transition-opacity"
              style={{ '--file-bg': '#38A09E' } as React.CSSProperties}
            />
            {selectedFile && (
              <p className="mt-1 text-[11px] text-slate-400">
                {selectedFile.name} · {formatBytes(selectedFile.size)}
              </p>
            )}
            <p className="mt-1 text-[11px] text-slate-400">
              Images 10 MB · Documents 25 MB · Audio 50 MB · Video 250 MB
            </p>
          </div>

          {/* Title */}
          <div>
            <label className="mb-1.5 block text-[13px] font-medium text-navy-900">
              Title
            </label>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="e.g. Week 1 Workbook"
              maxLength={300}
              className="w-full rounded-xl border border-slate-200 px-3.5 py-2.5 text-[14px] text-navy-900 outline-none transition-colors focus:border-teal-400 focus:ring-1 focus:ring-teal-400/30"
            />
          </div>

          {/* Description */}
          <div>
            <label className="mb-1.5 block text-[13px] font-medium text-navy-900">
              Description <span className="text-[11px] font-normal text-slate-400">(optional)</span>
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Brief note about this file…"
              rows={2}
              className="w-full rounded-xl border border-slate-200 px-3.5 py-2.5 text-[14px] text-navy-900 outline-none transition-colors focus:border-teal-400 focus:ring-1 focus:ring-teal-400/30 resize-none"
            />
          </div>

          {error && (
            <p className="rounded-lg bg-red-50 px-3 py-2 text-[13px] text-red-600">{error}</p>
          )}

          <div className="flex items-center justify-end gap-3 pt-1">
            <button
              type="button"
              onClick={onClose}
              disabled={uploading}
              className="rounded-xl px-4 py-2.5 text-[13px] font-medium text-slate-500 transition-colors hover:text-navy-900"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={uploading || !selectedFile}
              className="inline-flex items-center gap-2 rounded-xl px-5 py-2.5 text-[13px] font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-50"
              style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
            >
              {uploading ? 'Uploading…' : 'Upload'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Asset card
// ---------------------------------------------------------------------------

interface AssetCardProps {
  asset: CreatorMediaAsset
  spaceSlug: string
  onArchive: (id: string) => void
}

function AssetCard({ asset, spaceSlug, onArchive }: AssetCardProps) {
  const [archiving, setArchiving] = useState(false)

  async function handleArchive() {
    if (!confirm(`Archive "${asset.title}"? It will be hidden from the library.`)) return
    setArchiving(true)
    try {
      const res = await fetch(
        apiUrl(`/api/creator/spaces/${spaceSlug}/media/${asset.id}/archive`),
        { method: 'PATCH', credentials: 'include' },
      )
      if (res.ok) onArchive(asset.id)
    } finally {
      setArchiving(false)
    }
  }

  const apiBase = typeof window !== 'undefined'
    ? (process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000')
    : 'http://localhost:8000'
  const viewUrl = asset.file_url.startsWith('/')
    ? `${apiBase}${asset.file_url}`
    : asset.file_url

  return (
    <div
      className="flex items-start gap-4 rounded-2xl bg-white px-5 py-4"
      style={{ border: '1px solid rgba(0,0,0,0.07)', boxShadow: '0 1px 3px rgba(0,0,0,0.04)' }}
    >
      <div
        className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl"
        style={{ background: 'rgba(0,0,0,0.04)' }}
      >
        <FileIcon type={asset.media_type} />
      </div>

      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-[14px] font-medium text-navy-900 leading-snug">{asset.title}</p>
          <TypeBadge type={asset.media_type} />
        </div>
        <p className="mt-0.5 truncate text-[12px] text-slate-400">{asset.original_filename}</p>
        {asset.description && (
          <p className="mt-1 text-[13px] text-slate-500 leading-snug">{asset.description}</p>
        )}
        <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[11px] text-slate-400">
          <span>{formatBytes(asset.file_size_bytes)}</span>
          <span>·</span>
          <span>{formatDate(asset.created_at)}</span>
        </div>
      </div>

      <div className="flex shrink-0 items-center gap-2">
        <a
          href={viewUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="rounded-lg px-3 py-1.5 text-[12px] font-medium text-teal-600 transition-colors hover:bg-teal-50 hover:text-teal-700"
        >
          Open
        </a>
        <button
          type="button"
          onClick={handleArchive}
          disabled={archiving}
          className="rounded-lg px-3 py-1.5 text-[12px] font-medium text-slate-400 transition-colors hover:bg-slate-50 hover:text-slate-600 disabled:opacity-40"
        >
          {archiving ? '…' : 'Archive'}
        </button>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main client component
// ---------------------------------------------------------------------------

export default function MediaLibraryClient({ initialAssets, spaceSlug, spaceName }: Props) {
  const [assets, setAssets] = useState<CreatorMediaAsset[]>(initialAssets)
  const [showUpload, setShowUpload] = useState(false)
  const [search, setSearch] = useState('')
  const [typeFilter, setTypeFilter] = useState<TypeFilter>('all')

  function handleUploaded(asset: CreatorMediaAsset) {
    setAssets((prev) => [asset, ...prev])
    setShowUpload(false)
  }

  function handleArchive(id: string) {
    setAssets((prev) => prev.filter((a) => a.id !== id))
  }

  const filtered = assets.filter((a) => {
    if (typeFilter !== 'all' && a.media_type !== typeFilter) return false
    if (search) {
      const q = search.toLowerCase()
      return (
        a.title.toLowerCase().includes(q) ||
        a.original_filename.toLowerCase().includes(q)
      )
    }
    return true
  })

  return (
    <div className="w-full max-w-[1180px] px-8 py-8 md:px-10 md:py-10">

      {/* Header */}
      <div className="mb-8 flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.16em]" style={{ color: '#38A09E' }}>
            {spaceName}
          </p>
          <h1 className="text-2xl text-navy-900 md:text-3xl">Brand Library</h1>
          <p className="mt-1.5 text-[14px] leading-relaxed" style={{ color: '#334155' }}>
            Upload and manage the visual assets used across this collective.
          </p>
          <p className="mt-1 text-[12.5px]" style={{ color: '#64748B' }}>
            Use this for banners, logos, icons, thumbnails, and other brand images.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setShowUpload(true)}
          className="inline-flex shrink-0 items-center gap-2 rounded-xl px-5 py-2.5 text-[13px] font-semibold text-white transition-opacity hover:opacity-90"
          style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
        >
          <span aria-hidden="true">+</span> Upload asset
        </button>
      </div>

      {/* Resource separation note */}
      <div
        className="mb-6 flex items-start gap-3 rounded-2xl border px-5 py-4"
        style={{ borderColor: 'rgba(56,160,158,0.28)', background: 'rgba(56,160,158,0.05)' }}
      >
        <span className="mt-0.5 text-[14px]" style={{ color: '#38A09E' }}>◫</span>
        <p className="text-[13px] leading-relaxed" style={{ color: '#334155' }}>
          <span className="font-semibold">Looking for member resources?</span>{' '}
          Add PDFs, links, guides, replays, and pathway materials in{' '}
          <a href="/creator-studio/resources" className="font-medium underline underline-offset-2" style={{ color: '#38A09E' }}>
            Resources
          </a>.
        </p>
      </div>

      {/* Search + filter */}
      <div className="mb-5 flex flex-wrap items-center gap-3">
        <input
          type="search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search by title or filename…"
          className="w-full max-w-xs rounded-xl border border-slate-200 px-3.5 py-2 text-[13px] text-navy-900 outline-none transition-colors focus:border-teal-400 focus:ring-1 focus:ring-teal-400/30"
        />
        <div className="flex flex-wrap items-center gap-1.5">
          {TYPE_FILTERS.map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => setTypeFilter(t)}
              className="rounded-lg px-3 py-1.5 text-[12px] font-medium capitalize transition-colors"
              style={
                typeFilter === t
                  ? { background: '#38A09E', color: '#FFFFFF' }
                  : { background: 'rgba(0,0,0,0.05)', color: '#64748B' }
              }
            >
              {t === 'all' ? 'All' : typeLabel(t as MediaAssetType)}
            </button>
          ))}
        </div>
      </div>

      {/* Asset list */}
      {filtered.length > 0 ? (
        <div className="space-y-3">
          {filtered.map((asset) => (
            <AssetCard
              key={asset.id}
              asset={asset}
              spaceSlug={spaceSlug}
              onArchive={handleArchive}
            />
          ))}
        </div>
      ) : assets.length === 0 ? (
        <div
          className="rounded-2xl bg-white px-8 py-12 text-center"
          style={{ border: '1px solid rgba(0,0,0,0.07)' }}
        >
          <div
            className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-2xl"
            style={{ background: 'rgba(56,160,158,0.10)' }}
          >
            <svg width="22" height="22" fill="none" viewBox="0 0 24 24" stroke="#38A09E" strokeWidth="1.5" aria-hidden="true">
              <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M17 8l-5-5-5 5M12 3v12" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </div>
          <p className="mb-1 text-[16px] font-semibold text-navy-900">No brand assets yet</p>
          <p className="mb-6 text-[14px] leading-relaxed text-slate-500">
            Upload your first asset — banners, logos, icons, or thumbnails — to use across this collective.
          </p>
          <button
            type="button"
            onClick={() => setShowUpload(true)}
            className="inline-flex items-center gap-2 rounded-xl px-5 py-2.5 text-[13px] font-semibold text-white transition-opacity hover:opacity-90"
            style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
          >
            Upload first asset
          </button>
        </div>
      ) : (
        <div className="rounded-2xl bg-white px-6 py-8 text-center" style={{ border: '1px solid rgba(0,0,0,0.07)' }}>
          <p className="text-[14px] text-slate-400">No files match your search or filter.</p>
          <button
            type="button"
            onClick={() => { setSearch(''); setTypeFilter('all') }}
            className="mt-3 text-[13px] font-medium text-teal-600 hover:underline"
          >
            Clear filters
          </button>
        </div>
      )}

      {/* Upload modal */}
      {showUpload && (
        <UploadModal
          spaceSlug={spaceSlug}
          onClose={() => setShowUpload(false)}
          onUploaded={handleUploaded}
        />
      )}
    </div>
  )
}
