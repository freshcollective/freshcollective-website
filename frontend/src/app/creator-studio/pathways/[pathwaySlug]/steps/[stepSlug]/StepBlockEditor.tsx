'use client'

import { useState, useTransition, useRef, useEffect } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { apiUrl, resolveMediaUrl } from '@/lib/api'
import type { StepBlock, StepBlockType, CreatorMediaAsset } from '@/types/platform'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface CreatorPathwayMin {
  id: string
  slug: string
  title: string
}

interface CreatorStepMin {
  id: string
  slug: string
  title: string
  content_type: string
  content_body: string | null
}

interface Props {
  spaceSlug: string
  pathway: CreatorPathwayMin
  step: CreatorStepMin
  initialBlocks: StepBlock[]
  mediaAssets: CreatorMediaAsset[]
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const BLOCK_TYPE_OPTIONS: { value: StepBlockType; label: string; description: string }[] = [
  { value: 'heading', label: 'Heading', description: 'A section title' },
  { value: 'text', label: 'Text', description: 'Rich paragraph content' },
  { value: 'image', label: 'Image', description: 'From media library or URL' },
  { value: 'video_embed', label: 'Video', description: 'YouTube, Vimeo, or Loom' },
  { value: 'audio', label: 'Audio', description: 'From media library' },
  { value: 'file_download', label: 'File Download', description: 'Downloadable file from library' },
  { value: 'link', label: 'Link', description: 'An external link with label' },
  { value: 'reflection_prompt', label: 'Reflection Prompt', description: 'A question for the learner' },
  { value: 'exercise', label: 'Exercise', description: 'A structured activity' },
  { value: 'callout', label: 'Callout', description: 'Highlighted note or tip' },
  { value: 'divider', label: 'Divider', description: 'Visual separator' },
]

const CALLOUT_STYLES = ['info', 'tip', 'warning']

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function blockLabel(type: StepBlockType): string {
  return BLOCK_TYPE_OPTIONS.find(o => o.value === type)?.label ?? type
}

function calloutColor(style: string | null): string {
  if (style === 'warning') return 'rgba(234,179,8,0.12)'
  if (style === 'tip') return 'rgba(56,160,158,0.10)'
  return 'rgba(59,130,246,0.10)'
}

// ---------------------------------------------------------------------------
// Add Block Picker
// ---------------------------------------------------------------------------

function AddBlockPicker({ onSelect }: { onSelect: (type: StepBlockType) => void }) {
  const [open, setOpen] = useState(false)

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className="rounded-lg border border-dashed border-slate-300 px-4 py-2 text-[13px] font-medium text-slate-500 transition-colors hover:border-teal-400 hover:text-teal-700"
      >
        + Add block
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div
            className="absolute left-0 top-full z-20 mt-1 w-72 rounded-xl border border-slate-200 bg-white shadow-lg"
            style={{ maxHeight: '380px', overflowY: 'auto' }}
          >
            {BLOCK_TYPE_OPTIONS.map(opt => (
              <button
                key={opt.value}
                type="button"
                onClick={() => { onSelect(opt.value); setOpen(false) }}
                className="flex w-full flex-col px-4 py-3 text-left transition-colors hover:bg-slate-50"
              >
                <span className="text-[13px] font-semibold text-navy-900">{opt.label}</span>
                <span className="text-[11px] text-slate-400">{opt.description}</span>
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Media Picker
// ---------------------------------------------------------------------------

function MediaPicker({
  assets,
  value,
  onChange,
  accept,
}: {
  assets: CreatorMediaAsset[]
  value: string | null
  onChange: (id: string | null) => void
  accept?: ('image' | 'audio' | 'document' | 'other' | 'video')[]
}) {
  const filtered = accept ? assets.filter(a => accept.includes(a.media_type)) : assets
  const selected = filtered.find(a => a.id === value) ?? null

  return (
    <div>
      <label className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-slate-500">
        Media asset
      </label>
      <select
        value={value ?? ''}
        onChange={e => onChange(e.target.value || null)}
        className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[13px] text-navy-900"
      >
        <option value="">— None selected —</option>
        {filtered.map(a => (
          <option key={a.id} value={a.id}>{a.title} ({a.original_filename})</option>
        ))}
      </select>
      {selected && (
        <p className="mt-1 text-[11px] text-slate-400">
          {selected.media_type} · {selected.mime_type}
        </p>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Block Edit Form (per type)
// ---------------------------------------------------------------------------

function BlockEditForm({
  block,
  assets,
  onSave,
  onCancel,
  saving,
}: {
  block: StepBlock
  assets: CreatorMediaAsset[]
  onSave: (patch: Partial<StepBlock>) => void
  onCancel: () => void
  saving: boolean
}) {
  const [content, setContent] = useState(block.content ?? '')
  const [label, setLabel] = useState(block.label ?? '')
  const [caption, setCaption] = useState(block.caption ?? '')
  const [embedUrl, setEmbedUrl] = useState(block.embed_url ?? '')
  const [mediaAssetId, setMediaAssetId] = useState<string | null>(block.media_asset_id)

  function handleSave() {
    onSave({
      content: content || null,
      label: label || null,
      caption: caption || null,
      embed_url: embedUrl || null,
      media_asset_id: mediaAssetId,
    })
  }

  const t = block.block_type

  return (
    <div className="mt-3 space-y-3 rounded-lg border border-teal-100 bg-teal-50/40 p-4">

      {/* heading */}
      {t === 'heading' && (
        <div>
          <label className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-slate-500">Heading text</label>
          <input
            value={content}
            onChange={e => setContent(e.target.value)}
            className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[13px] font-semibold text-navy-900"
            placeholder="Section heading…"
          />
        </div>
      )}

      {/* text */}
      {t === 'text' && (
        <div>
          <label className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-slate-500">Content (Markdown supported)</label>
          <textarea
            value={content}
            onChange={e => setContent(e.target.value)}
            rows={6}
            className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[13px] text-navy-900"
            placeholder="Write your content…"
          />
        </div>
      )}

      {/* image */}
      {t === 'image' && (
        <>
          <MediaPicker assets={assets} value={mediaAssetId} onChange={setMediaAssetId} accept={['image']} />
          <div>
            <label className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-slate-500">Or external image URL</label>
            <input
              value={embedUrl}
              onChange={e => setEmbedUrl(e.target.value)}
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[13px] text-navy-900"
              placeholder="https://…"
            />
          </div>
          <div>
            <label className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-slate-500">Caption (optional)</label>
            <input
              value={caption}
              onChange={e => setCaption(e.target.value)}
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[13px] text-navy-900"
              placeholder="Image description…"
            />
          </div>
        </>
      )}

      {/* video_embed */}
      {t === 'video_embed' && (
        <>
          <div>
            <label className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-slate-500">Video URL (YouTube, Vimeo, Loom)</label>
            <input
              value={embedUrl}
              onChange={e => setEmbedUrl(e.target.value)}
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[13px] text-navy-900"
              placeholder="https://youtube.com/watch?v=…"
            />
          </div>
          <div>
            <label className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-slate-500">Caption (optional)</label>
            <input
              value={caption}
              onChange={e => setCaption(e.target.value)}
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[13px] text-navy-900"
              placeholder="Video description…"
            />
          </div>
        </>
      )}

      {/* audio */}
      {t === 'audio' && (
        <>
          <MediaPicker assets={assets} value={mediaAssetId} onChange={setMediaAssetId} accept={['audio']} />
          <div>
            <label className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-slate-500">Caption (optional)</label>
            <input
              value={caption}
              onChange={e => setCaption(e.target.value)}
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[13px] text-navy-900"
              placeholder="Audio description…"
            />
          </div>
        </>
      )}

      {/* file_download */}
      {t === 'file_download' && (
        <>
          <MediaPicker assets={assets} value={mediaAssetId} onChange={setMediaAssetId} accept={['document', 'other', 'audio', 'image']} />
          <div>
            <label className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-slate-500">Button label (optional)</label>
            <input
              value={label}
              onChange={e => setLabel(e.target.value)}
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[13px] text-navy-900"
              placeholder="Download workbook"
            />
          </div>
        </>
      )}

      {/* link */}
      {t === 'link' && (
        <>
          <div>
            <label className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-slate-500">URL</label>
            <input
              value={embedUrl}
              onChange={e => setEmbedUrl(e.target.value)}
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[13px] text-navy-900"
              placeholder="https://…"
            />
          </div>
          <div>
            <label className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-slate-500">Link label</label>
            <input
              value={label}
              onChange={e => setLabel(e.target.value)}
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[13px] text-navy-900"
              placeholder="Visit resource"
            />
          </div>
          <div>
            <label className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-slate-500">Description (optional)</label>
            <input
              value={caption}
              onChange={e => setCaption(e.target.value)}
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[13px] text-navy-900"
              placeholder="Short description of the link…"
            />
          </div>
        </>
      )}

      {/* reflection_prompt */}
      {t === 'reflection_prompt' && (
        <div>
          <label className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-slate-500">Reflection question</label>
          <textarea
            value={content}
            onChange={e => setContent(e.target.value)}
            rows={3}
            className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[13px] text-navy-900"
            placeholder="What did you notice about…"
          />
        </div>
      )}

      {/* exercise */}
      {t === 'exercise' && (
        <div>
          <label className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-slate-500">Exercise instructions</label>
          <textarea
            value={content}
            onChange={e => setContent(e.target.value)}
            rows={5}
            className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[13px] text-navy-900"
            placeholder="Step-by-step instructions…"
          />
        </div>
      )}

      {/* callout */}
      {t === 'callout' && (
        <>
          <div>
            <label className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-slate-500">Style</label>
            <select
              value={label || 'info'}
              onChange={e => setLabel(e.target.value)}
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[13px] text-navy-900"
            >
              {CALLOUT_STYLES.map(s => (
                <option key={s} value={s}>{s.charAt(0).toUpperCase() + s.slice(1)}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-slate-500">Callout text</label>
            <textarea
              value={content}
              onChange={e => setContent(e.target.value)}
              rows={3}
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[13px] text-navy-900"
              placeholder="Important note…"
            />
          </div>
        </>
      )}

      {/* divider — no fields */}
      {t === 'divider' && (
        <p className="text-[13px] text-slate-400 italic">Divider block — no content to edit.</p>
      )}

      <div className="flex gap-2 pt-1">
        <button
          type="button"
          onClick={handleSave}
          disabled={saving}
          className="rounded-lg px-4 py-2 text-[13px] font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-50"
          style={{ background: '#38A09E' }}
        >
          {saving ? 'Saving…' : 'Save'}
        </button>
        <button
          type="button"
          onClick={onCancel}
          disabled={saving}
          className="rounded-lg border border-slate-200 px-4 py-2 text-[13px] font-medium text-slate-600 transition-colors hover:bg-slate-50"
        >
          Cancel
        </button>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Block Preview (collapsed view)
// ---------------------------------------------------------------------------

function BlockPreview({ block }: { block: StepBlock }) {
  const t = block.block_type

  if (t === 'divider') return <hr className="border-slate-200" />

  if (t === 'heading') return (
    <p className="text-[18px] font-bold text-navy-900">{block.content || <span className="italic text-slate-300">No heading text</span>}</p>
  )

  if (t === 'text') return (
    <p className="whitespace-pre-wrap text-[14px] leading-relaxed text-slate-700">
      {block.content ? block.content.slice(0, 200) + (block.content.length > 200 ? '…' : '') : <span className="italic text-slate-300">No content</span>}
    </p>
  )

  if (t === 'image') return (
    <div className="flex items-center gap-3">
      {block.media_asset ? (
        <p className="text-[13px] text-slate-600">📷 {block.media_asset.title}</p>
      ) : block.embed_url ? (
        <p className="text-[13px] text-slate-600">📷 External: {block.embed_url.slice(0, 60)}…</p>
      ) : (
        <p className="text-[13px] italic text-slate-300">No image selected</p>
      )}
      {block.caption && <span className="text-[11px] text-slate-400">· {block.caption}</span>}
    </div>
  )

  if (t === 'video_embed') return (
    <p className="text-[13px] text-slate-600">
      🎬 {block.embed_url ? block.embed_url : <span className="italic text-slate-300">No URL set</span>}
      {block.caption && ` · ${block.caption}`}
    </p>
  )

  if (t === 'audio') return (
    <p className="text-[13px] text-slate-600">
      🔊 {block.media_asset ? block.media_asset.title : <span className="italic text-slate-300">No audio selected</span>}
    </p>
  )

  if (t === 'file_download') return (
    <p className="text-[13px] text-slate-600">
      📎 {block.media_asset ? block.media_asset.title : <span className="italic text-slate-300">No file selected</span>}
      {block.label && ` · "${block.label}"`}
    </p>
  )

  if (t === 'link') return (
    <p className="text-[13px] text-slate-600">
      🔗 {block.label || 'Link'}{block.embed_url ? ` → ${block.embed_url.slice(0, 50)}` : <span className="italic text-slate-300"> (no URL)</span>}
    </p>
  )

  if (t === 'reflection_prompt') return (
    <p className="text-[13px] italic text-slate-600">
      💬 {block.content ? `"${block.content.slice(0, 120)}…"` : <span className="not-italic text-slate-300">No prompt text</span>}
    </p>
  )

  if (t === 'exercise') return (
    <p className="text-[13px] text-slate-600">
      ✏️ {block.content ? block.content.slice(0, 120) : <span className="italic text-slate-300">No instructions</span>}
    </p>
  )

  if (t === 'callout') return (
    <div
      className="rounded-lg p-3"
      style={{ background: calloutColor(block.label) }}
    >
      <p className="text-[13px] text-slate-700">
        {block.content || <span className="italic text-slate-300">No callout text</span>}
      </p>
    </div>
  )

  return null
}

// ---------------------------------------------------------------------------
// Block Row
// ---------------------------------------------------------------------------

function BlockRow({
  block,
  index,
  total,
  assets,
  onMoveUp,
  onMoveDown,
  onDelete,
  onUpdate,
}: {
  block: StepBlock
  index: number
  total: number
  assets: CreatorMediaAsset[]
  onMoveUp: () => void
  onMoveDown: () => void
  onDelete: () => void
  onUpdate: (patch: Partial<StepBlock>) => Promise<void>
}) {
  const [editing, setEditing] = useState(false)
  const [saving, setSaving] = useState(false)

  async function handleSave(patch: Partial<StepBlock>) {
    setSaving(true)
    await onUpdate(patch)
    setSaving(false)
    setEditing(false)
  }

  return (
    <div className="rounded-xl border border-slate-200 bg-white">
      <div className="flex items-start gap-3 p-4">
        {/* move controls */}
        <div className="flex flex-col gap-0.5 pt-0.5">
          <button
            type="button"
            onClick={onMoveUp}
            disabled={index === 0}
            className="flex h-5 w-5 items-center justify-center rounded text-slate-300 transition-colors hover:bg-slate-100 hover:text-slate-500 disabled:opacity-20"
            title="Move up"
          >
            ↑
          </button>
          <button
            type="button"
            onClick={onMoveDown}
            disabled={index === total - 1}
            className="flex h-5 w-5 items-center justify-center rounded text-slate-300 transition-colors hover:bg-slate-100 hover:text-slate-500 disabled:opacity-20"
            title="Move down"
          >
            ↓
          </button>
        </div>

        {/* content */}
        <div className="min-w-0 flex-1">
          <div className="mb-2 flex items-center gap-2">
            <span
              className="rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide"
              style={{ background: 'rgba(56,160,158,0.10)', color: '#38A09E' }}
            >
              {blockLabel(block.block_type)}
            </span>
          </div>
          <BlockPreview block={block} />
          {editing && (
            <BlockEditForm
              block={block}
              assets={assets}
              onSave={handleSave}
              onCancel={() => setEditing(false)}
              saving={saving}
            />
          )}
        </div>

        {/* actions */}
        <div className="flex shrink-0 items-center gap-2">
          {!editing && (
            <button
              type="button"
              onClick={() => setEditing(true)}
              className="rounded-lg border border-slate-200 px-3 py-1.5 text-[12px] font-medium text-slate-600 transition-colors hover:bg-slate-50"
            >
              Edit
            </button>
          )}
          <button
            type="button"
            onClick={onDelete}
            className="rounded-lg border border-red-100 px-3 py-1.5 text-[12px] font-medium text-red-400 transition-colors hover:bg-red-50 hover:text-red-600"
          >
            Delete
          </button>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main Editor
// ---------------------------------------------------------------------------

export default function StepBlockEditor({ spaceSlug, pathway, step, initialBlocks, mediaAssets }: Props) {
  const router = useRouter()
  const [, startTransition] = useTransition()
  const [blocks, setBlocks] = useState<StepBlock[]>(initialBlocks)
  const [adding, setAdding] = useState(false)

  const baseUrl = apiUrl(`/api/creator/spaces/${spaceSlug}/pathways/${pathway.slug}/steps/${step.slug}/blocks`)

  async function addBlock(type: StepBlockType) {
    setAdding(true)
    try {
      const res = await fetch(baseUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ block_type: type }),
        credentials: 'include',
      })
      if (!res.ok) return
      const block: StepBlock = await res.json()
      setBlocks(prev => [...prev, block])
    } finally {
      setAdding(false)
    }
  }

  async function updateBlock(blockId: string, patch: Partial<StepBlock>) {
    const res = await fetch(`${baseUrl}/${blockId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
      credentials: 'include',
    })
    if (!res.ok) return
    const updated: StepBlock = await res.json()
    setBlocks(prev => prev.map(b => b.id === blockId ? updated : b))
  }

  async function deleteBlock(blockId: string) {
    if (!confirm('Delete this block?')) return
    await fetch(`${baseUrl}/${blockId}`, { method: 'DELETE', credentials: 'include' })
    setBlocks(prev => prev.filter(b => b.id !== blockId))
  }

  async function moveBlock(index: number, direction: 'up' | 'down') {
    const newBlocks = [...blocks]
    const swapIdx = direction === 'up' ? index - 1 : index + 1
    if (swapIdx < 0 || swapIdx >= newBlocks.length) return
    ;[newBlocks[index], newBlocks[swapIdx]] = [newBlocks[swapIdx], newBlocks[index]]
    setBlocks(newBlocks)

    await fetch(`${baseUrl}/reorder`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids: newBlocks.map(b => b.id) }),
      credentials: 'include',
    })
    startTransition(() => router.refresh())
  }

  return (
    <div className="max-w-3xl px-8 py-8 md:px-10 md:py-10">

      {/* Header */}
      <div className="mb-6">
        <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.16em]" style={{ color: '#38A09E' }}>
          Creator Studio · {pathway.title}
        </p>
        <div className="flex items-start justify-between gap-4">
          <h1 className="text-2xl text-navy-900 md:text-3xl">{step.title}</h1>
          <Link
            href={`/creator-studio/pathways/${pathway.slug}`}
            className="shrink-0 text-[13px] font-medium text-slate-400 transition-colors hover:text-slate-600"
          >
            ← Back to pathway
          </Link>
        </div>
      </div>

      {/* Blocks */}
      <div className="space-y-3">
        {blocks.length === 0 && (
          <div className="rounded-2xl border border-dashed border-slate-200 bg-white p-8 text-center">
            <p className="mb-1 text-[14px] font-semibold text-navy-900">No content blocks yet</p>
            <p className="text-[13px] text-slate-400">Add your first block below to start building this step.</p>
          </div>
        )}

        {blocks.map((block, i) => (
          <BlockRow
            key={block.id}
            block={block}
            index={i}
            total={blocks.length}
            assets={mediaAssets}
            onMoveUp={() => moveBlock(i, 'up')}
            onMoveDown={() => moveBlock(i, 'down')}
            onDelete={() => deleteBlock(block.id)}
            onUpdate={(patch) => updateBlock(block.id, patch)}
          />
        ))}
      </div>

      {/* Add block */}
      <div className="mt-4">
        {adding ? (
          <p className="text-[13px] text-slate-400">Adding block…</p>
        ) : (
          <AddBlockPicker onSelect={addBlock} />
        )}
      </div>

    </div>
  )
}
