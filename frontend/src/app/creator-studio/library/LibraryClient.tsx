'use client'

import { useCallback, useEffect, useState } from 'react'
import { apiUrl } from '@/lib/api'
import type {
  LibraryFolder,
  LibraryItem,
  LibraryListResponse,
  LibraryMediaType,
} from '@/types/platform'
import {
  Button,
  FormField,
  Input,
  Modal,
  SearchInput,
  TextArea,
  useToast,
} from '@/components/platform'

/**
 * LibraryClient — the unified Library UI. One list, one folder rail,
 * two entry points (Upload, Add Link). The creator never sees which
 * backend store an item lives in.
 */

interface Props {
  spaceSlug: string
  initial: LibraryListResponse
}

type TypeFilter = 'any' | 'image' | 'video' | 'audio' | 'document' | 'link'

const TYPE_FILTERS: { key: TypeFilter; label: string }[] = [
  { key: 'any', label: 'All' },
  { key: 'image', label: 'Images' },
  { key: 'video', label: 'Videos' },
  { key: 'audio', label: 'Audio' },
  { key: 'document', label: 'Documents' },
  { key: 'link', label: 'Links' },
]

const FILE_ICONS: Record<LibraryMediaType, string> = {
  image: '🖼',
  video: '▶',
  audio: '♪',
  document: '📄',
}

