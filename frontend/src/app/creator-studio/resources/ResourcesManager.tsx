'use client'

import { useCallback, useMemo, useState, type ReactNode } from 'react'
import { useRouter } from 'next/navigation'
import { apiUrl } from '@/lib/api'
import OverflowMenu from '@/components/ui/OverflowMenu'
import {
  Badge, type BadgeTone,
  Button,
  Card,
  Drawer, DrawerSection,
  EmptyState,
  FormField,
  Input,
  SearchInput,
  Select,
  StatusBadge,
  Text,
  TextArea,
  cn,
  useConfirm,
  useToast,
} from '@/components/platform'
import type {
  CreatorPathway,
  CreatorResource,
  ResourceType,
  ResourceUsageReference,
  ResourceUsageResponse,
} from '@/types/platform'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

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

type FilterKey =
  | 'all' | 'recent' | 'published' | 'drafts'
  | 'files' | 'guides' | 'audio' | 'video' | 'links'
  | 'unused' | 'archived'

interface FormState {
  title: string
  description: string
  resource_type: ResourceType
  url: string
  status: 'draft' | 'published' | 'archived'
  pathway_ids: string[]
}

const EMPTY_FORM: FormState = {
  title: '',
  description: '',
  resource_type: 'link',
  url: '',
  status: 'draft',
  pathway_ids: [],
}

interface Props {
  spaceSlug: string
  initialResources: CreatorResource[]
  pathways: CreatorPathway[]
}

// Map resource type to Badge tone.
const TYPE_TO_BADGE: Record<ResourceType, BadgeTone> = {
  audio:    'audio',
  video:    'video',
  replay:   'video',
  guide:    'guide',
  template: 'guide',
  file:     'file',
  link:     'link',
  other:    'other',
}

const TYPE_LABEL: Record<ResourceType, string> = {
  audio: 'Audio', video: 'Video', replay: 'Replay', guide: 'Guide',
  template: 'Template', file: 'File', link: 'Link', other: 'Other',
}

// ---------------------------------------------------------------------------
// Preview categorisation.
//
// Sniffs the resource's `file_name` / `url` to differentiate PDF, Image,
// and generic File from the coarse resource_type. Nothing about the
// resource data model or backend surface changes — this is purely a
// visual recognition layer built from data already in the response.
// ---------------------------------------------------------------------------

type PreviewCategory = 'image' | 'pdf' | 'guide' | 'audio' | 'video' | 'link' | 'file' | 'generic'

const IMAGE_EXT = new Set(['jpg', 'jpeg', 'png', 'gif', 'webp', 'avif', 'svg', 'bmp'])

function extensionOf(name: string | null | undefined): string {
  if (!name) return ''
  const dot = name.lastIndexOf('.')
  if (dot < 0) return ''
  return name.slice(dot + 1).toLowerCase()
}

function categorizeResource(r: CreatorResource): PreviewCategory {
  const t = r.resource_type
  const nameExt = extensionOf(r.file_name)
  const urlExt = extensionOf(r.url)
  const anyExt = nameExt || urlExt

  if (t === 'audio')  return 'audio'
  if (t === 'video')  return 'video'
  if (t === 'replay') return 'video'
  if (t === 'guide')  return 'guide'
  // Templates read as guides visually.
  if (t === 'template') return 'guide'
  // File / link paths can still be an image or PDF — sniff the extension.
  if (anyExt === 'pdf') return 'pdf'
  if (IMAGE_EXT.has(anyExt)) return 'image'
  if (t === 'link') return 'link'
  if (t === 'file') return 'file'
  return 'generic'
}

// Category → background + icon colour. Non-image previews carry a very
// subtle diagonal gradient in the type family — enough to feel like a
// lightly designed cover, never a decorated illustration.
const RESOURCE_TINT: Record<PreviewCategory, { bg: string; fg: string }> = {
  image:   { bg: 'linear-gradient(135deg, rgba(56,160,158,0.12)  0%, rgba(56,160,158,0.04)  100%)', fg: '#0f766e' }, // pale teal
  pdf:     { bg: 'linear-gradient(135deg, rgba(214,96,87,0.12)   0%, rgba(214,96,87,0.03)   100%)', fg: '#a63c30' }, // blush → warm white
  guide:   { bg: 'linear-gradient(135deg, rgba(56,116,180,0.10)  0%, rgba(148,163,184,0.10) 100%)', fg: '#1e40af' }, // blue → slate
  audio:   { bg: 'linear-gradient(135deg, rgba(139,92,246,0.12)  0%, rgba(139,92,246,0.04)  100%)', fg: '#6d28d9' }, // pale lavender
  video:   { bg: 'linear-gradient(135deg, rgba(56,116,180,0.12)  0%, rgba(56,116,180,0.04)  100%)', fg: '#1e40af' }, // pale blue
  link:    { bg: 'linear-gradient(135deg, rgba(56,160,158,0.12)  0%, rgba(56,160,158,0.04)  100%)', fg: '#0f766e' }, // pale teal
  file:    { bg: 'linear-gradient(135deg, rgba(30,41,59,0.07)    0%, rgba(30,41,59,0.02)    100%)', fg: '#334155' }, // pale slate
  generic: { bg: 'linear-gradient(135deg, rgba(100,116,139,0.12) 0%, rgba(100,116,139,0.04) 100%)', fg: '#475569' }, // pale grey
}

