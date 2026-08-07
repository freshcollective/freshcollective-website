'use client'

import { useMemo, useState } from 'react'
import { apiUrl, resolveMediaUrl } from '@/lib/api'
import OverflowMenu from '@/components/ui/OverflowMenu'
import {
  Badge, type BadgeTone,
  Button,
  Card,
  EmptyState,
  FormField,
  Input,
  Modal,
  SearchInput,
  Text,
  TextArea,
  cn,
  useConfirm,
  useToast,
} from '@/components/platform'
import { PlusIcon } from '@/components/creator/PrimaryActionLink'
import type {
  CreatorMediaAsset,
  MediaAssetType,
  MediaUsageReference,
  MediaUsageResponse,
} from '@/types/platform'

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
    day: 'numeric', month: 'short', year: 'numeric',
  })
}

function typeLabel(t: MediaAssetType): string {
  return { image: 'Image', video: 'Video', audio: 'Audio', document: 'Document', other: 'File' }[t]
}

// Map asset types onto Badge tones. Aligns the Asset Library palette
// with the platform-wide Fresh Collective type colours.
const TYPE_TO_BADGE: Record<MediaAssetType, BadgeTone> = {
  image:    'link',   // teal
  video:    'video',  // coral
  audio:    'audio',  // purple
  document: 'file',   // navy
  other:    'other',  // slate
}

// ---------------------------------------------------------------------------
// File-type categorisation for the preview area.
//
// The stored `media_type` is a coarse bucket ('image' | 'video' | 'audio' |
// 'document' | 'other'). For a richer preview we sniff `mime_type` and
// `extension` to differentiate PDF, spreadsheet, archive, and generic
// document. Nothing about storage or upload behaviour changes.
// ---------------------------------------------------------------------------

type FileCategory = 'image' | 'video' | 'audio' | 'pdf' | 'spreadsheet' | 'archive' | 'document' | 'generic'

const SPREADSHEET_MIME = new Set([
  'application/vnd.ms-excel',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  'application/vnd.oasis.opendocument.spreadsheet',
  'text/csv',
])
const ARCHIVE_MIME = new Set([
  'application/zip',
  'application/x-zip-compressed',
  'application/x-tar',
  'application/gzip',
  'application/x-rar-compressed',
  'application/x-7z-compressed',
])
const SPREADSHEET_EXT = new Set(['xls', 'xlsx', 'csv', 'ods', 'numbers'])
const ARCHIVE_EXT     = new Set(['zip', 'tar', 'gz', 'tgz', 'rar', '7z'])

function categorize(asset: CreatorMediaAsset): FileCategory {
  const mt = asset.media_type
  const mime = asset.mime_type?.toLowerCase() ?? ''
  const ext  = (asset.extension ?? '').replace(/^\./, '').toLowerCase()

  if (mt === 'image') return 'image'
  if (mt === 'video') return 'video'
  if (mt === 'audio') return 'audio'
  if (mime === 'application/pdf' || ext === 'pdf') return 'pdf'
  if (SPREADSHEET_MIME.has(mime) || SPREADSHEET_EXT.has(ext)) return 'spreadsheet'
  if (ARCHIVE_MIME.has(mime) || ARCHIVE_EXT.has(ext)) return 'archive'
  if (mt === 'document') return 'document'
  return 'generic'
}

// Category → preview background + icon colour. Non-image cards use a
// very subtle diagonal gradient in the type family, giving each panel a
// touch of depth without shouting. Kept low-saturation so the icon —
// not the colour — remains the visual identity of the file.
const CATEGORY_TINT: Record<FileCategory, { bg: string; fg: string }> = {
  image:       { bg: 'linear-gradient(135deg, rgba(56,160,158,0.12)  0%, rgba(56,160,158,0.04)  100%)', fg: '#0f766e' }, // pale teal
  pdf:         { bg: 'linear-gradient(135deg, rgba(214,96,87,0.12)   0%, rgba(214,96,87,0.03)   100%)', fg: '#a63c30' }, // blush → warm white
  video:       { bg: 'linear-gradient(135deg, rgba(56,116,180,0.12)  0%, rgba(56,116,180,0.04)  100%)', fg: '#1e40af' }, // pale blue
  audio:       { bg: 'linear-gradient(135deg, rgba(139,92,246,0.12)  0%, rgba(139,92,246,0.04)  100%)', fg: '#6d28d9' }, // pale lavender
  document:    { bg: 'linear-gradient(135deg, rgba(30,41,59,0.07)    0%, rgba(30,41,59,0.02)    100%)', fg: '#334155' }, // pale slate
  spreadsheet: { bg: 'linear-gradient(135deg, rgba(34,197,94,0.12)   0%, rgba(34,197,94,0.04)   100%)', fg: '#15803d' }, // pale green
  archive:     { bg: 'linear-gradient(135deg, rgba(212,176,72,0.16)  0%, rgba(212,176,72,0.05)  100%)', fg: '#7A5A00' }, // pale gold
  generic:     { bg: 'linear-gradient(135deg, rgba(100,116,139,0.12) 0%, rgba(100,116,139,0.04) 100%)', fg: '#475569' }, // pale grey
}

