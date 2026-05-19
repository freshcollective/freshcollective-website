'use client'

/**
 * Shared sub-components for block-based content editors.
 * Used by both StepBlockEditor (pathway step content) and
 * AboutPageEditor (pathway about/sales page content).
 */

import { useState } from 'react'
import Link from 'next/link'
import RichTextEditor from '@/components/creator/RichTextEditor'
import RichTextRenderer from '@/components/RichTextRenderer'
import type { EditorBlock, StepBlockType, CreatorMediaAsset } from '@/types/platform'

// ---------------------------------------------------------------------------
// Constants & utilities (exported for use in editor files)
// ---------------------------------------------------------------------------

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

export const BLOCK_TYPE_OPTIONS: { value: StepBlockType; label: string; icon: string; description: string }[] = [
  { value: 'heading',           icon: 'H',  label: 'Heading',           description: 'Section title' },
  { value: 'text',              icon: '¶',  label: 'Text',              description: 'Rich paragraph content' },
  { value: 'image',             icon: '🖼', label: 'Image',             description: 'From Media Library' },
  { value: 'video_embed',       icon: '▶',  label: 'Video embed',       description: 'YouTube, Vimeo, or Loom' },
  { value: 'audio',             icon: '🔊', label: 'Audio',             description: 'From Media Library' },
  { value: 'file_download',     icon: '↓',  label: 'File download',     description: 'Downloadable file' },
  { value: 'link',              icon: '🔗', label: 'Link',              description: 'External link card' },
  { value: 'reflection_prompt', icon: '💬', label: 'Reflection prompt', description: 'Question for the reader' },
  { value: 'exercise',          icon: '✏', label: 'Exercise',           description: 'Structured activity' },
  { value: 'callout',           icon: '!',  label: 'Callout',           description: 'Highlighted note or tip' },
  { value: 'divider',           icon: '—',  label: 'Divider',           description: 'Visual separator' },
]

export const CALLOUT_STYLES = [
  { value: 'info',    label: 'Info',    color: 'rgba(59,130,246,0.09)',  accent: '#1d4ed8' },
  { value: 'tip',     label: 'Tip',     color: 'rgba(56,160,158,0.09)', accent: '#0f766e' },
  { value: 'warning', label: 'Warning', color: 'rgba(234,179,8,0.11)',  accent: '#92400e' },
]

export function blockLabel(type: StepBlockType): string {
  return BLOCK_TYPE_OPTIONS.find(o => o.value === type)?.label ?? type
}

export function blockIcon(type: StepBlockType): string {
  return BLOCK_TYPE_OPTIONS.find(o => o.value === type)?.icon ?? '·'
}

export function resolveAssetUrl(url: string): string {
  return url.startsWith('http') ? url : `${API_BASE}/api/uploads/${url}`
}

export function getEmbedUrl(raw: string): string | null {
  if (!raw) return null
  try {
    const url = new URL(raw)
    if (url.hostname.includes('youtube.com')) {
      const id = url.searchParams.get('v')
      return id ? `https://www.youtube.com/embed/${id}` : null
    }
    if (url.hostname.includes('youtu.be')) {
      const id = url.pathname.slice(1)
      return id ? `https://www.youtube.com/embed/${id}` : null
    }
    if (url.hostname.includes('vimeo.com')) {
      const id = url.pathname.split('/').filter(Boolean).pop()
      return id ? `https://player.vimeo.com/video/${id}` : null
    }
    if (url.hostname.includes('loom.com') && url.pathname.includes('/share/')) {
      const id = url.pathname.split('/share/')[1]?.split('?')[0]
      return id ? `https://www.loom.com/embed/${id}` : null
    }
  } catch {}
  return null
}

// ---------------------------------------------------------------------------
// AddBlockPicker
// ---------------------------------------------------------------------------