/**
 * Preview icon for a resource category. Uses inline SVGs matching the
 * house style; no new icon dependency.
 */
function ResourceCategoryIcon({ category, size = 28 }: { category: PreviewCategory; size?: number }) {
  const s = size
  const props = {
    width: s, height: s, viewBox: '0 0 24 24', fill: 'none',
    stroke: 'currentColor', strokeWidth: 1.6,
    strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const,
  }
  if (category === 'image') {
    return (
      <svg {...props} aria-hidden="true">
        <rect x="3" y="3" width="18" height="18" rx="2" />
        <circle cx="8.5" cy="8.5" r="1.5" />
        <path d="M21 15l-5-5L5 21" />
      </svg>
    )
  }
  if (category === 'pdf') {
    return (
      <svg {...props} aria-hidden="true">
        <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
        <polyline points="14 2 14 8 20 8" />
        <text x="12" y="18" textAnchor="middle" fontSize="6" fontFamily="sans-serif" fontWeight="700" fill="currentColor" stroke="none">PDF</text>
      </svg>
    )
  }
  if (category === 'guide') {
    return (
      <svg {...props} aria-hidden="true">
        <path d="M4 5a2 2 0 012-2h11v18H6a2 2 0 01-2-2V5z" />
        <line x1="8" y1="7" x2="15" y2="7" />
        <line x1="8" y1="11" x2="15" y2="11" />
        <line x1="8" y1="15" x2="12" y2="15" />
      </svg>
    )
  }
  if (category === 'audio') {
    return (
      <svg {...props} aria-hidden="true">
        <path d="M9 18V5l12-2v13" />
        <circle cx="6" cy="18" r="3" />
        <circle cx="18" cy="16" r="3" />
      </svg>
    )
  }
  if (category === 'video') {
    return (
      <svg {...props} aria-hidden="true">
        <rect x="3" y="4" width="18" height="16" rx="2" />
        <path d="M10 9l6 3-6 3V9z" fill="currentColor" stroke="none" />
      </svg>
    )
  }
  if (category === 'link') {
    return (
      <svg {...props} aria-hidden="true">
        <path d="M10 14a5 5 0 007 0l3-3a5 5 0 00-7-7l-1 1" />
        <path d="M14 10a5 5 0 00-7 0l-3 3a5 5 0 007 7l1-1" />
      </svg>
    )
  }
  // file / generic
  return (
    <svg {...props} aria-hidden="true">
      <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
      <polyline points="14 2 14 8 20 8" />
      <line x1="8"  y1="13" x2="16" y2="13" />
      <line x1="8"  y1="17" x2="12" y2="17" />
    </svg>
  )
}

/**
 * Shallow type-strip at the top of a Resource card.
 *
 * Resources are a management surface — an "organised library" of
 * catalogue entries, not a gallery of artwork. The type strip is a
 * quiet identifier: a small icon on the left, the type label beside
 * it, on a subtle gradient in the type family. Deliberately no image
 * thumbnails here — that lives in Media Library where artwork IS the
 * content.
 */