function categoryLabel(c: FileCategory): string {
  return {
    image: 'Image', video: 'Video', audio: 'Audio',
    pdf: 'PDF', spreadsheet: 'Spreadsheet', archive: 'Archive',
    document: 'Document', generic: 'File',
  }[c]
}

/**
 * File-type icon. `type` is either the coarse `MediaAssetType` (kept for
 * back-compat) or the richer `FileCategory` computed by ``categorize``.
 * Icons are heroicons-outline-style inline SVGs so we don't add a
 * dependency for a handful of glyphs.
 */
function FileIcon({ type, size = 20 }: { type: MediaAssetType | FileCategory; size?: number }) {
  const s = size
  const props = {
    width: s, height: s, viewBox: '0 0 24 24', fill: 'none',
    stroke: 'currentColor', strokeWidth: 1.5,
    strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const,
  }
  if (type === 'image') {
    return (
      <svg {...props} aria-hidden="true">
        <rect x="3" y="3" width="18" height="18" rx="2" />
        <circle cx="8.5" cy="8.5" r="1.5" />
        <path d="M21 15l-5-5L5 21" />
      </svg>
    )
  }
  if (type === 'video') {
    // Play triangle inside a rounded rectangle — reads as "video" clearly
    // whether the tile is small or large.
    return (
      <svg {...props} aria-hidden="true">
        <rect x="3" y="4" width="18" height="16" rx="2" />
        <path d="M10 9l6 3-6 3V9z" fill="currentColor" stroke="none" />
      </svg>
    )
  }
  if (type === 'audio') {
    return (
      <svg {...props} aria-hidden="true">
        <path d="M9 18V5l12-2v13" />
        <circle cx="6" cy="18" r="3" />
        <circle cx="18" cy="16" r="3" />
      </svg>
    )
  }
  if (type === 'pdf') {
    return (
      <svg {...props} aria-hidden="true">
        <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
        <polyline points="14 2 14 8 20 8" />
        <text x="12" y="18" textAnchor="middle" fontSize="6" fontFamily="sans-serif" fontWeight="700" fill="currentColor" stroke="none">PDF</text>
      </svg>
    )
  }
  if (type === 'spreadsheet') {
    return (
      <svg {...props} aria-hidden="true">
        <rect x="3" y="4" width="18" height="16" rx="2" />
        <line x1="3" y1="10" x2="21" y2="10" />
        <line x1="3" y1="16" x2="21" y2="16" />
        <line x1="9" y1="4" x2="9" y2="20" />
        <line x1="15" y1="4" x2="15" y2="20" />
      </svg>
    )
  }
  if (type === 'archive') {
    return (
      <svg {...props} aria-hidden="true">
        <rect x="3" y="4" width="18" height="16" rx="2" />
        <line x1="12" y1="4" x2="12" y2="8" />
        <line x1="12" y1="10" x2="12" y2="12" />
        <line x1="12" y1="14" x2="12" y2="16" />
      </svg>
    )
  }
  // document / generic (default)
  return (
    <svg {...props} aria-hidden="true">
      <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
      <polyline points="14 2 14 8 20 8" />
      <line x1="8" y1="13" x2="16" y2="13" />
      <line x1="8" y1="17" x2="12" y2="17" />
    </svg>
  )
}

// ---------------------------------------------------------------------------
// Preview — the top of every asset card. 16:9 area with rounded top
// corners. Renders a real image for image assets (with a graceful fallback
// when it fails to load) and a large centred file-type glyph for everything
// else. Tinted by category so files are recognisable at a glance without
// shouting for attention.
// ---------------------------------------------------------------------------