export function AddBlockPicker({ onSelect }: { onSelect: (type: StepBlockType) => void }) {
  const [open, setOpen] = useState(false)

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className="flex items-center gap-2 rounded-lg border border-dashed border-slate-300 px-4 py-2.5 text-[13px] font-medium text-slate-500 transition-colors hover:border-teal-400 hover:text-teal-700"
      >
        <span className="text-[16px] leading-none">+</span>
        Add block
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute left-0 top-full z-20 mt-1.5 w-72 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-xl">
            <p className="border-b border-slate-100 px-4 py-2 text-[10px] font-bold uppercase tracking-widest text-slate-400">
              Add content block
            </p>
            <div style={{ maxHeight: 360, overflowY: 'auto' }}>
              {BLOCK_TYPE_OPTIONS.map(opt => (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => { onSelect(opt.value); setOpen(false) }}
                  className="flex w-full items-start gap-3 px-4 py-3 text-left transition-colors hover:bg-slate-50"
                >
                  <span
                    className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-[13px]"
                    style={{ background: 'rgba(56,160,158,0.10)', color: '#38A09E' }}
                  >
                    {opt.icon}
                  </span>
                  <div>
                    <p className="text-[13px] font-semibold text-navy-900">{opt.label}</p>
                    <p className="text-[11px] text-slate-400">{opt.description}</p>
                  </div>
                </button>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// MediaPicker
// ---------------------------------------------------------------------------

export function MediaPicker({
  assets,
  value,
  onChange,
  accept,
  emptyMessage,
}: {
  assets: CreatorMediaAsset[]
  value: string | null
  onChange: (id: string | null) => void
  accept?: CreatorMediaAsset['media_type'][]
  emptyMessage?: string
}) {
  const filtered = accept
    ? assets.filter(a => accept.includes(a.media_type) && a.status === 'active')
    : assets.filter(a => a.status === 'active')
  const selected = filtered.find(a => a.id === value) ?? null

  if (filtered.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-slate-200 p-3 text-center">
        <p className="text-[12px] text-slate-400">{emptyMessage ?? 'No assets available.'}</p>
        <Link href="/creator-studio/media" className="mt-1 block text-[12px] font-medium text-teal-600 hover:underline">
          Open Media Library →
        </Link>
      </div>
    )
  }

  return (
    <div>
      <select
        value={value ?? ''}
        onChange={e => onChange(e.target.value || null)}
        className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[13px] text-navy-900 focus:outline-none focus:ring-1 focus:ring-teal-300"
      >
        <option value="">— Select from Media Library —</option>
        {filtered.map(a => (
          <option key={a.id} value={a.id}>{a.title} · {a.original_filename}</option>
        ))}
      </select>

      {selected && (
        <div className="mt-2 flex items-center gap-3 rounded-lg border border-slate-100 bg-slate-50 p-2">
          {selected.media_type === 'image' && (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={resolveAssetUrl(selected.file_url)}
              alt={selected.title}
              className="h-14 w-14 rounded object-cover"
            />
          )}
          <div className="min-w-0">
            <p className="truncate text-[12px] font-medium text-navy-900">{selected.title}</p>
            <p className="text-[11px] text-slate-400">{selected.original_filename} · {selected.media_type}</p>
          </div>
          <button
            type="button"
            onClick={() => onChange(null)}
            className="ml-auto shrink-0 text-[11px] text-slate-400 hover:text-red-400"
          >
            ✕
          </button>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// BlockPreview (collapsed card view)
// ---------------------------------------------------------------------------

export function BlockPreview({ block, assets }: { block: EditorBlock; assets: CreatorMediaAsset[] }) {
  const asset = block.media_asset_id
    ? assets.find(a => a.id === block.media_asset_id) ?? block.media_asset
    : block.media_asset
  const t = block.block_type

  if (t === 'divider') return <hr className="border-slate-200" />

  if (t === 'heading') return (
    <p className="text-[16px] font-bold text-navy-900">
      {block.content || <span className="italic text-slate-300">No heading text</span>}
    </p>
  )

  if (t === 'text') return (
    <div className="line-clamp-3 text-[14px] text-slate-600">
      <RichTextRenderer content={block.content} />
    </div>
  )

  if (t === 'image') {
    const imgSrc = asset ? resolveAssetUrl(asset.file_url) : block.embed_url
    return (
      <div className="flex items-center gap-3">
        {imgSrc ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={imgSrc} alt={block.caption ?? ''} className="h-16 w-20 rounded object-cover" />
        ) : (
          <div className="flex h-16 w-20 items-center justify-center rounded bg-slate-100 text-slate-400">🖼</div>
        )}
        <div>
          {asset && <p className="text-[13px] font-medium text-navy-900">{asset.title}</p>}
          {block.caption && <p className="text-[12px] text-slate-400">{block.caption}</p>}
          {!asset && !imgSrc && <p className="text-[13px] italic text-slate-300">No image selected</p>}
        </div>
      </div>
    )
  }

  if (t === 'video_embed') {
    const embed = block.embed_url ? getEmbedUrl(block.embed_url) : null
    return (
      <div className="flex items-center gap-2 text-[13px] text-slate-600">
        <span>▶</span>
        {block.embed_url
          ? embed
            ? <span className="text-teal-700">{block.embed_url}</span>
            : <span className="text-slate-400">{block.embed_url}</span>
          : <span className="italic text-slate-300">No URL set</span>
        }
      </div>
    )
  }

  if (t === 'audio') return (
    <div className="flex items-center gap-2 text-[13px]">
      <span>🔊</span>
      {asset
        ? <span className="font-medium text-navy-900">{asset.title}</span>
        : <span className="italic text-slate-300">No audio selected</span>
      }
    </div>
  )

  if (t === 'file_download') return (
    <div className="flex items-center gap-2 text-[13px]">
      <span>↓</span>
      {asset
        ? <><span className="font-medium text-navy-900">{asset.title}</span>{block.label && <span className="text-slate-400">· "{block.label}"</span>}</>
        : <span className="italic text-slate-300">No file selected</span>
      }
    </div>
  )

  if (t === 'link') return (
    <div className="flex items-center gap-2 text-[13px]">
      <span>🔗</span>
      <span className="font-medium text-navy-900">{block.label || 'Link'}</span>
      {block.embed_url
        ? <span className="max-w-[200px] truncate text-slate-400">→ {block.embed_url}</span>
        : <span className="italic text-slate-300">(no URL)</span>
      }
    </div>
  )

  if (t === 'reflection_prompt') return (
    <div className="text-[13px] italic text-slate-600">
      <span className="mr-1 not-italic">💬</span>
      <RichTextRenderer content={block.content} />
    </div>
  )

  if (t === 'exercise') return (
    <div className="text-[13px] text-slate-600">
      <span className="mr-1">✏</span>
      <RichTextRenderer content={block.content} />
    </div>
  )

  if (t === 'callout') {
    const style = CALLOUT_STYLES.find(s => s.value === (block.label ?? 'info')) ?? CALLOUT_STYLES[0]
    return (
      <div className="rounded-lg px-4 py-2.5" style={{ background: style.color }}>
        <p className="mb-0.5 text-[10px] font-bold uppercase tracking-widest" style={{ color: style.accent }}>{style.label}</p>
        <div className="line-clamp-2 text-[13px] text-slate-700">
          <RichTextRenderer content={block.content} />
        </div>
      </div>
    )
  }

  return null
}

// ---------------------------------------------------------------------------
// BlockEditForm
// ---------------------------------------------------------------------------

export function BlockEditForm({
  block,
  assets,
  onSave,
  onCancel,
  saving,
}: {
  block: EditorBlock
  assets: CreatorMediaAsset[]
  onSave: (patch: Record<string, unknown>) => void
  onCancel: () => void
  saving: boolean
}) {
  const [content, setContent] = useState(block.content ?? '')
  const [label, setLabel] = useState(block.label ?? '')
  const [caption, setCaption] = useState(block.caption ?? '')
  const [embedUrl, setEmbedUrl] = useState(block.embed_url ?? '')
  const [mediaAssetId, setMediaAssetId] = useState<string | null>(block.media_asset_id)

  const t = block.block_type
  const embedPreview = t === 'video_embed' && embedUrl ? getEmbedUrl(embedUrl) : null

  function handleSave() {
    onSave({
      content: content || null,
      label: label || null,
      caption: caption || null,
      embed_url: embedUrl || null,
      media_asset_id: mediaAssetId,
    })
  }

  return (
    <div className="mt-3 space-y-4 rounded-xl border border-teal-100 bg-teal-50/30 p-4">

      {t === 'heading' && (
        <>
          <div>
            <label className="field-label">Heading text</label>
            <input
              value={content}
              onChange={e => setContent(e.target.value)}
              className="field-input text-[18px] font-bold"
              placeholder="Section heading…"
              autoFocus
            />
          </div>
          <div>
            <label className="field-label">Heading level</label>
            <div className="flex gap-2">
              {['H1', 'H2', 'H3'].map((h, idx) => (
                <button
                  key={h}
                  type="button"
                  onClick={() => setLabel(`h${idx + 1}`)}
                  className={`rounded-lg border px-3 py-1.5 text-[12px] font-semibold transition-colors ${label === `h${idx + 1}` || (!label && idx === 1) ? 'border-teal-500 bg-teal-50 text-teal-700' : 'border-slate-200 text-slate-500 hover:border-teal-300'}`}
                >
                  {h}
                </button>
              ))}
            </div>
          </div>
        </>
      )}

      {t === 'text' && (
        <div>
          <label className="field-label">Content</label>
          <RichTextEditor
            content={content}
            onChange={setContent}
            placeholder="Write your content… Bold, italic, lists, links all supported."
            minRows={6}
          />
        </div>
      )}

      {t === 'image' && (
        <>
          <div>
            <label className="field-label">Image from Media Library</label>
            <MediaPicker
              assets={assets}
              value={mediaAssetId}
              onChange={setMediaAssetId}
              accept={['image']}
              emptyMessage="No images in this collective's Media Library yet."
            />
          </div>
          <div>
            <label className="field-label">Or external image URL</label>
            <input
              value={embedUrl}
              onChange={e => setEmbedUrl(e.target.value)}
              className="field-input"
              placeholder="https://…"
            />
          </div>
          <div>
            <label className="field-label">Caption (optional)</label>
            <input value={caption} onChange={e => setCaption(e.target.value)} className="field-input" placeholder="Describe the image…" />
          </div>
        </>
      )}

      {t === 'video_embed' && (
        <>
          <div>
            <label className="field-label">Video URL — YouTube, Vimeo, or Loom</label>
            <input
              value={embedUrl}
              onChange={e => setEmbedUrl(e.target.value)}
              className="field-input"
              placeholder="https://youtube.com/watch?v=… or https://vimeo.com/…"
              autoFocus
            />
            {embedUrl && !embedPreview && (
              <p className="mt-1 text-[11px] text-amber-600">URL not recognised as YouTube, Vimeo, or Loom — will render as a link card for members.</p>
            )}
          </div>
          {embedPreview && (
            <div className="overflow-hidden rounded-lg bg-black" style={{ aspectRatio: '16/9' }}>
              <iframe
                src={embedPreview}
                className="h-full w-full"
                allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                allowFullScreen
              />
            </div>
          )}
          <div>
            <label className="field-label">Caption (optional)</label>
            <input value={caption} onChange={e => setCaption(e.target.value)} className="field-input" placeholder="Video description…" />
          </div>
        </>
      )}

      {t === 'audio' && (
        <>
          <div>
            <label className="field-label">Audio from Media Library</label>
            <MediaPicker
              assets={assets}
              value={mediaAssetId}
              onChange={setMediaAssetId}
              accept={['audio']}
              emptyMessage="No audio files in this collective's Media Library yet."
            />
          </div>
          {mediaAssetId && assets.find(a => a.id === mediaAssetId) && (
            <audio controls className="w-full" src={resolveAssetUrl(assets.find(a => a.id === mediaAssetId)!.file_url)} />
          )}
          <div>
            <label className="field-label">Caption (optional)</label>
            <input value={caption} onChange={e => setCaption(e.target.value)} className="field-input" placeholder="Audio description…" />
          </div>
        </>
      )}

      {t === 'file_download' && (
        <>
          <div>
            <label className="field-label">File from Media Library</label>
            <MediaPicker
              assets={assets}
              value={mediaAssetId}
              onChange={setMediaAssetId}
              accept={['document', 'other', 'audio', 'image']}
              emptyMessage="No files in this collective's Media Library yet."
            />
          </div>
          <div>
            <label className="field-label">Button label (optional)</label>
            <input value={label} onChange={e => setLabel(e.target.value)} className="field-input" placeholder="Download workbook" />
          </div>
        </>
      )}

      {t === 'link' && (
        <>
          <div>
            <label className="field-label">URL</label>
            <input value={embedUrl} onChange={e => setEmbedUrl(e.target.value)} className="field-input" placeholder="https://…" autoFocus />
          </div>
          <div>
            <label className="field-label">Link label</label>
            <input value={label} onChange={e => setLabel(e.target.value)} className="field-input" placeholder="Visit resource" />
          </div>
          <div>
            <label className="field-label">Description (optional)</label>
            <input value={caption} onChange={e => setCaption(e.target.value)} className="field-input" placeholder="Short description…" />
          </div>
        </>
      )}

      {t === 'reflection_prompt' && (
        <div>
          <label className="field-label">Reflection question</label>
          <RichTextEditor
            content={content}
            onChange={setContent}
            placeholder="What did you notice about…"
            minRows={3}
          />
        </div>
      )}

      {t === 'exercise' && (
        <div>
          <label className="field-label">Exercise instructions</label>
          <RichTextEditor
            content={content}
            onChange={setContent}
            placeholder="Step-by-step instructions…"
            minRows={5}
          />
        </div>
      )}

      {t === 'callout' && (
        <>
          <div>
            <label className="field-label">Style</label>
            <div className="flex gap-2">
              {CALLOUT_STYLES.map(s => (
                <button
                  key={s.value}
                  type="button"
                  onClick={() => setLabel(s.value)}
                  className={`rounded-lg border px-3 py-1.5 text-[12px] font-semibold transition-colors ${(label || 'info') === s.value ? 'border-teal-500 bg-teal-50 text-teal-700' : 'border-slate-200 text-slate-500 hover:border-teal-300'}`}
                >
                  {s.label}
                </button>
              ))}
            </div>
          </div>
          <div>
            <label className="field-label">Callout text</label>
            <RichTextEditor
              content={content}
              onChange={setContent}
              placeholder="Important note…"
              minRows={3}
            />
          </div>
        </>
      )}

      {t === 'divider' && (
        <p className="text-[13px] italic text-slate-400">Divider — no content needed.</p>
      )}

      <div className="flex items-center gap-2 border-t border-teal-100 pt-3">
        <button
          type="button"
          onClick={handleSave}
          disabled={saving}
          className="rounded-lg px-4 py-2 text-[13px] font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-50"
          style={{ background: '#38A09E' }}
        >
          {saving ? 'Saving…' : 'Save block'}
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
// BlockRow
// ---------------------------------------------------------------------------

export function BlockRow({
  block,
  index,
  total,
  assets,
  initialEditing,
  onMoveUp,
  onMoveDown,
  onDelete,
  onUpdate,
}: {
  block: EditorBlock
  index: number
  total: number
  assets: CreatorMediaAsset[]
  initialEditing?: boolean
  onMoveUp: () => void
  onMoveDown: () => void
  onDelete: () => void
  onUpdate: (patch: Record<string, unknown>) => Promise<void>
}) {
  const [editing, setEditing] = useState(initialEditing ?? false)
  const [saving, setSaving] = useState(false)

  async function handleSave(patch: Record<string, unknown>) {
    setSaving(true)
    await onUpdate(patch)
    setSaving(false)
    setEditing(false)
  }

  return (
    <div className={`rounded-xl border bg-white transition-shadow ${editing ? 'border-teal-200 shadow-sm' : 'border-slate-200'}`}>
      <div className="flex items-start gap-3 p-4">

        <div className="flex shrink-0 flex-col gap-1 pt-0.5">
          <button
            type="button"
            onClick={onMoveUp}
            disabled={index === 0}
            className="flex h-6 w-6 items-center justify-center rounded text-[12px] text-slate-300 transition-colors hover:bg-slate-100 hover:text-slate-600 disabled:opacity-20"
            title="Move up"
          >↑</button>
          <button
            type="button"
            onClick={onMoveDown}
            disabled={index === total - 1}
            className="flex h-6 w-6 items-center justify-center rounded text-[12px] text-slate-300 transition-colors hover:bg-slate-100 hover:text-slate-600 disabled:opacity-20"
            title="Move down"
          >↓</button>
        </div>

        <div className="min-w-0 flex-1">
          <div className="mb-2 flex items-center gap-2">
            <span
              className="flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wide"
              style={{ background: 'rgba(56,160,158,0.10)', color: '#38A09E' }}
            >
              <span>{blockIcon(block.block_type)}</span>
              {blockLabel(block.block_type)}
            </span>
          </div>

          {!editing && <BlockPreview block={block} assets={assets} />}

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

        <div className="flex shrink-0 items-center gap-1.5">
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
            className="rounded-lg border border-transparent px-2 py-1.5 text-[12px] text-slate-300 transition-colors hover:border-red-100 hover:bg-red-50 hover:text-red-500"
            title="Delete block"
          >
            ✕
          </button>
        </div>
      </div>
    </div>
  )
}