function ResourceTypeStrip({
  category, typeLabel,
}: {
  category: PreviewCategory
  typeLabel: string
}) {
  const tint = RESOURCE_TINT[category]
  return (
    <div
      className="relative flex h-14 w-full items-center gap-2 rounded-t-[var(--fc-radius-lg)] px-3.5"
      style={{ background: tint.bg, color: tint.fg }}
    >
      <ResourceCategoryIcon category={category} size={20} />
      <span className="text-[11px] font-[var(--fc-fw-semibold)] uppercase tracking-[var(--fc-tracking-eyebrow)]">
        {typeLabel}
      </span>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Pathway palette — dot colour on cards + 3px stripe on the drawer.
// ---------------------------------------------------------------------------

interface PathwayPalette {
  dot:       string
  drawerBar: string
}

const PAL: Record<string, PathwayPalette> = {
  teal:  { dot: '#38A09E', drawerBar: '#38A09E' },
  navy:  { dot: '#3D6289', drawerBar: '#3D6289' },
  blue:  { dot: '#4F7ABE', drawerBar: '#4F7ABE' },
  lilac: { dot: '#7C6BB0', drawerBar: '#7C6BB0' },
  sage:  { dot: '#6B8E7F', drawerBar: '#6B8E7F' },
  grey:  { dot: '#94A3B8', drawerBar: '#94A3B8' },
}

function hashSlug(s: string): number {
  let h = 0
  for (let i = 0; i < s.length; i++) h = ((h << 5) - h) + s.charCodeAt(i)
  return Math.abs(h)
}
const ROTATION: PathwayPalette[] = [PAL.blue, PAL.sage, PAL.lilac, PAL.navy]

function paletteForPathway(pathway: { slug: string } | null | undefined, isArchived: boolean): PathwayPalette {
  if (isArchived) return PAL.grey
  if (!pathway) return PAL.teal
  const s = pathway.slug.toLowerCase()
  if (s.includes('life-in-alignment') || s === 'lia')      return PAL.navy
  if (s.includes('human-design') || s.includes('shortcut')) return PAL.blue
  if (s.includes('embody'))                                return PAL.lilac
  if (s.includes('home-practice') || s.includes('home'))   return PAL.sage
  return ROTATION[hashSlug(pathway.slug) % ROTATION.length]
}

// ---------------------------------------------------------------------------
// Small helpers
// ---------------------------------------------------------------------------

function usageLabel(count: number): string {
  if (count === 0) return 'Not linked'
  if (count === 1) return 'Linked to 1 lesson'
  return `Linked to ${count} lessons`
}

function formatBytes(bytes: number | null | undefined): string | null {
  if (bytes === null || bytes === undefined) return null
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('en-AU', {
    day: 'numeric', month: 'short', year: 'numeric',
  })
}

const STATUS_OPTIONS: { key: 'all' | 'published' | 'drafts'; label: string }[] = [
  { key: 'all',       label: 'All' },
  { key: 'published', label: 'Published' },
  { key: 'drafts',    label: 'Draft' },
]

const CONTENT_OPTIONS: { key: 'all' | 'guides' | 'files' | 'audio' | 'video' | 'links'; label: string }[] = [
  { key: 'all',    label: 'All' },
  { key: 'guides', label: 'Guide' },
  { key: 'files',  label: 'File'  },
  { key: 'audio',  label: 'Audio' },
  { key: 'video',  label: 'Video' },
  { key: 'links',  label: 'Link'  },
]

const SECONDARY_FILTERS: { key: 'recent' | 'unused' | 'archived'; label: string }[] = [
  { key: 'recent',   label: 'Recent'   },
  { key: 'unused',   label: 'Unused'   },
  { key: 'archived', label: 'Archived' },
]

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function ResourcesManager({ spaceSlug, initialResources, pathways }: Props) {
  const router = useRouter()
  const toast = useToast()
  const confirm = useConfirm()

  const [resources, setResources] = useState<CreatorResource[]>(initialResources)

  const [formMode, setFormMode] = useState<null | 'create' | string>(null)
  const [form, setForm] = useState<FormState>(EMPTY_FORM)
  const [uploadFile, setUploadFile] = useState<File | null>(null)
  const [saving, setSaving] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const [deletingId, setDeletingId] = useState<string | null>(null)

  const [search, setSearch] = useState('')
  const [filter, setFilter] = useState<FilterKey>('all')

  const activePaths = pathways.filter((p) => p.status !== 'archived')

  const editingResource = useMemo(
    () => (formMode !== null && formMode !== 'create')
      ? resources.find(r => r.id === formMode) ?? null
      : null,
    [formMode, resources],
  )

  // -- "Recently added" window ----------------------------------------------
  const FOURTEEN_DAYS_MS = 14 * 24 * 60 * 60 * 1000
  const isRecent = useCallback((r: CreatorResource) => {
    if (!r.created_at) return false
    return (Date.now() - new Date(r.created_at).getTime()) < FOURTEEN_DAYS_MS
  }, [FOURTEEN_DAYS_MS])

  // -- Filtering + search ---------------------------------------------------
  const filterMatches = (r: CreatorResource): boolean => {
    switch (filter) {
      case 'all':       return r.status !== 'archived'
      case 'recent':    return isRecent(r) && r.status !== 'archived'
      case 'published': return r.status === 'published'
      case 'drafts':    return r.status === 'draft'
      case 'files':     return r.resource_type === 'file'    && r.status !== 'archived'
      case 'guides':    return r.resource_type === 'guide'   && r.status !== 'archived'
      case 'audio':     return r.resource_type === 'audio'   && r.status !== 'archived'
      case 'video':     return r.resource_type === 'video'   && r.status !== 'archived'
      case 'links':     return r.resource_type === 'link'    && r.status !== 'archived'
      case 'unused':    return r.usage_count === 0           && r.status !== 'archived'
      case 'archived':  return r.status === 'archived'
    }
  }
  const searchMatches = (r: CreatorResource): boolean => {
    if (!search.trim()) return true
    const q = search.toLowerCase()
    return (
      r.title.toLowerCase().includes(q) ||
      (r.description?.toLowerCase().includes(q) ?? false) ||
      (r.file_name?.toLowerCase().includes(q) ?? false)
    )
  }

  const statusRank = (s: CreatorResource['status']) =>
    s === 'published' ? 0 : s === 'draft' ? 1 : 2

  const visible: CreatorResource[] = useMemo(() => {
    const list = resources.filter(r => searchMatches(r) && filterMatches(r))
    if (filter === 'recent') {
      return list.slice().sort((a, b) => (b.created_at || '').localeCompare(a.created_at || ''))
    }
    return list.slice().sort((a, b) => {
      const s = statusRank(a.status) - statusRank(b.status)
      if (s !== 0) return s
      return a.title.localeCompare(b.title)
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resources, filter, search])

  // Segmented-control resolvers — same-shape mapping onto the single filter.
  const statusValue: 'all' | 'published' | 'drafts' =
    filter === 'published' || filter === 'drafts' ? filter : 'all'
  const contentValue: 'all' | 'guides' | 'files' | 'audio' | 'video' | 'links' =
    ['guides', 'files', 'audio', 'video', 'links'].includes(filter)
      ? filter as 'guides' | 'files' | 'audio' | 'video' | 'links'
      : 'all'

  // -- Form helpers ---------------------------------------------------------
  function openCreate() {
    setForm(EMPTY_FORM); setUploadFile(null); setFormError(null); setFormMode('create')
  }

  function openEdit(r: CreatorResource) {
    setForm({
      title: r.title,
      description: r.description ?? '',
      resource_type: r.resource_type as ResourceType,
      url: r.url ?? '',
      status: r.status,
      pathway_ids: (r.pathways ?? []).map(p => p.id),
    })
    setUploadFile(null); setFormError(null); setFormMode(r.id)
  }

  function openDuplicate(r: CreatorResource) {
    setForm({
      title: `${r.title} (copy)`,
      description: r.description ?? '',
      resource_type: r.resource_type as ResourceType,
      url: r.url ?? '',
      status: 'draft',
      pathway_ids: (r.pathways ?? []).map(p => p.id),
    })
    setUploadFile(null); setFormError(null); setFormMode('create')
  }

  const cancelForm = useCallback(() => {
    setFormMode(null); setFormError(null); setUploadFile(null)
  }, [])

  function togglePathway(id: string) {
    setForm(f => {
      const has = f.pathway_ids.includes(id)
      return { ...f, pathway_ids: has ? f.pathway_ids.filter(x => x !== id) : [...f.pathway_ids, id] }
    })
  }

  async function handleSave() {
    if (!form.title.trim()) { setFormError('Title is required.'); return }
    const isCreate = formMode === 'create'
    setSaving(true); setFormError(null)
    try {
      let res: Response
      if (uploadFile) {
        const fd = new FormData()
        fd.append('file', uploadFile)
        fd.append('title', form.title.trim())
        fd.append('description', form.description.trim())
        fd.append('resource_type', form.resource_type)
        fd.append('status', form.status)
        fd.append('pathway_ids', JSON.stringify(form.pathway_ids))
        res = await fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/resources/upload`), {
          method: 'POST', credentials: 'include', body: fd,
        })
      } else if (isCreate) {
        res = await fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/resources`), {
          method: 'POST', credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            title: form.title.trim(),
            description: form.description.trim() || null,
            resource_type: form.resource_type,
            url: form.url.trim() || null,
            status: form.status,
            pathway_ids: form.pathway_ids,
          }),
        })
      } else {
        res = await fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/resources/${formMode}`), {
          method: 'PATCH', credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            title: form.title.trim(),
            description: form.description.trim() || null,
            resource_type: form.resource_type,
            url: form.url.trim() || null,
            status: form.status,
            pathway_ids: form.pathway_ids,
          }),
        })
      }

      if (!res.ok) {
        const b = await res.json().catch(() => ({}))
        throw new Error(typeof b.detail === 'string' ? b.detail : `Save failed (${res.status})`)
      }

      const saved: CreatorResource = await res.json()
      if (isCreate || uploadFile) {
        setResources((prev) => [...prev, saved])
      } else {
        setResources((prev) => prev.map((r) => r.id === saved.id ? saved : r))
      }
      setFormMode(null)
      router.refresh()
      toast.show(isCreate ? 'Resource added' : 'Changes saved', { tone: 'success' })
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Something went wrong.'
      setFormError(message)
    } finally {
      setSaving(false)
    }
  }

  async function patchResource(id: string, patch: Record<string, unknown>) {
    const res = await fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/resources/${id}`), {
      method: 'PATCH', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    })
    if (!res.ok) return null
    const updated: CreatorResource = await res.json()
    setResources((prev) => prev.map((x) => x.id === updated.id ? updated : x))
    return updated
  }

  async function handleTogglePublish(r: CreatorResource) {
    const target = r.status === 'published' ? 'draft' : 'published'
    const result = await patchResource(r.id, { status: target })
    if (result) {
      toast.show(target === 'published' ? 'Published' : 'Unpublished', { tone: 'success' })
    } else {
      toast.show('Could not update status', { tone: 'error' })
    }
  }

  async function handleArchive(r: CreatorResource) {
    const result = await patchResource(r.id, { status: 'archived' })
    if (result) {
      toast.show('Archived', { tone: 'success' })
    } else {
      toast.show('Could not archive', { tone: 'error' })
    }
  }

  async function handleRestore(r: CreatorResource) {
    const result = await patchResource(r.id, { status: 'draft' })
    if (result) {
      toast.show('Restored to draft', { tone: 'success' })
    } else {
      toast.show('Could not restore', { tone: 'error' })
    }
  }

  async function handleDelete(id: string) {
    const target = resources.find(r => r.id === id)
    const yes = await confirm({
      title: target ? `Delete “${target.title}”?` : 'Delete this resource?',
      body: 'This cannot be undone.',
      confirmLabel: 'Delete',
      tone: 'danger',
    })
    if (!yes) return

    setDeletingId(id)
    try {
      const res = await fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/resources/${id}`), {
        method: 'DELETE', credentials: 'include',
      })
      if (!res.ok) throw new Error(`Delete failed (${res.status})`)
      setResources((prev) => prev.filter((r) => r.id !== id))
      if (formMode === id) setFormMode(null)
      router.refresh()
      toast.show('Resource deleted', { tone: 'success' })
    } catch {
      toast.show('Could not delete resource', { tone: 'error' })
    } finally {
      setDeletingId(null)
    }
  }

  // -- Top stats ------------------------------------------------------------
  const publishedCount = resources.filter((r) => r.status === 'published').length
  const draftsCount    = resources.filter((r) => r.status === 'draft').length
  const unusedCount    = resources.filter((r) => r.usage_count === 0 && r.status !== 'archived').length
  const totalCount     = resources.filter(r => r.status !== 'archived').length

  const drawerAccent = editingResource
    ? paletteForPathway(editingResource.pathways?.[0] ?? null, editingResource.status === 'archived').drawerBar
    : PAL.teal.drawerBar

  return (
    <div>
      {/* Stats */}
      <div className="mb-8 grid grid-cols-2 gap-3 md:grid-cols-4 md:gap-4">
        <StatCard label="Total"     value={totalCount} />
        <StatCard label="Published" value={publishedCount} />
        <StatCard label="Drafts"    value={draftsCount} />
        <StatCard label="Unused"    value={unusedCount} />
      </div>

      {/* Action row */}
      <div className="mb-5 flex flex-wrap items-center gap-3">
        <Button variant="primary" onClick={openCreate}>+ Add resource</Button>
        <SearchInput
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          onClear={() => setSearch('')}
          placeholder="Search resources…"
          className="flex-1"
        />
      </div>

      {/* Filters — two segmented controls + secondary text buttons */}
      <div className="mb-8 space-y-2.5">
        <div className="flex flex-wrap items-center gap-x-6 gap-y-2.5">
          <SegmentedControl
            label="Status"
            value={statusValue}
            options={STATUS_OPTIONS}
            onChange={(k) => setFilter(k)}
          />
          <SegmentedControl
            label="Type"
            value={contentValue}
            options={CONTENT_OPTIONS}
            onChange={(k) => setFilter(k)}
          />
        </div>
        <div className="flex flex-wrap items-center gap-1">
          <span className="mr-1 text-[10px] font-[var(--fc-fw-semibold)] uppercase tracking-[var(--fc-tracking-eyebrow)] text-[color:var(--fc-ink-primary)]">
            View
          </span>
          {SECONDARY_FILTERS.map((f) => {
            const active = filter === f.key
            return (
              <button
                key={f.key}
                type="button"
                onClick={() => setFilter(active ? 'all' : f.key)}
                className={cn(
                  'rounded-[var(--fc-radius-md)] px-2.5 py-1 text-[12px] font-[var(--fc-fw-semibold)] transition-colors duration-[var(--fc-motion-hover)]',
                  active
                    ? 'bg-[rgba(15,30,55,0.06)] text-[color:var(--fc-ink-heading)]'
                    : 'text-[color:var(--fc-ink-disabled)] hover:text-[color:var(--fc-ink-heading)]',
                )}
              >
                {f.label}
              </button>
            )
          })}
        </div>
      </div>

      {/* Grid or empty states */}
      {resources.length === 0 ? (
        <EmptyState
          title="No resources yet"
          description="Add links, files, guides, and tools for your members."
          action={<Button variant="primary" onClick={openCreate}>+ Add first resource</Button>}
        />
      ) : visible.length === 0 ? (
        <EmptyState
          title="No matches"
          description="No resources match this search or filter."
          action={
            <Button variant="tertiary" onClick={() => { setSearch(''); setFilter('all') }}>
              Clear filters
            </Button>
          }
        />
      ) : (
        <>
          <Text variant="meta" className="mb-4">
            {visible.length} {visible.length === 1 ? 'resource' : 'resources'}
          </Text>
          <div className="grid grid-cols-1 gap-5 md:grid-cols-2 md:gap-6 xl:grid-cols-3">
            {visible.map((r) => (
              <ResourceCard
                key={r.id}
                resource={r}
                selected={formMode === r.id}
                onOpen={() => openEdit(r)}
                onTogglePublish={() => handleTogglePublish(r)}
                onArchive={() => handleArchive(r)}
                onRestore={() => handleRestore(r)}
                onDelete={() => handleDelete(r.id)}
                deleting={deletingId === r.id}
              />
            ))}
          </div>
        </>
      )}

      {/* Right-hand details drawer */}
      <Drawer
        open={formMode !== null}
        onClose={cancelForm}
        eyebrow={formMode === 'create' ? 'New resource' : 'Resource'}
        title={formMode === 'create' ? 'Add resource' : (editingResource?.title ?? 'Resource')}
        accentColor={drawerAccent}
        footer={
          <>
            <Button variant="primary" onClick={handleSave} loading={saving}>
              {formMode === 'create' ? 'Add resource' : 'Save changes'}
            </Button>
            <Button variant="tertiary" onClick={cancelForm} disabled={saving}>Cancel</Button>
            {editingResource && (
              <div className="ml-auto flex flex-wrap items-center gap-2">
                <Button variant="secondary" onClick={() => openDuplicate(editingResource)}>
                  Duplicate
                </Button>
                {editingResource.status === 'archived' ? (
                  <Button variant="secondary" onClick={() => handleRestore(editingResource)}>
                    Restore
                  </Button>
                ) : (
                  <Button variant="secondary" onClick={() => handleArchive(editingResource)}>
                    Archive
                  </Button>
                )}
                <Button
                  variant="danger"
                  onClick={() => handleDelete(editingResource.id)}
                  loading={deletingId === editingResource.id}
                >
                  Delete
                </Button>
              </div>
            )}
          </>
        }
      >
        <DrawerSection title="General" first>
          <div className="space-y-4">
            <FormField label="Title" required error={formError && !form.title.trim() ? formError : undefined}>
              <Input
                value={form.title}
                onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))}
                maxLength={300}
                placeholder="e.g. Breath awareness practice"
              />
            </FormField>

            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <FormField label="Type">
                <Select
                  value={form.resource_type}
                  onChange={(e) => setForm((f) => ({ ...f, resource_type: e.target.value as ResourceType }))}
                >
                  {RESOURCE_TYPES.map((t) => (
                    <option key={t.value} value={t.value}>{t.label}</option>
                  ))}
                </Select>
              </FormField>

              <FormField label="Status">
                <div className="flex gap-2">
                  {(['draft', 'published'] as const).map((s) => (
                    <button
                      key={s}
                      type="button"
                      onClick={() => setForm((f) => ({ ...f, status: s }))}
                      className={cn(
                        'flex-1 rounded-[var(--fc-radius-md)] border px-3 py-2.5 text-[13px] font-[var(--fc-fw-semibold)] transition-all duration-[var(--fc-motion-hover)]',
                        form.status === s
                          ? 'border-[color:var(--fc-accent-500)]/40 bg-[color:var(--fc-accent-500)]/[0.06] text-[color:var(--fc-accent-700)]'
                          : 'border-[color:var(--fc-border-input)] bg-transparent text-[color:var(--fc-ink-primary)]',
                      )}
                    >
                      {s === 'draft' ? 'Draft' : 'Published'}
                    </button>
                  ))}
                </div>
              </FormField>
            </div>
          </div>
        </DrawerSection>

        <DrawerSection title="Content">
          <div className="space-y-4">
            <FormField label="Description">
              <TextArea
                value={form.description}
                onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
                rows={3}
                placeholder="Brief description of this resource"
              />
            </FormField>

            {editingResource && (editingResource.file_name || editingResource.url) && (
              <MetaBlock>
                {editingResource.file_name && (
                  <MetaLine
                    label="File"
                    value={
                      <>
                        <span className="text-[color:var(--fc-ink-heading)]">
                          {editingResource.file_name}
                        </span>
                        {formatBytes(editingResource.file_size) && (
                          <span className="text-[color:var(--fc-ink-primary)]">
                            {' · '}
                            {formatBytes(editingResource.file_size)}
                          </span>
                        )}
                      </>
                    }
                  />
                )}
                {editingResource.url && !editingResource.file_name && (
                  <MetaLine
                    label="URL"
                    value={
                      <a
                        href={editingResource.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="truncate text-[color:var(--fc-accent-700)] underline-offset-2 hover:underline"
                      >
                        {editingResource.url}
                      </a>
                    }
                  />
                )}
                <MetaLine label="Added" value={formatDate(editingResource.created_at)} />
              </MetaBlock>
            )}

            {!uploadFile && (
              <FormField label="URL">
                <Input
                  type="url"
                  value={form.url}
                  onChange={(e) => setForm((f) => ({ ...f, url: e.target.value }))}
                  placeholder="https://…"
                />
              </FormField>
            )}

            {formMode === 'create' && (
              <div className="flex flex-col gap-1.5">
                <label
                  htmlFor="fc-resource-file"
                  className="text-[12px] font-[var(--fc-fw-semibold)] uppercase tracking-[var(--fc-tracking-eyebrow-tight)] text-[color:var(--fc-ink-primary)]"
                >
                  Or upload a file
                </label>
                <input
                  id="fc-resource-file"
                  type="file"
                  accept=".pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.jpg,.jpeg,.png,.webp,.mp3,.wav,.m4a,.mp4,.mov"
                  onChange={(e) => {
                    const f = e.target.files?.[0] ?? null
                    setUploadFile(f)
                    if (f) setForm((prev) => ({ ...prev, url: '' }))
                  }}
                  className="block w-full text-[13px] text-[color:var(--fc-ink-primary)] file:mr-3 file:rounded-[var(--fc-radius-md)] file:border-0 file:bg-slate-100 file:px-3 file:py-1.5 file:text-[12px] file:font-[var(--fc-fw-semibold)] file:text-[color:var(--fc-ink-primary)]"
                />
                {uploadFile && (
                  <Text as="p" variant="meta">
                    {uploadFile.name} ({(uploadFile.size / 1024).toFixed(0)} KB)
                  </Text>
                )}
              </div>
            )}
          </div>
        </DrawerSection>

        <DrawerSection title="Availability">
          <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
            <PathwayToggle
              checked={form.pathway_ids.length === 0}
              onToggle={() => setForm(f => ({ ...f, pathway_ids: [] }))}
              label="General"
              hint="All members"
            />
            {activePaths.map((p) => (
              <PathwayToggle
                key={p.id}
                checked={form.pathway_ids.includes(p.id)}
                onToggle={() => togglePathway(p.id)}
                label={p.title}
              />
            ))}
          </div>
        </DrawerSection>

        {editingResource && (
          <DrawerSection title="Usage">
            <DrawerUsage
              resourceId={editingResource.id}
              usageCount={editingResource.usage_count}
              spaceSlug={spaceSlug}
            />
          </DrawerSection>
        )}

        {formError && form.title.trim() && (
          <div
            role="alert"
            className="mt-6 rounded-[var(--fc-radius-md)] px-3 py-2 text-[13px] text-[color:var(--fc-status-error-text)]"
            style={{ background: 'var(--fc-status-error-bg)' }}
          >
            {formError}
          </div>
        )}
      </Drawer>
    </div>
  )
}

// ---------------------------------------------------------------------------
// StatCard — Card with stat figure + eyebrow label.
// ---------------------------------------------------------------------------

function StatCard({ label, value }: { label: string; value: number }) {
  return (
    <Card padding="md">
      <Text variant="stat">{value}</Text>
      <Text variant="eyebrow" muted className="mt-2">{label}</Text>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// SegmentedControl — filter pattern (Fresh Collective does not ship a segmented-control
// primitive; kept local per Phase 3 scope and re-styled with Fresh Collective tokens).
// ---------------------------------------------------------------------------

function SegmentedControl<T extends string>({
  label, value, options, onChange,
}: {
  label: string
  value: T
  options: { key: T; label: string }[]
  onChange: (key: T) => void
}) {
  return (
    <div className="flex items-center gap-2.5">
      <span className="text-[10px] font-[var(--fc-fw-semibold)] uppercase tracking-[var(--fc-tracking-eyebrow)] text-[color:var(--fc-ink-primary)]">
        {label}
      </span>
      <div
        role="tablist"
        className="inline-flex items-center rounded-[var(--fc-radius-lg)] p-0.5"
        style={{ background: 'rgba(15,30,55,0.05)' }}
      >
        {options.map((opt) => {
          const active = value === opt.key
          return (
            <button
              key={opt.key}
              type="button"
              role="tab"
              aria-selected={active}
              onClick={() => onChange(opt.key)}
              className={cn(
                'rounded-[var(--fc-radius-md)] px-3 py-1 text-[12.5px] font-[var(--fc-fw-semibold)] transition-colors duration-[var(--fc-motion-hover)]',
                active
                  ? 'text-[color:var(--fc-ink-heading)]'
                  : 'text-[color:var(--fc-ink-primary)] opacity-60 hover:opacity-100',
              )}
              style={
                active
                  ? {
                      background: 'var(--fc-surface-card)',
                      boxShadow: '0 1px 2px rgba(15,30,55,0.06)',
                    }
                  : undefined
              }
            >
              {opt.label}
            </button>
          )
        })}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// PathwayToggle — pill-style checkbox for the "Available in" section.
// ---------------------------------------------------------------------------

function PathwayToggle({
  checked, onToggle, label, hint,
}: {
  checked: boolean
  onToggle: () => void
  label: string
  hint?: string
}) {
  return (
    <label
      className={cn(
        'flex cursor-pointer items-center gap-2.5 rounded-[var(--fc-radius-md)] border px-3 py-2 text-[13px] font-[var(--fc-fw-semibold)] transition-all duration-[var(--fc-motion-hover)]',
      )}
      style={{
        borderColor: checked ? 'rgba(56,160,158,0.40)' : 'var(--fc-border-input)',
        background: checked ? 'rgba(56,160,158,0.06)' : 'transparent',
        color: checked ? 'var(--fc-accent-700)' : 'var(--fc-ink-primary)',
      }}
    >
      <input
        type="checkbox"
        checked={checked}
        onChange={onToggle}
        className="accent-[color:var(--fc-accent-500)]"
      />
      <span>{label}</span>
      {hint && (
        <span className="ml-auto text-[11px] font-[var(--fc-fw-regular)] text-[color:var(--fc-ink-primary)]">
          {hint}
        </span>
      )}
    </label>
  )
}

// ---------------------------------------------------------------------------
// MetaBlock / MetaLine — compact read-only key/value strip inside the drawer.
// ---------------------------------------------------------------------------

function MetaBlock({ children }: { children: ReactNode }) {
  return (
    <dl className="rounded-[var(--fc-radius-md)] bg-slate-50 px-4 py-3 text-[12.5px]">
      {children}
    </dl>
  )
}

function MetaLine({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex items-baseline gap-3 py-0.5">
      <dt className="w-14 shrink-0 text-[11px] font-[var(--fc-fw-semibold)] uppercase tracking-[var(--fc-tracking-eyebrow-tight)] text-[color:var(--fc-ink-primary)]">
        {label}
      </dt>
      <dd className="min-w-0 flex-1 truncate text-[color:var(--fc-ink-primary)]">
        {value}
      </dd>
    </div>
  )
}

// ---------------------------------------------------------------------------
// DrawerUsage — "Linked to N lessons" + expand to show grouped references.
// ---------------------------------------------------------------------------

function DrawerUsage({
  resourceId, usageCount, spaceSlug,
}: {
  resourceId: string
  usageCount: number
  spaceSlug: string
}) {
  const [expanded, setExpanded] = useState(false)
  const [loading, setLoading] = useState(false)
  const [refs, setRefs] = useState<ResourceUsageReference[] | null>(null)

  async function toggle() {
    if (refs !== null) { setExpanded(v => !v); return }
    setLoading(true)
    try {
      const res = await fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/resources/${resourceId}/usage`), {
        credentials: 'include',
      })
      if (res.ok) {
        const body: ResourceUsageResponse = await res.json()
        setRefs(body.references)
      } else {
        setRefs([])
      }
    } catch {
      setRefs([])
    } finally {
      setLoading(false)
      setExpanded(true)
    }
  }

  const grouped = useMemo(() => {
    if (!refs) return null
    const buckets = new Map<string, { pathwayTitle: string; refs: ResourceUsageReference[] }>()
    for (const ref of refs) {
      const key = ref.pathway_id ?? '__none__'
      const title = ref.pathway_title ?? '—'
      if (!buckets.has(key)) buckets.set(key, { pathwayTitle: title, refs: [] })
      buckets.get(key)!.refs.push(ref)
    }
    return Array.from(buckets.values())
  }, [refs])

  return (
    <div>
      <div className="flex items-center gap-2.5">
        <Text variant="body-strong">{usageLabel(usageCount)}</Text>
        {usageCount > 0 && (
          <button
            type="button"
            onClick={toggle}
            disabled={loading}
            className="text-[12px] font-[var(--fc-fw-semibold)] text-[color:var(--fc-accent-700)] underline-offset-2 hover:underline"
          >
            {loading ? 'Loading…' : expanded ? 'Hide' : 'Show where'}
          </button>
        )}
      </div>

      {expanded && refs !== null && (
        <div className="mt-3 rounded-[var(--fc-radius-md)] bg-slate-50 px-4 py-3 text-[12px]">
          {refs.length === 0 ? (
            <Text variant="meta" muted>Not referenced from any pathway yet.</Text>
          ) : (
            <ul className="space-y-2.5">
              {grouped!.map((g) => (
                <li key={g.pathwayTitle}>
                  <Text variant="body-strong" className="text-[12px]">{g.pathwayTitle}</Text>
                  <ul className="ml-3 mt-1 space-y-0.5">
                    {g.refs.map((ref, i) => (
                      <li key={i} className="text-[12px] text-[color:var(--fc-ink-primary)]">
                        {ref.href ? (
                          <a
                            href={ref.href}
                            className="underline-offset-2 hover:text-[color:var(--fc-accent-700)] hover:underline"
                          >
                            {ref.step_title ?? (ref.kind === 'about_block' ? 'About page' : 'Step')}
                          </a>
                        ) : (
                          <span>{ref.step_title ?? 'About page'}</span>
                        )}
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
  )
}

// ---------------------------------------------------------------------------
// ResourceCard — Card + Badge + StatusBadge composition.
// ---------------------------------------------------------------------------

function ResourceCard({
  resource, selected, onOpen, onTogglePublish, onArchive, onRestore, onDelete, deleting,
}: {
  resource: CreatorResource
  selected: boolean
  onOpen: () => void
  onTogglePublish: () => void
  onArchive: () => void
  onRestore: () => void
  onDelete: () => void
  deleting: boolean
}) {
  const r = resource
  const isArchived = r.status === 'archived'
  const primary = r.pathways?.[0] ?? null
  const pathwayPalette = paletteForPathway(primary, isArchived)
  const pathwayLabel = primary?.title ?? 'General'

  const variant =
    selected   ? 'selected' :
    isArchived ? 'archived' :
    'default'

  const overflowItems = isArchived
    ? [
        { label: 'Restore', onClick: onRestore },
        {
          label: deleting ? 'Deleting…' : 'Delete',
          onClick: onDelete, tone: 'danger' as const,
          dividerAbove: true, disabled: deleting,
        },
      ]
    : [
        { label: r.status === 'published' ? 'Unpublish' : 'Publish', onClick: onTogglePublish },
        { label: 'Archive', onClick: onArchive },
        {
          label: deleting ? 'Deleting…' : 'Delete',
          onClick: onDelete, tone: 'danger' as const,
          dividerAbove: true, disabled: deleting,
        },
      ]

  const statusKind: 'published' | 'draft' | 'archived' =
    r.status === 'published' ? 'published'
    : r.status === 'archived' ? 'archived'
    : 'draft'

  const category = categorizeResource(r)
  const typeLabelText = TYPE_LABEL[r.resource_type]
  const updated = r.updated_at ?? r.created_at

  return (
    <Card
      as="article"
      variant={variant}
      padding="none"
      interactive={!selected}
      role="button"
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onOpen() }
      }}
      className="flex min-w-0 flex-col overflow-hidden text-left"
    >
      {/* Shallow type strip — a quiet identifier, not a cover. */}
      <div className="relative">
        <ResourceTypeStrip category={category} typeLabel={typeLabelText} />
        <div
          className="absolute right-2 top-1/2 -translate-y-1/2"
          onClick={(e) => e.stopPropagation()}
          onKeyDown={(e) => e.stopPropagation()}
        >
          <OverflowMenu
            ariaLabel={`Actions for ${r.title}`}
            items={overflowItems}
          />
        </div>
      </div>

      {/* Body — information-dense, catalogue-card feel. */}
      <div className="flex min-w-0 flex-1 flex-col px-3.5 pt-3 pb-3">
        <h4
          className="line-clamp-2 text-[14.5px] font-[var(--fc-fw-semibold)] leading-snug text-[color:var(--fc-ink-heading)]"
          title={r.title}
        >
          {r.title}
        </h4>

        {/* Type + status chips */}
        <div className="mt-1.5 flex items-center gap-1.5">
          <Badge tone={TYPE_TO_BADGE[r.resource_type]}>
            {TYPE_LABEL[r.resource_type]}
          </Badge>
          <StatusBadge status={statusKind} />
        </div>

        {/* Attached to — pathway or General */}
        <div className="mt-2.5 flex items-center gap-2">
          <span
            className="inline-block h-1.5 w-1.5 shrink-0 rounded-full"
            style={{ background: pathwayPalette.dot }}
            aria-hidden="true"
          />
          <span className="truncate text-[12.5px] font-[var(--fc-fw-semibold)] text-[color:var(--fc-ink-primary)]">
            {pathwayLabel}
          </span>
        </div>

        {/* Link status + updated date on a single tight row */}
        <div className="mt-1 flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
          <span className="text-[11.5px] text-[color:var(--fc-ink-primary)]">
            {usageLabel(r.usage_count)}
          </span>
          {updated && (
            <span className="text-[11px] text-[color:var(--fc-ink-secondary,rgba(12,24,38,0.55))]">
              Updated {formatDate(updated)}
            </span>
          )}
        </div>
      </div>
    </Card>
  )
}