function AssetPreview({
  asset, category, viewUrl,
}: {
  asset: CreatorMediaAsset
  category: FileCategory
  viewUrl: string
}) {
  const [imageFailed, setImageFailed] = useState(false)
  const tint = CATEGORY_TINT[category]
  const isImage = category === 'image' && !imageFailed

  return (
    <div
      className="relative w-full overflow-hidden rounded-t-[var(--fc-radius-lg)]"
      // Aspect ratio 16:6 keeps the preview compact. At typical card
      // widths this lands around 125–140px on desktop, 115–130px on
      // tablet, and 160–180px on mobile — visible enough to recognise
      // the file without turning the library into a gallery.
      style={{ aspectRatio: '16 / 6', background: tint.bg }}
    >
      {isImage ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={viewUrl}
          alt={asset.alt_text?.trim() || `Preview of ${asset.title}`}
          className="h-full w-full object-cover"
          loading="lazy"
          onError={() => setImageFailed(true)}
        />
      ) : (
        <div
          className="flex h-full w-full items-center justify-center"
          style={{ color: tint.fg }}
        >
          {/* Large centred glyph so the file type reads as the panel's
              identity rather than a small symbol in empty space. Same
              size for a failed-image fallback so the panel doesn't
              collapse in on itself. */}
          <FileIcon type={category} size={64} />
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Upload Modal — Modal
// ---------------------------------------------------------------------------

interface UploadModalProps {
  open: boolean
  spaceSlug: string
  onClose: () => void
  onUploaded: (asset: CreatorMediaAsset) => void
}

function UploadModal({ open, spaceSlug, onClose, onUploaded }: UploadModalProps) {
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const toast = useToast()

  function reset() {
    setSelectedFile(null); setTitle(''); setDescription(''); setError(null)
  }

  function handleClose() {
    if (uploading) return
    reset()
    onClose()
  }

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0] ?? null
    setSelectedFile(f)
    setError(null)
    if (f && !title.trim()) {
      setTitle(f.name.replace(/\.[^/.]+$/, ''))
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!selectedFile) { setError('Please select a file.'); return }
    setUploading(true); setError(null)
    try {
      const fd = new FormData()
      fd.append('file', selectedFile)
      fd.append('title', title.trim())
      fd.append('description', description.trim())

      const res = await fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/media`), {
        method: 'POST', body: fd, credentials: 'include',
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body?.detail ?? `Upload failed (${res.status})`)
      }
      const asset: CreatorMediaAsset = await res.json()
      onUploaded(asset)
      toast.show('Asset uploaded', { tone: 'success' })
      reset()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Upload failed.')
    } finally {
      setUploading(false)
    }
  }

  return (
    <Modal
      open={open}
      onClose={handleClose}
      title="Upload asset"
      size="md"
      actions={
        <>
          <Button variant="tertiary" onClick={handleClose} disabled={uploading}>
            Cancel
          </Button>
          <Button
            variant="primary"
            type="submit"
            form="brand-upload-form"
            disabled={!selectedFile}
            loading={uploading}
          >
            Upload
          </Button>
        </>
      }
    >
      <form id="brand-upload-form" onSubmit={handleSubmit} className="space-y-4">
        <div className="flex flex-col gap-1.5">
          <label
            htmlFor="brand-upload-file"
            className="text-[12px] font-[var(--fc-fw-semibold)] uppercase tracking-[var(--fc-tracking-eyebrow-tight)] text-[color:var(--fc-ink-primary)]"
          >
            File <span aria-hidden="true" className="text-[color:var(--fc-accent-500)]">*</span>
          </label>
          <input
            id="brand-upload-file"
            type="file"
            accept={ACCEPTED_MIME}
            onChange={handleFileChange}
            className="block w-full text-[13px] text-[color:var(--fc-ink-primary)] file:mr-3 file:rounded-[var(--fc-radius-md)] file:border-0 file:bg-slate-100 file:px-3 file:py-1.5 file:text-[12px] file:font-[var(--fc-fw-semibold)] file:text-[color:var(--fc-ink-primary)]"
          />
          {selectedFile && (
            <Text as="p" variant="meta">
              {selectedFile.name} · {formatBytes(selectedFile.size)}
            </Text>
          )}
          <Text as="p" variant="meta" muted>
            Images 10 MB · Documents 25 MB · Audio 50 MB · Video 250 MB
          </Text>
        </div>

        <FormField label="Title">
          <Input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="e.g. Week 1 Workbook"
            maxLength={300}
          />
        </FormField>

        <FormField label="Description" helper="Optional short note about this file.">
          <TextArea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Brief note about this file…"
            rows={2}
          />
        </FormField>

        {error && (
          <div
            role="alert"
            className="rounded-[var(--fc-radius-md)] px-3 py-2 text-[13px] text-[color:var(--fc-status-error-text)]"
            style={{ background: 'var(--fc-status-error-bg)' }}
          >
            {error}
          </div>
        )}
      </form>
    </Modal>
  )
}

// ---------------------------------------------------------------------------
// Edit Modal — metadata only. NEVER touches the underlying file.
// ---------------------------------------------------------------------------

interface EditModalProps {
  open: boolean
  spaceSlug: string
  asset: CreatorMediaAsset | null
  onClose: () => void
  onSaved: (asset: CreatorMediaAsset) => void
}

function EditModal({ open, spaceSlug, asset, onClose, onSaved }: EditModalProps) {
  return (
    <Modal
      open={open && asset !== null}
      onClose={onClose}
      title="Edit asset"
      size="md"
      // Actions are rendered inside EditModalContent via portal-style
      // (they need access to the form state); here we mount only the body.
    >
      {asset && (
        <EditModalContent
          key={asset.id}
          asset={asset}
          spaceSlug={spaceSlug}
          onClose={onClose}
          onSaved={onSaved}
        />
      )}
    </Modal>
  )
}

/**
 * EditModalContent — form body + inline action row. Mounted with a key so
 * React remounts the component (and resets state) whenever the active asset
 * changes.
 */
function EditModalContent({
  asset, spaceSlug, onClose, onSaved,
}: {
  asset: CreatorMediaAsset
  spaceSlug: string
  onClose: () => void
  onSaved: (asset: CreatorMediaAsset) => void
}) {
  const toast = useToast()
  const [title, setTitle] = useState(asset.title)
  const [description, setDescription] = useState(asset.description ?? '')
  const [altText, setAltText] = useState(asset.alt_text ?? '')
  const [tags, setTags] = useState(asset.tags ?? '')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function handleClose() {
    if (saving) return
    onClose()
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!title.trim()) { setError('Title is required.'); return }
    setSaving(true); setError(null)
    try {
      const res = await fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/media/${asset.id}`), {
        method: 'PATCH',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: title.trim(),
          description: description.trim(),
          alt_text: altText.trim(),
          tags: tags.trim(),
        }),
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body?.detail ?? `Save failed (${res.status})`)
      }
      const updated: CreatorMediaAsset = await res.json()
      onSaved(updated)
      toast.show('Changes saved', { tone: 'success' })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Save failed.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      <Text as="p" variant="meta" className="mb-4">
        Updates apply everywhere this asset is used. The file itself isn&apos;t modified.
      </Text>

      <form onSubmit={handleSubmit} className="space-y-4">
        <FormField label="Title" required>
          <Input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            maxLength={300}
          />
        </FormField>

        <FormField label="Description" helper="Optional short note about this file.">
          <TextArea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={2}
          />
        </FormField>

        <FormField label="Alt text" helper="Optional — used when this asset is rendered as an image, for accessibility.">
          <Input
            value={altText}
            onChange={(e) => setAltText(e.target.value)}
            maxLength={500}
            placeholder="e.g. Sunlit room with open journal and tea"
          />
        </FormField>

        <FormField label="Tags" helper="Comma-separated. Used to find this asset later.">
          <Input
            value={tags}
            onChange={(e) => setTags(e.target.value)}
            maxLength={500}
            placeholder="e.g. cover, week 1, banner"
          />
        </FormField>

        {error && (
          <div
            role="alert"
            className="rounded-[var(--fc-radius-md)] px-3 py-2 text-[13px] text-[color:var(--fc-status-error-text)]"
            style={{ background: 'var(--fc-status-error-bg)' }}
          >
            {error}
          </div>
        )}

        <div className="flex flex-wrap items-center justify-end gap-2 pt-2">
          <Button
            type="button"
            variant="tertiary"
            onClick={handleClose}
            disabled={saving}
          >
            Cancel
          </Button>
          <Button
            type="submit"
            variant="primary"
            loading={saving}
          >
            Save changes
          </Button>
        </div>
      </form>
    </>
  )
}