function formatBytes(n: number | null): string {
  if (n == null) return ''
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / (1024 * 1024)).toFixed(1)} MB`
}

function itemIcon(item: LibraryItem): string {
  if (item.kind === 'link') return '🔗'
  return FILE_ICONS[item.file?.media_type ?? 'document'] ?? '📄'
}

function itemTypeLabel(item: LibraryItem): string {
  if (item.kind === 'link') return 'Link'
  const t = item.file?.media_type
  if (t === 'image') return 'Image'
  if (t === 'video') return 'Video'
  if (t === 'audio') return 'Audio'
  return 'Document'
}

// ---------------------------------------------------------------------------

export default function LibraryClient({ spaceSlug, initial }: Props) {
  const { show } = useToast()

  const [items, setItems] = useState<LibraryItem[]>(initial.items)
  const [folders, setFolders] = useState<LibraryFolder[]>(initial.folders)
  const [type, setType] = useState<TypeFilter>('any')
  // 'all' = every folder + uncategorised; 'none' = uncategorised only.
  const [activeFolder, setActiveFolder] = useState<string>('all')
  const [q, setQ] = useState<string>('')
  const [loading, setLoading] = useState<boolean>(false)
  const [uploadOpen, setUploadOpen] = useState(false)
  const [addLinkOpen, setAddLinkOpen] = useState(false)
  const [detailItem, setDetailItem] = useState<LibraryItem | null>(null)
  const [addFolderOpen, setAddFolderOpen] = useState(false)

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams()
      params.set('type', type)
      params.set('folder', activeFolder)
      if (q.trim()) params.set('q', q.trim())
      const res = await fetch(
        apiUrl(`/api/creator/spaces/${spaceSlug}/library?${params}`),
        { credentials: 'include', cache: 'no-store' },
      )
      if (res.ok) {
        const data: LibraryListResponse = await res.json()
        setItems(data.items)
        setFolders(data.folders)
      }
    } finally {
      setLoading(false)
    }
  }, [spaceSlug, type, activeFolder, q])

  useEffect(() => {
    void refresh()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [type, activeFolder])

  // Debounce search
  useEffect(() => {
    const t = setTimeout(() => { void refresh() }, 250)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q])

  // ── Folder CRUD ──────────────────────────────────────────────────

  async function handleCreateFolder(name: string) {
    const res = await fetch(
      apiUrl(`/api/creator/spaces/${spaceSlug}/library/folders`),
      {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      },
    )
    if (res.ok) {
      const folder: LibraryFolder = await res.json()
      setFolders((prev) => [...prev, folder])
      show(`Folder "${folder.name}" created.`, { tone: 'success' })
      setAddFolderOpen(false)
    } else {
      const body = await res.json().catch(() => ({}))
      show(
        typeof body.detail === 'string' ? body.detail : 'Could not create folder.',
        { tone: 'error' },
      )
    }
  }

  async function handleRenameFolder(folder: LibraryFolder) {
    const next = window.prompt('Rename folder', folder.name)?.trim()
    if (!next || next === folder.name) return
    const res = await fetch(
      apiUrl(`/api/creator/spaces/${spaceSlug}/library/folders/${folder.id}`),
      {
        method: 'PATCH',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: next }),
      },
    )
    if (res.ok) {
      const updated: LibraryFolder = await res.json()
      setFolders((prev) => prev.map((f) => (f.id === folder.id ? updated : f)))
    }
  }

  async function handleDeleteFolder(folder: LibraryFolder) {
    if (!window.confirm(
      `Delete "${folder.name}"?\n\nItems in this folder will move to "All items" — nothing is deleted with the folder.`,
    )) return
    const res = await fetch(
      apiUrl(`/api/creator/spaces/${spaceSlug}/library/folders/${folder.id}`),
      { method: 'DELETE', credentials: 'include' },
    )
    if (res.status === 204) {
      setFolders((prev) => prev.filter((f) => f.id !== folder.id))
      if (activeFolder === folder.id) setActiveFolder('all')
      void refresh()
    }
  }

  // ── Item detail modal — edit title/description/folder ─────────────

  function openDetail(item: LibraryItem) {
    setDetailItem(item)
  }

  async function saveDetail(edited: LibraryItem) {
    // Route by kind. Both endpoints already accept these fields; we
    // just target the right one.
    const path = edited.kind === 'file'
      ? `/api/creator/spaces/${spaceSlug}/media/${edited.id}`
      : `/api/creator/spaces/${spaceSlug}/resources/${edited.id}`
    const res = await fetch(apiUrl(path), {
      method: 'PATCH',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        title: edited.title,
        description: edited.description ?? '',
        folder_id: edited.folder_id,
      }),
    })
    if (res.ok) {
      show('Saved.', { tone: 'success' })
      setDetailItem(null)
      void refresh()
    } else {
      const body = await res.json().catch(() => ({}))
      show(
        typeof body.detail === 'string' ? body.detail : 'Could not save.',
        { tone: 'error' },
      )
    }
  }

  const emptyMessage = q.trim()
    ? 'No matches. Try a different search.'
    : type !== 'any'
      ? 'Nothing of that type yet.'
      : activeFolder === 'none'
        ? 'No uncategorised items — everything is in a folder.'
        : activeFolder !== 'all'
          ? 'This folder is empty. Move items here from "All items", or upload something new.'
          : 'Your Library is empty. Upload a file or add a link to get started.'

  return (
    <div className="grid gap-8 md:grid-cols-[220px_1fr]">
      {/* ── Folder rail ─────────────────────────────────────────── */}
      <aside>
        <div className="mb-3 flex items-center justify-between">
          <p className="text-[10.5px] font-semibold uppercase tracking-[0.16em]"
             style={{ color: 'rgba(12,24,38,0.55)' }}>
            Folders
          </p>
          <button
            type="button"
            className="text-[12px] font-medium text-teal-700 hover:underline"
            onClick={() => setAddFolderOpen(true)}
          >
            + New
          </button>
        </div>
        <ul className="space-y-0.5">
          <FolderRow
            label="All items"
            active={activeFolder === 'all'}
            onClick={() => setActiveFolder('all')}
          />
          <FolderRow
            label="Uncategorised"
            active={activeFolder === 'none'}
            onClick={() => setActiveFolder('none')}
            muted
          />
          {folders.length > 0 && (
            <li className="my-2 h-px w-full"
                style={{ background: 'rgba(12,24,38,0.10)' }} />
          )}
          {folders.map((f) => (
            <FolderRow
              key={f.id}
              label={f.name}
              itemCount={f.item_count}
              active={activeFolder === f.id}
              onClick={() => setActiveFolder(f.id)}
              onRename={() => void handleRenameFolder(f)}
              onDelete={() => void handleDeleteFolder(f)}
            />
          ))}
        </ul>
      </aside>

      {/* ── Content pane ───────────────────────────────────────── */}
      <section>
        <div className="mb-4 flex flex-wrap items-center gap-3">
          <Button onClick={() => setUploadOpen(true)} variant="primary">
            Upload
          </Button>
          <Button onClick={() => setAddLinkOpen(true)} variant="secondary">
            Add Link
          </Button>
        </div>

        {/* Type filter chips */}
        <div className="mb-3 flex flex-wrap gap-1.5">
          {TYPE_FILTERS.map((f) => (
            <button
              key={f.key}
              type="button"
              onClick={() => setType(f.key)}
              className="rounded-full px-3 py-1 text-[12.5px] font-medium transition-colors"
              style={
                type === f.key
                  ? { background: 'rgba(56,160,158,0.14)', color: '#0f766e' }
                  : { background: 'rgba(12,24,38,0.05)', color: 'rgba(12,24,38,0.72)' }
              }
            >
              {f.label}
            </button>
          ))}
        </div>

        <div className="mb-4">
          <SearchInput
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search Library…"
          />
        </div>

        {items.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-slate-300 bg-white p-8 text-center">
            <p className="text-[14px] text-black">{emptyMessage}</p>
          </div>
        ) : (
          <ul className="grid gap-2">
            {items.map((item) => (
              <li key={`${item.kind}-${item.id}`}>
                <button
                  type="button"
                  onClick={() => openDetail(item)}
                  className="flex w-full items-start gap-3 rounded-xl border border-slate-200 bg-white px-4 py-3 text-left transition-colors hover:border-teal-300"
                >
                  <span aria-hidden="true" className="mt-0.5 text-[18px]">
                    {itemIcon(item)}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="flex items-center gap-2">
                      <span className="truncate text-[14.5px] font-medium text-navy-900">
                        {item.title}
                      </span>
                      <span
                        className="shrink-0 rounded-full px-2 py-0.5 text-[10.5px] font-semibold uppercase tracking-wider"
                        style={{ background: 'rgba(12,24,38,0.06)', color: 'rgba(12,24,38,0.62)' }}
                      >
                        {itemTypeLabel(item)}
                      </span>
                      {item.used_in_count > 0 && (
                        <span
                          className="shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium"
                          style={{ background: 'rgba(56,160,158,0.10)', color: '#0f766e' }}
                        >
                          Used in {item.used_in_count}
                        </span>
                      )}
                    </span>
                    {item.description && (
                      <span className="mt-1 block truncate text-[12.5px] text-black">
                        {item.description}
                      </span>
                    )}
                    <span className="mt-1 block text-[11.5px]"
                          style={{ color: 'rgba(12,24,38,0.50)' }}>
                      {item.kind === 'file' && item.file
                        ? [item.file.original_filename, formatBytes(item.file.size_bytes)]
                            .filter(Boolean).join(' · ')
                        : item.link?.url}
                    </span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}

        {loading && (
          <p className="mt-4 text-center text-[12px]" style={{ color: 'rgba(12,24,38,0.55)' }}>
            Loading…
          </p>
        )}
      </section>

      {/* ── Upload modal ───────────────────────────────────────── */}
      {uploadOpen && (
        <UploadModal
          spaceSlug={spaceSlug}
          folders={folders}
          initialFolderId={activeFolder !== 'all' && activeFolder !== 'none' ? activeFolder : null}
          onClose={() => setUploadOpen(false)}
          onUploaded={() => { void refresh() }}
        />
      )}

      {/* ── Add Link modal ─────────────────────────────────────── */}
      {addLinkOpen && (
        <AddLinkModal
          spaceSlug={spaceSlug}
          folders={folders}
          initialFolderId={activeFolder !== 'all' && activeFolder !== 'none' ? activeFolder : null}
          onClose={() => setAddLinkOpen(false)}
          onAdded={() => { void refresh() }}
        />
      )}

      {/* ── Item detail modal ──────────────────────────────────── */}
      {detailItem && (
        <ItemDetailModal
          item={detailItem}
          folders={folders}
          onClose={() => setDetailItem(null)}
          onSave={saveDetail}
        />
      )}

      {/* ── New folder modal ───────────────────────────────────── */}
      {addFolderOpen && (
        <NewFolderModal
          onClose={() => setAddFolderOpen(false)}
          onCreate={handleCreateFolder}
        />
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------

function FolderRow({
  label, itemCount, active, muted, onClick, onRename, onDelete,
}: {
  label: string
  itemCount?: number
  active: boolean
  muted?: boolean
  onClick: () => void
  onRename?: () => void
  onDelete?: () => void
}) {
  return (
    <li className="group flex items-center">
      <button
        type="button"
        onClick={onClick}
        className="flex-1 rounded-md px-3 py-1.5 text-left text-[13.5px] transition-colors hover:bg-slate-100"
        style={
          active
            ? { background: 'rgba(56,160,158,0.10)', color: '#0f766e', fontWeight: 600 }
            : { color: muted ? 'rgba(12,24,38,0.55)' : '#0C1826' }
        }
      >
        {label}
        {typeof itemCount === 'number' && (
          <span className="ml-2 text-[11.5px]" style={{ color: 'rgba(12,24,38,0.45)' }}>
            {itemCount}
          </span>
        )}
      </button>
      {onRename && (
        <div className="ml-1 hidden gap-0.5 group-hover:flex">
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); onRename() }}
            className="rounded p-1 text-[11px] hover:bg-slate-200"
            title="Rename"
          >
            ✎
          </button>
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); onDelete?.() }}
            className="rounded p-1 text-[11px] hover:bg-slate-200"
            title="Delete"
          >
            ×
          </button>
        </div>
      )}
    </li>
  )
}

// ---------------------------------------------------------------------------
// Upload modal — POSTs to the existing /media endpoint. After the file
// is stored, an in-modal "details" step lets the creator adjust title,
// description, and folder before closing.

function UploadModal({
  spaceSlug, folders, initialFolderId, onClose, onUploaded,
}: {
  spaceSlug: string
  folders: LibraryFolder[]
  initialFolderId: string | null
  onClose: () => void
  onUploaded: () => void
}) {
  const { show } = useToast()
  const [file, setFile] = useState<File | null>(null)
  const [uploading, setUploading] = useState(false)
  const [uploaded, setUploaded] = useState<{ id: string; title: string } | null>(null)
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [folderId, setFolderId] = useState<string | ''>(initialFolderId ?? '')

  async function doUpload() {
    if (!file) return
    setUploading(true)
    try {
      const form = new FormData()
      form.append('file', file)
      const res = await fetch(
        apiUrl(`/api/creator/spaces/${spaceSlug}/media`),
        { method: 'POST', credentials: 'include', body: form },
      )
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        show(
          typeof body.detail === 'string' ? body.detail : 'Upload failed.',
          { tone: 'error' },
        )
        return
      }
      const asset = await res.json()
      setUploaded({ id: asset.id, title: asset.title })
      setTitle(asset.title)
      show('Uploaded.', { tone: 'success' })
      onUploaded()
    } finally {
      setUploading(false)
    }
  }

  async function saveDetails() {
    if (!uploaded) return
    const body: Record<string, unknown> = {
      title, description,
    }
    if (folderId) body.folder_id = folderId
    else body.folder_id = null
    const res = await fetch(
      apiUrl(`/api/creator/spaces/${spaceSlug}/media/${uploaded.id}`),
      {
        method: 'PATCH',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      },
    )
    if (res.ok) {
      onUploaded()
      onClose()
    } else {
      show('Could not save details.', { tone: 'error' })
    }
  }

  return (
    <Modal open onClose={onClose} title="Upload to Library">
      {!uploaded ? (
        <div className="space-y-4">
          <input
            type="file"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className="block w-full text-[13.5px]"
          />
          <div className="flex justify-end gap-2">
            <Button variant="tertiary" onClick={onClose}>Cancel</Button>
            <Button
              variant="primary"
              onClick={() => void doUpload()}
              disabled={!file || uploading}
            >
              {uploading ? 'Uploading…' : 'Upload'}
            </Button>
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          <p className="text-[13px] text-black">
            Uploaded — add optional details.
          </p>
          <FormField label="Title">
            <Input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
            />
          </FormField>
          <FormField label="Description">
            <TextArea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={3}
            />
          </FormField>
          <FormField label="Folder (optional)">
            <select
              value={folderId}
              onChange={(e) => setFolderId(e.target.value)}
              className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-[14px]"
            >
              <option value="">All items (no folder)</option>
              {folders.map((f) => (
                <option key={f.id} value={f.id}>{f.name}</option>
              ))}
            </select>
          </FormField>
          <div className="flex justify-end gap-2">
            <Button variant="tertiary" onClick={onClose}>Skip</Button>
            <Button variant="primary" onClick={() => void saveDetails()}>Save details</Button>
          </div>
        </div>
      )}
    </Modal>
  )
}

// ---------------------------------------------------------------------------
// Add Link modal — POSTs to the existing /resources endpoint with
// resource_type='link'.

function AddLinkModal({
  spaceSlug, folders, initialFolderId, onClose, onAdded,
}: {
  spaceSlug: string
  folders: LibraryFolder[]
  initialFolderId: string | null
  onClose: () => void
  onAdded: () => void
}) {
  const { show } = useToast()
  const [url, setUrl] = useState('')
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [folderId, setFolderId] = useState<string | ''>(initialFolderId ?? '')
  const [saving, setSaving] = useState(false)

  async function save() {
    if (!url.trim() || !title.trim()) return
    setSaving(true)
    try {
      const body: Record<string, unknown> = {
        title: title.trim(),
        description: description.trim() || null,
        resource_type: 'link',
        url: url.trim(),
        status: 'published',
      }
      if (folderId) body.folder_id = folderId
      const res = await fetch(
        apiUrl(`/api/creator/spaces/${spaceSlug}/resources`),
        {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        },
      )
      if (res.ok) {
        show('Link added.', { tone: 'success' })
        onAdded()
        onClose()
      } else {
        const b = await res.json().catch(() => ({}))
        show(
          typeof b.detail === 'string' ? b.detail : 'Could not add link.',
          { tone: 'error' },
        )
      }
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal open onClose={onClose} title="Add a link">
      <div className="space-y-4">
        <FormField label="URL">
          <Input
            type="url"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://…"
          />
        </FormField>
        <FormField label="Title">
          <Input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
        </FormField>
        <FormField label="Description (optional)">
          <TextArea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={2}
          />
        </FormField>
        <FormField label="Folder (optional)">
          <select
            value={folderId}
            onChange={(e) => setFolderId(e.target.value)}
            className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-[14px]"
          >
            <option value="">All items (no folder)</option>
            {folders.map((f) => (
              <option key={f.id} value={f.id}>{f.name}</option>
            ))}
          </select>
        </FormField>
        <div className="flex justify-end gap-2">
          <Button variant="tertiary" onClick={onClose}>Cancel</Button>
          <Button
            variant="primary"
            onClick={() => void save()}
            disabled={!url.trim() || !title.trim() || saving}
          >
            {saving ? 'Adding…' : 'Add link'}
          </Button>
        </div>
      </div>
    </Modal>
  )
}

// ---------------------------------------------------------------------------
// Item detail modal — edit title, description, folder. No file
// replacement in v1 — creators re-upload if the file itself needs to
// change.

function ItemDetailModal({
  item, folders, onClose, onSave,
}: {
  item: LibraryItem
  folders: LibraryFolder[]
  onClose: () => void
  onSave: (edited: LibraryItem) => Promise<void> | void
}) {
  const [title, setTitle] = useState(item.title)
  const [description, setDescription] = useState(item.description ?? '')
  const [folderId, setFolderId] = useState<string | ''>(item.folder_id ?? '')
  const [saving, setSaving] = useState(false)

  return (
    <Modal open onClose={onClose} title={item.title}>
      <div className="space-y-4">
        <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-[12.5px]"
             style={{ color: 'rgba(12,24,38,0.62)' }}>
          {item.kind === 'file' && item.file
            ? [
                item.file.original_filename,
                formatBytes(item.file.size_bytes),
                item.file.mime_type,
              ].filter(Boolean).join(' · ')
            : item.link?.url}
        </div>

        <FormField label="Title">
          <Input value={title} onChange={(e) => setTitle(e.target.value)} />
        </FormField>
        <FormField label="Description">
          <TextArea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={3}
          />
        </FormField>
        <FormField label="Folder">
          <select
            value={folderId}
            onChange={(e) => setFolderId(e.target.value)}
            className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-[14px]"
          >
            <option value="">All items (no folder)</option>
            {folders.map((f) => (
              <option key={f.id} value={f.id}>{f.name}</option>
            ))}
          </select>
        </FormField>

        {item.used_in_count > 0 && (
          <p className="text-[12px]" style={{ color: 'rgba(12,24,38,0.55)' }}>
            Used in {item.used_in_count} {item.used_in_count === 1 ? 'place' : 'places'}.
            Changes here flow through everywhere this item is embedded.
          </p>
        )}

        <div className="flex justify-end gap-2">
          <Button variant="tertiary" onClick={onClose}>Cancel</Button>
          <Button
            variant="primary"
            disabled={saving || !title.trim()}
            onClick={async () => {
              setSaving(true)
              try {
                await onSave({
                  ...item,
                  title,
                  description: description || null,
                  folder_id: folderId || null,
                })
              } finally {
                setSaving(false)
              }
            }}
          >
            {saving ? 'Saving…' : 'Save changes'}
          </Button>
        </div>
      </div>
    </Modal>
  )
}

// ---------------------------------------------------------------------------

function NewFolderModal({
  onClose, onCreate,
}: {
  onClose: () => void
  onCreate: (name: string) => Promise<void> | void
}) {
  const [name, setName] = useState('')
  const [saving, setSaving] = useState(false)
  return (
    <Modal open onClose={onClose} title="New folder">
      <div className="space-y-4">
        <FormField label="Folder name">
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Onboarding"
            autoFocus
          />
        </FormField>
        <div className="flex justify-end gap-2">
          <Button variant="tertiary" onClick={onClose}>Cancel</Button>
          <Button
            variant="primary"
            disabled={!name.trim() || saving}
            onClick={async () => {
              setSaving(true)
              try { await onCreate(name.trim()) } finally { setSaving(false) }
            }}
          >
            Create
          </Button>
        </div>
      </div>
    </Modal>
  )
}