// ---------------------------------------------------------------------------
// Asset card — Card
// ---------------------------------------------------------------------------

interface AssetCardProps {
  asset: CreatorMediaAsset
  spaceSlug: string
  onArchive: (id: string) => void
  onEdit: (asset: CreatorMediaAsset) => void
}

function AssetCard({ asset, spaceSlug, onArchive, onEdit }: AssetCardProps) {
  const toast = useToast()
  const confirm = useConfirm()
  const [archiving, setArchiving] = useState(false)
  const [usageOpen, setUsageOpen] = useState(false)
  const [usageLoading, setUsageLoading] = useState(false)
  const [usage, setUsage] = useState<MediaUsageReference[] | null>(null)

  async function handleArchive() {
    const yes = await confirm({
      title: `Archive “${asset.title}”?`,
      body: 'It will be hidden from the library. This does not delete the file.',
      confirmLabel: 'Archive',
      tone: 'danger',
    })
    if (!yes) return

    setArchiving(true)
    try {
      const res = await fetch(
        apiUrl(`/api/creator/spaces/${spaceSlug}/media/${asset.id}/archive`),
        { method: 'PATCH', credentials: 'include' },
      )
      if (res.ok) {
        onArchive(asset.id)
        toast.show(`${asset.title} archived`, { tone: 'success' })
      } else {
        toast.show('Could not archive asset', { tone: 'error' })
      }
    } catch {
      toast.show('Could not archive asset', { tone: 'error' })
    } finally {
      setArchiving(false)
    }
  }

  async function loadUsage() {
    if (usage !== null) { setUsageOpen(o => !o); return }
    setUsageLoading(true)
    try {
      const res = await fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/media/${asset.id}/usage`), {
        credentials: 'include',
      })
      if (res.ok) {
        const body: MediaUsageResponse = await res.json()
        setUsage(body.references)
      } else {
        setUsage([])
      }
    } catch {
      setUsage([])
    } finally {
      setUsageLoading(false)
      setUsageOpen(true)
    }
  }

  const grouped = useMemo(() => {
    if (!usage) return null
    const buckets = new Map<string, { pathwayTitle: string; refs: MediaUsageReference[] }>()
    for (const ref of usage) {
      const key = ref.pathway_id ?? '__none__'
      const title = ref.pathway_title ?? '—'
      if (!buckets.has(key)) buckets.set(key, { pathwayTitle: title, refs: [] })
      buckets.get(key)!.refs.push(ref)
    }
    return Array.from(buckets.values())
  }, [usage])

  // Resolve the file URL for image previews + Open action. Uses the
  // shared resolveMediaUrl helper so a relative "/media/..." path is
  // rewritten to the backend origin.
  const viewUrl = resolveMediaUrl(asset.file_url) ?? asset.file_url

  const tagList = (asset.tags ?? '').split(',').map(t => t.trim()).filter(Boolean)

  const category = categorize(asset)
  const badgeTone = TYPE_TO_BADGE[asset.media_type]

  return (
    <Card
      as="article"
      padding="none"
      className={cn('flex min-w-0 flex-col overflow-hidden', archiving && 'opacity-60')}
    >
      {/* ── Preview area (top third) — image or file-type icon ── */}
      <div className="relative">
        <AssetPreview asset={asset} category={category} viewUrl={viewUrl} />

        {/* Overflow menu floats over the preview's top-right corner so
            the body copy stays uncluttered. Uses a white pill so
            actions are legible over any preview background. */}
        <div
          className="absolute right-2 top-2 rounded-full"
          style={{ background: 'rgba(255,255,255,0.94)', backdropFilter: 'blur(6px)' }}
        >
          <OverflowMenu
            ariaLabel={`Actions for ${asset.title}`}
            items={[
              {
                label: 'Open',
                onClick: () => window.open(viewUrl, '_blank', 'noopener,noreferrer'),
              },
              { label: 'Edit', onClick: () => onEdit(asset) },
              {
                label: archiving ? 'Archiving…' : 'Archive',
                onClick: handleArchive,
                tone: 'danger',
                dividerAbove: true,
                disabled: archiving,
              },
            ]}
          />
        </div>
      </div>

      {/* ── Body ── tight spacing so the card stays compact even with
           optional description / alt / tags present. */}
      <div className="flex min-w-0 flex-1 flex-col px-3.5 pt-2.5 pb-3">
        <h4
          className="truncate text-[14.5px] font-[var(--fc-fw-semibold)] leading-tight text-[color:var(--fc-ink-heading)]"
          title={asset.title}
        >
          {asset.title}
        </h4>
        <div className="mt-1 flex flex-wrap items-center gap-1.5">
          <Badge tone={badgeTone}>{categoryLabel(category)}</Badge>
          <Text as="span" variant="meta">
            {formatBytes(asset.file_size_bytes)}
          </Text>
        </div>

        {asset.description && (
          <p className="mt-2 line-clamp-2 text-[12.5px] leading-snug text-[color:var(--fc-ink-primary)]">
            {asset.description}
          </p>
        )}

        {asset.alt_text && (
          <p
            className="mt-1.5 line-clamp-1 text-[11.5px] italic text-[color:var(--fc-ink-primary)]"
            title={asset.alt_text}
          >
            Alt: {asset.alt_text}
          </p>
        )}

        {tagList.length > 0 && (
          <div className="mt-1.5 flex flex-wrap gap-1">
            {tagList.map(t => (
              <Badge key={t} tone="neutral">{t}</Badge>
            ))}
          </div>
        )}

        <p
          className="mt-1.5 truncate text-[11px] text-[color:var(--fc-ink-secondary,rgba(12,24,38,0.55))]"
          title={asset.original_filename}
        >
          {asset.original_filename}
        </p>

        <div className="flex-1" />

        <div
          className="mt-2 flex flex-wrap items-center justify-between gap-2 border-t pt-2"
          style={{ borderColor: 'var(--fc-border-hairline)' }}
        >
          <Text as="span" variant="meta">{formatDate(asset.created_at)}</Text>
          <button
            type="button"
            onClick={loadUsage}
            disabled={usageLoading}
            className="text-[11.5px] font-[var(--fc-fw-semibold)] text-[color:var(--fc-ink-primary)] underline-offset-2 transition-colors hover:text-[color:var(--fc-accent-700)] hover:underline"
          >
            {usageLoading
              ? 'Loading…'
              : asset.usage_count === 0
              ? 'Used in 0 places'
              : usageOpen
              ? `Used in ${asset.usage_count} place${asset.usage_count === 1 ? '' : 's'} ▴`
              : `Used in ${asset.usage_count} place${asset.usage_count === 1 ? '' : 's'} ▾`}
          </button>
        </div>

        {usageOpen && usage !== null && (
          <div
            className="mt-2 rounded-[var(--fc-radius-md)] border px-3 py-2 text-[12px]"
            style={{
              borderColor: 'var(--fc-border-hairline)',
              background: 'rgba(15,30,55,0.02)',
            }}
          >
            {usage.length === 0 ? (
              <Text as="p" variant="meta">Not referenced from any pathway yet.</Text>
            ) : (
              <ul className="space-y-1.5">
                {grouped!.map((g) => (
                  <li key={g.pathwayTitle}>
                    <Text as="p" variant="body-strong" className="text-[12px]">
                      {g.pathwayTitle}
                    </Text>
                    <ul className="ml-3 mt-0.5 space-y-0.5">
                      {g.refs.map((ref, i) => (
                        <li key={i} className="text-[12px] text-[color:var(--fc-ink-primary)]">
                          • {ref.label ?? ref.kind}
                        </li>
                      ))}
                    </ul>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Main client component
// ---------------------------------------------------------------------------

export default function AssetLibrarySection({ initialAssets, spaceSlug, spaceName: _spaceName }: Props) {
  const [assets, setAssets] = useState<CreatorMediaAsset[]>(initialAssets)
  const [showUpload, setShowUpload] = useState(false)
  const [editingAsset, setEditingAsset] = useState<CreatorMediaAsset | null>(null)
  const [search, setSearch] = useState('')
  const [typeFilter, setTypeFilter] = useState<TypeFilter>('all')

  function handleUploaded(asset: CreatorMediaAsset) {
    setAssets((prev) => [asset, ...prev])
    setShowUpload(false)
  }

  function handleArchive(id: string) {
    setAssets((prev) => prev.filter((a) => a.id !== id))
  }

  function handleUpdated(updated: CreatorMediaAsset) {
    setAssets((prev) => prev.map((a) => a.id === updated.id ? updated : a))
    setEditingAsset(null)
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
    <section className="w-full">

      {/* Section header — the outer Assets page owns the Creator
          Studio eyebrow + "Assets" H1, so this section renders just an
          H2 and a short line of supporting copy. */}
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="font-serif text-[22px] text-[color:var(--fc-ink-heading)] md:text-[24px]">
            Asset Library
          </h2>
          <Text as="p" variant="body" className="mt-1.5">
            Upload and manage the visual assets used across this collective — banners, logos, icons, thumbnails, audio, video, and downloads.
          </Text>
        </div>
        <Button variant="primary" iconStart={<PlusIcon />} onClick={() => setShowUpload(true)}>
          Upload asset
        </Button>
      </div>

      {/* Resource separation note */}
      <div
        className="mb-6 flex items-start gap-3 rounded-[var(--fc-radius-xl)] border px-5 py-4"
        style={{
          borderColor: 'rgba(56,160,158,0.28)',
          background: 'var(--fc-accent-50)',
        }}
      >
        <span
          aria-hidden="true"
          className="mt-0.5 text-[14px] text-[color:var(--fc-accent-500)]"
        >
          ◫
        </span>
        <p className="text-[13px] leading-relaxed text-[color:var(--fc-ink-primary)]">
          <span className="font-[var(--fc-fw-semibold)]">Looking for member resources?</span>{' '}
          Add PDFs, links, guides, replays, and pathway materials in{' '}
          <a
            href="/creator-studio/resources"
            className="font-[var(--fc-fw-semibold)] text-[color:var(--fc-accent-500)] underline underline-offset-2"
          >
            Resources
          </a>
          .
        </p>
      </div>

      {/* Search + type filter */}
      <div className="mb-5 flex flex-wrap items-center gap-3">
        <SearchInput
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          onClear={() => setSearch('')}
          placeholder="Search by title or filename…"
          className="max-w-xs"
        />
        <div className="flex flex-wrap items-center gap-1.5" role="tablist" aria-label="Type filter">
          {TYPE_FILTERS.map((t) => {
            const active = typeFilter === t
            return (
              <button
                key={t}
                type="button"
                role="tab"
                aria-selected={active}
                onClick={() => setTypeFilter(t)}
                className={cn(
                  'rounded-[var(--fc-radius-md)] px-3 py-1.5 text-[12px] font-[var(--fc-fw-semibold)] capitalize transition-colors duration-[var(--fc-motion-hover)]',
                  active
                    ? 'text-[color:var(--fc-ink-inverse)]'
                    : 'text-[color:var(--fc-ink-primary)] opacity-60 hover:opacity-100',
                )}
                style={
                  active
                    ? { background: 'var(--fc-accent-500)' }
                    : { background: 'rgba(15,30,55,0.05)' }
                }
              >
                {t === 'all' ? 'All' : typeLabel(t as MediaAssetType)}
              </button>
            )
          })}
        </div>
      </div>

      {/* Asset grid or empty states */}
      {filtered.length > 0 ? (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {filtered.map((asset) => (
            <AssetCard
              key={asset.id}
              asset={asset}
              spaceSlug={spaceSlug}
              onArchive={handleArchive}
              onEdit={setEditingAsset}
            />
          ))}
        </div>
      ) : assets.length === 0 ? (
        <EmptyState
          title="No assets yet"
          description="Upload your first asset — image, video, audio, or file — to use across this collective."
          action={
            <Button variant="primary" iconStart={<PlusIcon />} onClick={() => setShowUpload(true)}>
              Upload first asset
            </Button>
          }
        />
      ) : (
        <EmptyState
          title="No matches"
          description="No files match your search or filter."
          action={
            <Button
              variant="tertiary"
              onClick={() => { setSearch(''); setTypeFilter('all') }}
            >
              Clear filters
            </Button>
          }
        />
      )}

      {/* Upload modal */}
      <UploadModal
        open={showUpload}
        spaceSlug={spaceSlug}
        onClose={() => setShowUpload(false)}
        onUploaded={handleUploaded}
      />

      {/* Edit modal */}
      <EditModal
        open={editingAsset !== null}
        spaceSlug={spaceSlug}
        asset={editingAsset}
        onClose={() => setEditingAsset(null)}
        onSaved={handleUpdated}
      />
    </section>
  )
}
