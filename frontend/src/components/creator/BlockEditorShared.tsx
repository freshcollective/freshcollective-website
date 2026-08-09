'use client'

/**
 * Shared sub-components for block-based content editors.
 * Used by both StepBlockEditor (pathway step content) and
 * AboutPageEditor (pathway about/sales page content).
 */

import { useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import { apiUrl } from '@/lib/api'
import { exerciseContentToRichText } from '@/lib/exerciseSteps'
import CollectivePaletteColourPicker from '@/components/creator/CollectivePaletteColourPicker'
import { useCollectivePalette } from '@/components/collective/CollectivePaletteContext'
import {
  COLUMNS_VARIANTS,
  cellCountForVariant,
  decodeColumns,
  encodeColumns,
  gridTemplateForVariant,
  labelForVariant,
  resizeColumns,
  variantShortLabel,
  type ColumnsPayload,
  type ColumnsVariant,
} from '@/lib/columnsBlock'
import RichTextEditor from '@/components/creator/RichTextEditor'
import RichTextRenderer from '@/components/RichTextRenderer'
import { checkEmbed, supportedEmbedsList, type EmbedProvider } from '@/lib/embedAllowlist'
import EmbedRenderer from '@/components/EmbedRenderer'
import ButtonBlock, {
  BUTTON_NEW_STYLES,
  checkButtonUrl,
  defaultNewTab,
  encodeButtonCaption,
  parseButtonCaption,
  type ButtonNewStyle,
  type ButtonStyle,
} from '@/components/ButtonBlock'
import {
  CALLOUT_PURPOSES_PICKER,
  normaliseCalloutPurpose,
  resolveCalloutPalette,
  resolveCalloutPurposeIcon,
  resolveCalloutPurposeLabel,
  resolveContainerPalette,
} from '@/lib/calloutPalette'
import type { EditorBlock, StepBlockType, CreatorMediaAsset, CreatorResource } from '@/types/platform'

// ---------------------------------------------------------------------------
// Constants & utilities (exported for use in editor files)
// ---------------------------------------------------------------------------

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

/**
 * Block options shown in the "Add block" picker, in display order.
 *
 * Notes:
 *   - `value` is the database block_type (never renamed — existing rows
 *     keep working). Only the display `label` and `description` change.
 *   - `hidden: true` keeps the entry available for label/icon lookup on
 *     existing blocks but removes it from the picker menu. Headings now
 *     live inside the Content (rich text) block as H1/H2/H3; the legacy
 *     Link block has been folded into Button + plain links inside Content.
 */
export const BLOCK_TYPE_OPTIONS: {
  value: StepBlockType
  label: string
  icon: string
  description: string
  hidden?: boolean
  group?: 'write' | 'engage' | 'media' | 'share' | 'layout'
}[] = [
  { value: 'text',              icon: '¶',  label: 'Content',           description: 'Rich text, headings, lists, tables', group: 'write' },
  { value: 'callout',           icon: '!',  label: 'Callout',           description: 'Note, tip, important, caution, celebration', group: 'write' },

  { value: 'reflection_prompt', icon: '💬', label: 'Reflection prompt', description: 'A question that invites the reader to pause', group: 'engage' },
  { value: 'exercise',          icon: '✏', label: 'Exercise',           description: 'Structured activity with numbered steps', group: 'engage' },

  { value: 'image',             icon: '🖼', label: 'Image',             description: 'Upload directly or pick from Assets', group: 'media' },
  { value: 'video_embed',       icon: '▶',  label: 'Video',             description: 'Paste a YouTube, Vimeo, or Loom URL', group: 'media' },
  { value: 'audio',             icon: '🔊', label: 'Audio',             description: 'Audio player from Assets', group: 'media' },
  // UI label is "External embed"; database value stays 'embed' for back-compat.
  { value: 'embed',             icon: '◇',  label: 'External embed',    description: 'Supported forms, calendars, presentations', group: 'media' },

  { value: 'resource',          icon: '◰',  label: 'Resource',          description: 'Share something from your Resources library', group: 'share' },
  { value: 'file_download',     icon: '↓',  label: 'File download',     description: 'Attach a downloadable file', group: 'share' },
  { value: 'button',            icon: '▢',  label: 'Button',            description: 'A call-to-action button with a destination', group: 'share' },

  { value: 'columns',           icon: '▥',  label: 'Columns',           description: 'Side-by-side columns of content — stack on mobile', group: 'layout' },
  { value: 'divider',           icon: '—',  label: 'Divider',           description: 'Visual separator', group: 'layout' },

  // Hidden — kept for back-compat labelling on existing blocks
  { value: 'heading',           icon: 'H',  label: 'Heading',           description: 'Section title', hidden: true, group: 'write' },
  { value: 'link',              icon: '🔗', label: 'Link',              description: 'External link card', hidden: true, group: 'share' },
]


export const BLOCK_GROUP_LABELS: Record<'write' | 'engage' | 'media' | 'share' | 'layout', string> = {
  write:  'Write',
  engage: 'Engage',
  media:  'Media',
  share:  'Share',
  layout: 'Layout',
}

/**
 * Callout style options. Database values (`info` / `tip` / `warning`) are
 * unchanged so existing callouts continue to render. Only the creator-facing
 * display labels are renamed. Member-facing callouts no longer show a label
 * tag at all — see `[step-slug]/page.tsx` and `about/page.tsx`.
 */
export function blockLabel(type: StepBlockType): string {
  return BLOCK_TYPE_OPTIONS.find(o => o.value === type)?.label ?? type
}

export function blockIcon(type: StepBlockType): string {
  return BLOCK_TYPE_OPTIONS.find(o => o.value === type)?.icon ?? '·'
}

/**
 * Friendly display label for a block badge in the creator UI.
 * Callouts show their creator-set purpose (Highlight / Tip / Placeholder /
 * Reflection / Note) when one is selected; otherwise fall back to "Callout".
 */
export function blockBadgeLabel(block: { block_type: StepBlockType; label?: string | null }): string {
  if (block.block_type === 'callout') {
    return resolveCalloutPurposeLabel(block.label) ?? 'Callout'
  }
  return blockLabel(block.block_type)
}

export function resolveAssetUrl(url: string): string {
  if (url.startsWith('http')) return url
  // Media file_url is stored as `/api/uploads/...` (absolute path on the API
  // host). Anything else is treated as a relative storage path for back-compat.
  return url.startsWith('/') ? `${API_BASE}${url}` : `${API_BASE}/api/uploads/${url}`
}

/**
 * Block types that may opt into a soft-coloured container wrapper.
 * Excluded: callout (already a coloured container), divider (visual separator),
 * heading + link (legacy/hidden).
 *
 * The palette resolver `resolveContainerPalette` lives in
 * `@/lib/calloutPalette` (server-safe — no "use client") so Server Components
 * can call it directly. Don't move it back here.
 */
/**
 * Blocks that may opt into a soft-coloured container wrapper.
 *
 * Deliberately excludes prose-specialised blocks whose visual treatment
 * is owned by the block itself:
 *   - callout — has its own colour + purpose palette
 *   - reflection_prompt — journal-quote treatment
 *   - exercise — structured step-row card
 * Adding a generic container-style selector on top of those would
 * duplicate the choice and feel like "another Content block".
 */
export const CONTAINER_STYLE_BLOCK_TYPES: ReadonlySet<StepBlockType> = new Set([
  'text', 'video_embed', 'audio', 'embed',
  'file_download', 'resource',
])
// Deliberately excluded:
//   - image  — image presentation gets its own controls (width /
//              alignment / caption / alt text). A coloured wrapper
//              competes with the image itself. Existing image blocks
//              that already have ``container_style`` set still render
//              their wrapper on member pages — the value is preserved
//              on save even though the editor no longer offers it.
//   - button — buttons carry their own colour + style choice; a
//              generic wrapper would just double up.

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

/**
 * BlockTypeMenu — the raw list of block-type buttons.
 *
 * ``AddBlockPicker`` renders its own toggle button + this menu inside a
 * dropdown. Newer callers (drag-and-drop insert-between affordances)
 * embed the menu directly so a single click on their trigger opens
 * the type list — no intermediate "Add block" panel.
 */
export function BlockTypeMenu({ onSelect }: { onSelect: (type: StepBlockType) => void }) {
  const visible = BLOCK_TYPE_OPTIONS.filter(opt => !opt.hidden)
  const groups: Array<'write' | 'engage' | 'media' | 'share' | 'layout'> = [
    'write', 'engage', 'media', 'share', 'layout',
  ]
  return (
    <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-xl">
      <div style={{ maxHeight: 480, overflowY: 'auto' }}>
        {groups.map((g) => {
          const items = visible.filter((opt) => (opt.group ?? 'layout') === g)
          if (items.length === 0) return null
          return (
            <div key={g}>
              <p className="border-b border-t border-slate-100 bg-slate-50 px-4 py-1.5 text-[10.5px] font-semibold uppercase tracking-[0.14em] text-slate-500 first:border-t-0">
                {BLOCK_GROUP_LABELS[g]}
              </p>
              {items.map((opt) => (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => onSelect(opt.value)}
                  className="flex w-full items-start gap-3 px-4 py-3 text-left transition-colors hover:bg-slate-50 focus:bg-slate-50 focus:outline-none"
                >
                  <span
                    className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-[15px]"
                    style={{ background: 'rgba(56,160,158,0.10)', color: '#38A09E' }}
                  >
                    {opt.icon}
                  </span>
                  <div className="min-w-0">
                    <p className="text-[14px] font-semibold text-navy-900">{opt.label}</p>
                    <p className="mt-0.5 text-[12px] leading-snug text-black">{opt.description}</p>
                  </div>
                </button>
              ))}
            </div>
          )
        })}
      </div>
    </div>
  )
}


export function AddBlockPicker({ onSelect }: { onSelect: (type: StepBlockType) => void }) {
  const [open, setOpen] = useState(false)

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className="flex items-center gap-2 rounded-lg border border-dashed border-slate-300 px-5 py-3 text-[14px] font-medium text-black transition-colors hover:border-teal-400 hover:text-teal-700"
      >
        <span className="text-[18px] leading-none">+</span>
        Add block
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute left-0 top-full z-20 mt-1.5 w-80 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-xl">
            <p className="border-b border-slate-100 px-4 py-2.5 text-[12px] font-semibold text-black">
              Add a block
            </p>
            <div style={{ maxHeight: 420, overflowY: 'auto' }}>
              {BLOCK_TYPE_OPTIONS.filter(opt => !opt.hidden).map(opt => (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => { onSelect(opt.value); setOpen(false) }}
                  className="flex w-full items-start gap-3 px-4 py-3.5 text-left transition-colors hover:bg-slate-50"
                >
                  <span
                    className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-[15px]"
                    style={{ background: 'rgba(56,160,158,0.10)', color: '#38A09E' }}
                  >
                    {opt.icon}
                  </span>
                  <div className="min-w-0">
                    <p className="text-[14px] font-semibold text-navy-900">{opt.label}</p>
                    <p className="mt-0.5 text-[12px] leading-snug text-black">{opt.description}</p>
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
      <div className="rounded-lg border border-dashed border-slate-200 p-4 text-center">
        <p className="text-[13px] text-black">{emptyMessage ?? 'No files in the Library yet.'}</p>
        <Link href="/creator-studio/library" className="mt-1.5 inline-block text-[13px] font-medium text-teal-600 hover:underline">
          Open Library →
        </Link>
      </div>
    )
  }

  return (
    <div>
      <select
        value={value ?? ''}
        onChange={e => onChange(e.target.value || null)}
        className="field-input"
      >
        <option value="">— Select from Library —</option>
        {filtered.map(a => (
          <option key={a.id} value={a.id}>{a.title} · {a.original_filename}</option>
        ))}
      </select>

      {selected && (
        <div className="mt-2 flex items-center gap-3 rounded-lg border border-slate-100 bg-slate-50 p-3">
          {selected.media_type === 'image' && (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={resolveAssetUrl(selected.file_url)}
              alt={selected.title}
              className="h-16 w-16 rounded object-cover"
            />
          )}
          <div className="min-w-0">
            <p className="truncate text-[13px] font-medium text-navy-900">{selected.title}</p>
            <p className="text-[12px] text-black">{selected.original_filename} · {selected.media_type}</p>
          </div>
          <button
            type="button"
            onClick={() => onChange(null)}
            className="ml-auto flex h-8 w-8 shrink-0 items-center justify-center rounded text-[14px] text-slate-400 hover:bg-red-50 hover:text-red-500"
            title="Remove selection"
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

export function BlockPreview({
  block,
  assets,
  resources = [],
}: {
  block: EditorBlock
  assets: CreatorMediaAsset[]
  resources?: CreatorResource[]
}) {
  const collectivePalette = useCollectivePalette()
  const inner = renderBlockPreviewInner({ block, assets, resources, collectivePalette })
  if (inner == null) return null
  const palette = resolveContainerPalette(block.container_style, collectivePalette)
  if (!palette) return inner
  // Scope ``--fc-quote-accent`` to the preview wrapper so blockquotes
  // inside the preview render with the same palette-derived accent
  // members will see. Keeps editor + member surface visually parallel.
  const scopedStyle = {
    background: palette.bg,
    borderColor: palette.border,
    ['--fc-quote-accent' as string]: palette.accent,
  } as React.CSSProperties
  return (
    <div
      className="rounded-lg border px-4 py-3"
      style={scopedStyle}
    >
      {inner}
    </div>
  )
}

function renderBlockPreviewInner({
  block,
  assets,
  resources,
  collectivePalette,
}: {
  block: EditorBlock
  assets: CreatorMediaAsset[]
  resources: CreatorResource[]
  collectivePalette: import('@/lib/collectivePalette').CollectivePaletteMeta | null
}) {
  const asset = block.media_asset_id
    ? assets.find(a => a.id === block.media_asset_id) ?? block.media_asset
    : block.media_asset
  const t = block.block_type

  // ── Divider ──────────────────────────────────────────────────
  // A decorative three-dot ornament in place of a bare hairline;
  // reads as a chapter break rather than a form separator.
  if (t === 'divider') return (
    <div
      className="my-6 flex justify-center text-[14px] tracking-[0.5em] text-slate-300 select-none"
      aria-hidden="true"
    >
      ···
    </div>
  )

  if (t === 'columns') return <ColumnsPreview content={block.content ?? null} />

  // ── Heading ──────────────────────────────────────────────────
  // Serif face with editorial weight, generous top margin so the
  // heading reads as a chapter or section break rather than a
  // form label. ``first:mt-0`` prevents an unwanted top gap when a
  // step opens with a heading.
  if (t === 'heading') {
    const level = block.label === 'h1' ? 'h1' : block.label === 'h3' ? 'h3' : 'h2'
    const text = block.content || null
    const empty = <span className="italic text-slate-400">Untitled heading</span>
    if (level === 'h1') {
      return (
        <h1 className="mb-4 mt-10 max-w-[36ch] font-serif text-[32px] font-normal leading-tight text-navy-900 first:mt-0">
          {text ?? empty}
        </h1>
      )
    }
    if (level === 'h3') {
      return (
        <h3 className="mb-2 mt-7 max-w-[44ch] font-serif text-[19px] font-medium leading-snug text-navy-900 first:mt-0">
          {text ?? empty}
        </h3>
      )
    }
    return (
      <h2 className="mb-3 mt-9 max-w-[40ch] font-serif text-[24px] font-normal leading-tight text-navy-900 first:mt-0">
        {text ?? empty}
      </h2>
    )
  }

  // ── Paragraph ─────────────────────────────────────────────────
  // 16px on 1.8 leading is the editorial sweet spot for long-form
  // reading. Line length capped at ~70ch so the eye doesn't have to
  // travel too far between rows. Warm ink colour on white for a
  // page-in-hand feeling rather than screen text.
  if (t === 'text') return (
    <div className="max-w-[70ch] text-[16px] font-normal leading-[1.8] tracking-[0.005em] text-navy-900/[0.88]">
      {block.content
        ? <RichTextRenderer content={block.content} />
        : <span className="italic text-slate-400">Empty paragraph — click to write.</span>}
    </div>
  )

  // ── Image ─────────────────────────────────────────────────────
  // Figures breathe — generous vertical margin, softer corner
  // radius (a plate rather than a card), muted italic caption with
  // constrained width so it reads centred beneath the image.
  if (t === 'image') {
    const imgSrc = asset ? resolveAssetUrl(asset.file_url) : block.embed_url
    if (!imgSrc) {
      return (
        <div className="my-6 flex items-center gap-3 rounded-lg border border-dashed border-slate-200 bg-slate-50 px-4 py-6 text-slate-500">
          <span className="text-[22px]">🖼</span>
          <span className="text-[13.5px] italic">Click to add an image.</span>
        </div>
      )
    }
    const altText = block.label ?? asset?.title ?? ''
    return (
      <figure className="my-7">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={imgSrc}
          alt={altText}
          className="block w-full rounded-xl object-cover"
          style={{ maxHeight: 520 }}
        />
        {block.caption && (
          <figcaption className="mx-auto mt-3 max-w-md text-center text-[13px] italic leading-relaxed text-slate-500">
            {block.caption}
          </figcaption>
        )}
      </figure>
    )
  }

  if (t === 'video_embed') {
    const embed = block.embed_url ? getEmbedUrl(block.embed_url) : null
    if (embed) {
      return (
        <figure className="my-7">
          <div className="overflow-hidden rounded-xl bg-black" style={{ aspectRatio: '16/9' }}>
            <iframe
              src={embed}
              className="h-full w-full"
              allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
              allowFullScreen
            />
          </div>
          {block.caption && (
            <figcaption className="mx-auto mt-3 max-w-md text-center text-[13px] italic leading-relaxed text-slate-500">
              {block.caption}
            </figcaption>
          )}
        </figure>
      )
    }
    return (
      <div className="my-4 flex items-center gap-2 rounded-lg border border-dashed border-slate-200 bg-slate-50 px-4 py-3 text-[13.5px] text-slate-500">
        <span>▶</span>
        {block.embed_url
          ? <span className="italic">{block.embed_url}</span>
          : <span className="italic">Click to paste a YouTube, Vimeo, or Loom URL.</span>}
      </div>
    )
  }

  if (t === 'audio') {
    if (asset) {
      return (
        <figure className="my-6">
          <audio controls className="w-full" src={resolveAssetUrl(asset.file_url)} />
          {block.caption && (
            <figcaption className="mx-auto mt-3 max-w-md text-center text-[13px] italic leading-relaxed text-slate-500">
              {block.caption}
            </figcaption>
          )}
        </figure>
      )
    }
    return (
      <div className="my-4 flex items-center gap-2 rounded-lg border border-dashed border-slate-200 bg-slate-50 px-4 py-3 text-[13.5px] text-slate-500">
        <span>🔊</span>
        <span className="italic">Click to attach audio.</span>
      </div>
    )
  }

  if (t === 'file_download') return (
    <div className="flex items-center gap-3 rounded-lg border border-slate-200 bg-slate-50 px-4 py-3">
      <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-white text-[16px] text-slate-500">↓</span>
      <div className="min-w-0 flex-1">
        {asset ? (
          <>
            <p className="text-[14px] font-semibold text-navy-900">{block.label || asset.title}</p>
            {block.label && <p className="text-[12px] text-slate-500">{asset.title}</p>}
          </>
        ) : (
          <p className="text-[13.5px] italic text-slate-500">Click to attach a downloadable file.</p>
        )}
      </div>
    </div>
  )

  if (t === 'link') return (
    <div className="flex items-center gap-3 rounded-lg border border-slate-200 bg-white px-4 py-3">
      <span className="text-[16px]">🔗</span>
      <div className="min-w-0 flex-1">
        <p className="text-[14px] font-semibold text-navy-900">{block.label || 'Link'}</p>
        {block.embed_url
          ? <p className="text-[12.5px] text-teal-700 break-all">{block.embed_url}</p>
          : <p className="text-[12.5px] italic text-slate-500">No URL set.</p>}
      </div>
    </div>
  )

  // ── Reflection prompt — journal-style pull quote ─────────────
  if (t === 'reflection_prompt') return (
    <div
      className="relative my-6 rounded-xl border px-7 py-6"
      style={{ background: 'rgba(56,160,158,0.05)', borderColor: 'rgba(56,160,158,0.24)' }}
    >
      <p
        className="mb-3 flex items-center gap-2 text-[10.5px] font-semibold uppercase tracking-[0.16em]"
        style={{ color: '#0f4645' }}
      >
        <span aria-hidden="true" className="text-[15px] leading-none">❝</span>
        Reflection prompt
      </p>
      <div
        className="font-serif text-[19px] leading-[1.5] text-navy-900"
        style={{ fontStyle: 'italic' }}
      >
        {block.content
          ? <RichTextRenderer content={block.content} />
          : <span className="not-italic text-slate-400">Ask the reader a question…</span>}
      </div>
      {block.caption && (
        <p className="mt-3 text-[14px] leading-[1.7] text-navy-900/[0.75]">{block.caption}</p>
      )}
    </div>
  )

  // ── Exercise — a warm plate with a serif title ──────────────
  if (t === 'exercise') {
    const body = exerciseContentToRichText(block.content)
    return (
      <div className="my-6 rounded-xl border border-slate-200 bg-slate-50/70 px-6 py-5">
        <div className="mb-2 flex items-center gap-2 text-[10.5px] font-semibold uppercase tracking-[0.16em] text-slate-700">
          <span aria-hidden="true" className="text-[13px]">✏</span>
          Exercise
        </div>
        {block.label && (
          <p className="mt-1 mb-4 font-serif text-[21px] leading-snug text-navy-900">
            {block.label}
          </p>
        )}
        <div className="text-[15px] leading-[1.75] text-navy-900/[0.85]">
          {body
            ? <RichTextRenderer content={body} />
            : <span className="italic text-slate-400">Walk the reader through the exercise…</span>}
        </div>
      </div>
    )
  }

  // ── Callout ──────────────────────────────────────────────────
  if (t === 'callout') {
    const palette = resolveCalloutPalette(block.caption, block.label, undefined, collectivePalette)
    const icon = resolveCalloutPurposeIcon(block.label)
    const purposeLabel = resolveCalloutPurposeLabel(block.label)
    return (
      <div
        className="my-5 rounded-xl border px-6 py-5"
        style={{ background: palette.bg, borderColor: palette.border }}
      >
        {(icon || purposeLabel) && (
          <div className="mb-2 flex items-center gap-2 text-[11.5px] font-semibold uppercase tracking-[0.14em] text-navy-900">
            {icon && <span aria-hidden="true" className="text-[14px]">{icon}</span>}
            {purposeLabel && <span>{purposeLabel}</span>}
          </div>
        )}
        <div className="text-[15.5px] leading-[1.75] text-navy-900/[0.88]">
          {block.content
            ? <RichTextRenderer content={block.content} />
            : <span className="italic text-slate-400">Callout body…</span>}
        </div>
      </div>
    )
  }

  if (t === 'embed') {
    const check = block.embed_url ? checkEmbed(block.embed_url) : null
    return (
      <div className="flex items-center gap-2 text-[13px]">
        <span>◇</span>
        <span className="font-medium text-navy-900">{block.label || 'External embed'}</span>
        {check?.ok
          ? <span className="text-black">· {check.provider.name}</span>
          : <span className="italic text-black">— no URL set</span>}
        {block.caption && <span className="text-black">· {block.caption}</span>}
      </div>
    )
  }

  if (t === 'button') {
    return (
      <div className="flex items-center gap-3">
        <ButtonBlock
          href={block.embed_url || '#'}
          text={block.label || 'Button'}
          caption={block.caption ?? null}
          collectivePalette={collectivePalette}
          previewOnly
        />
        {block.embed_url && (
          <span className="text-[11px] text-black break-all">→ {block.embed_url}</span>
        )}
      </div>
    )
  }

  if (t === 'resource') {
    // Prefer the live snapshot from the loaded creator-resources list (always
    // current); fall back to the inline `resource` field the API sends back
    // with the block (also fresh, just may lag a save by a tick).
    const linked = block.resource_id
      ? resources.find(r => r.id === block.resource_id) ?? null
      : null
    const snapshot = linked ?? block.resource
    if (!snapshot) {
      return (
        <p className="text-[13px] italic text-black">
          ◰ No resource selected
        </p>
      )
    }
    const isDraft = snapshot.status !== 'published'
    const title = block.label || snapshot.title
    const description = block.caption || snapshot.description
    return (
      <div className="flex items-start gap-3">
        <span
          className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-[15px]"
          style={{ background: 'rgba(56,160,158,0.10)', color: '#246B6A' }}
        >
          ◰
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <p className="text-[14px] font-semibold text-navy-900">{title}</p>
            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-slate-500">
              {snapshot.resource_type}
            </span>
            {isDraft && (
              <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-700">
                Draft · hidden from members
              </span>
            )}
          </div>
          {description && (
            <p className="mt-0.5 text-[12.5px] leading-relaxed text-black">{description}</p>
          )}
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
  resources = [],
  onSave,
  onAutosave,
  onCancel,
  onDeleteRequested,
  saving,
  spaceSlug,
  onAssetUploaded,
}: {
  block: EditorBlock
  assets: CreatorMediaAsset[]
  resources?: CreatorResource[]
  /** Explicit save — closes the edit form. Wired to the Save button. */
  onSave: (patch: Record<string, unknown>) => void
  /** Silent autosave — persists changes without closing the form. When
   *  omitted, autosave is disabled and only the Save button persists. */
  onAutosave?: (patch: Record<string, unknown>) => void
  onCancel: () => void
  /** Optional destructive action rendered in the editor footer so
   *  Delete stays discoverable while the block is active — the
   *  permanent right-gutter Delete is hidden in edit state. */
  onDeleteRequested?: () => void
  saving: boolean
  /** Provided so image blocks can upload directly to Assets
   *  from the editor. When omitted the upload button is hidden. */
  spaceSlug?: string
  /** Called when a new asset is uploaded so the parent can add it to
   *  its ``assets`` list without a full refresh. */
  onAssetUploaded?: (asset: CreatorMediaAsset) => void
}) {
  // Exercise blocks are now a specialised Content block: the body is a
  // regular TipTap document living in ``content``. Legacy rows that
  // still hold the ``{"exercise":{"steps":[…]}}`` envelope are
  // migrated to a TipTap ordered-list document on first mount so the
  // writer opens them as editable prose without loss.
  const [content, setContent] = useState(
    block.block_type === 'exercise'
      ? exerciseContentToRichText(block.content)
      : (block.content ?? ''),
  )
  // Callouts: seed `label` with the normalised purpose (legacy info/warning
  // become highlight/placeholder; tip stays tip; anything else clears).
  const [label, setLabel] = useState(
    block.block_type === 'callout'
      ? normaliseCalloutPurpose(block.label)
      : (block.label ?? ''),
  )
  // Callouts: the stored ``caption`` already holds a palette token,
  // custom hex, or legacy chip key — pass it through untouched so the
  // colour picker shows the current selection. If a callout arrives
  // with no caption but has a legacy label (info/tip/warning), seed a
  // matching legacy chip key so the picker reflects what the reader
  // sees today.
  const [caption, setCaption] = useState(
    block.block_type === 'callout'
      ? (block.caption
        ?? (block.label && ['info', 'tip', 'warning'].includes(block.label)
          ? resolveCalloutPalette(block.caption, block.label).key
          : ''))
      : (block.caption ?? ''),
  )
  const [embedUrl, setEmbedUrl] = useState(block.embed_url ?? '')
  const [mediaAssetId, setMediaAssetId] = useState<string | null>(block.media_asset_id)
  const [resourceId, setResourceId] = useState<string | null>(block.resource_id)
  // Image blocks store alt text in ``label``. Three distinct states
  // (unset / decorative / explicit) map onto two values (``null`` and
  // any string), so we carry an ``altUnset`` flag alongside ``label``:
  //   - altUnset = true                      → save label as null
  //   - altUnset = false && label === ''     → decorative (save '')
  //   - altUnset = false && label === '...'  → explicit alt (save '...')
  // Legacy image blocks with ``label = null`` open in the "unset"
  // state so the member renderer keeps falling back to asset.title.
  const [imageAltUnset, setImageAltUnset] = useState<boolean>(
    block.block_type === 'image' && block.label === null,
  )
  const [containerStyle, setContainerStyle] = useState<string | null>(block.container_style ?? null)

  const t = block.block_type
  const embedPreview = t === 'video_embed' && embedUrl ? getEmbedUrl(embedUrl) : null
  const supportsContainerStyle = CONTAINER_STYLE_BLOCK_TYPES.has(t)

  function buildPatch(): Record<string, unknown> {
    // Image block invariants:
    //   * ``label`` doubles as alt text — three states that must be
    //     preserved end-to-end (null → legacy unset, '' → decorative,
    //     '...' → explicit alt). The ``imageAltUnset`` flag lifts the
    //     ambiguity between "empty because decorative" and "empty
    //     because the writer hasn't touched it". Do not coerce '' → null.
    //   * ``container_style`` is deprecated for images: the editor no
    //     longer offers a picker, but we preserve whatever value the
    //     block already has so existing published rows don't lose
    //     their soft-tint wrapper on their next save.
    const isImage = t === 'image'
    const labelForImage = imageAltUnset ? null : label
    const containerForImage = block.container_style ?? null

    return {
      content: content || null,
      label: isImage ? labelForImage : (label || null),
      caption: caption || null,
      embed_url: embedUrl || null,
      media_asset_id: mediaAssetId,
      resource_id: t === 'resource' ? resourceId : block.resource_id,
      container_style: isImage
        ? containerForImage
        : (supportsContainerStyle ? containerStyle : null),
    }
  }

  function handleSave() {
    onSave(buildPatch())
  }

  /**
   * Autosave: fire ``onSave`` on debounced state changes so writers do
   * not need to click Save between edits. The Save button remains as
   * an explicit flush for the writer who wants confirmation.
   *
   * We skip the initial render so mounting a block does not trigger a
   * no-op PATCH.
   */
  const initialMount = useRef(true)
  const autosaveTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  useEffect(() => {
    if (initialMount.current) {
      initialMount.current = false
      return
    }
    if (!onAutosave) return
    if (autosaveTimer.current) clearTimeout(autosaveTimer.current)
    autosaveTimer.current = setTimeout(() => {
      onAutosave(buildPatch())
    }, 700)
    return () => {
      if (autosaveTimer.current) clearTimeout(autosaveTimer.current)
    }
    // Callback identity is stable across renders in every caller; the
    // effect is intentionally scoped to the tracked fields.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [content, label, caption, embedUrl, mediaAssetId, resourceId, containerStyle, imageAltUnset])

  /** Upload an image directly from the writer's device to this
   *  collective's Asset Library. On success the returned asset is
   *  registered with the parent via ``onAssetUploaded`` and set as
   *  this block's media source.
   *
   *  The uploader is scoped to this block form so a new image block can
   *  be filled without navigating away from the pathway editor. */
  const [uploadBusy, setUploadBusy] = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)
  async function uploadFromDevice(file: File) {
    if (!spaceSlug) return
    setUploadBusy(true)
    setUploadError(null)
    try {
      const form = new FormData()
      form.append('file', file)
      form.append('title', file.name.replace(/\.[^.]+$/, ''))
      const res = await fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/media`), {
        method: 'POST',
        credentials: 'include',
        body: form,
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(typeof body.detail === 'string' ? body.detail : `Upload: ${res.status}`)
      }
      const asset = await res.json() as CreatorMediaAsset
      onAssetUploaded?.(asset)
      setMediaAssetId(asset.id)
    } catch (e) {
      setUploadError((e as Error).message)
    } finally {
      setUploadBusy(false)
    }
  }

  // A purpose-built editor is used for reflection_prompt (see
  // PromptEditor below). Exercise is a specialised Content block
  // handled inline via the standard t === 'exercise' branch further
  // down. Every other block uses the shared form.
  if (t === 'reflection_prompt') {
    return (
      <PromptEditor
        content={content}
        caption={caption}
        onContentChange={setContent}
        onCaptionChange={setCaption}
        onAutosave={onAutosave ? (() => onAutosave(buildPatch())) : undefined}
        onDone={onCancel}
        onDeleteRequested={onDeleteRequested}
      />
    )
  }
  if (t === 'columns') {
    return (
      <ColumnsEditor
        content={content}
        onContentChange={setContent}
        onAutosave={onAutosave ? (() => onAutosave(buildPatch())) : undefined}
        onDone={onCancel}
        onDeleteRequested={onDeleteRequested}
      />
    )
  }

  return (
    <div className="space-y-5">

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
                  className={`rounded-lg border px-3.5 py-2 text-[13px] font-semibold transition-colors ${label === `h${idx + 1}` || (!label && idx === 1) ? 'border-teal-500 bg-teal-50 text-teal-700' : 'border-slate-200 text-black hover:border-teal-300'}`}
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
            minRows={10}
          />
        </div>
      )}

      {t === 'exercise' && (
        <>
          <div>
            <label className="field-label">Title <span className="text-slate-500">(optional)</span></label>
            <input
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              className="field-input font-serif text-[18px] text-navy-900"
              placeholder="Give the exercise a short title"
            />
          </div>
          <div>
            <label className="field-label">Instructions</label>
            <RichTextEditor
              content={content}
              onChange={setContent}
              placeholder="Walk the reader through the steps… Numbered lists, bullets, and formatting all supported."
              minRows={8}
            />
          </div>
        </>
      )}

      {t === 'image' && (
        <ImageBlockFields
          assets={assets}
          mediaAssetId={mediaAssetId}
          onMediaAssetIdChange={setMediaAssetId}
          embedUrl={embedUrl}
          onEmbedUrlChange={setEmbedUrl}
          caption={caption}
          onCaptionChange={setCaption}
          altText={label}
          onAltTextChange={setLabel}
          altUnset={imageAltUnset}
          onAltUnsetChange={setImageAltUnset}
          spaceSlug={spaceSlug}
          uploadBusy={uploadBusy}
          uploadError={uploadError}
          onUploadFile={(file) => void uploadFromDevice(file)}
        />
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
            <label className="field-label">Audio from Assets</label>
            <MediaPicker
              assets={assets}
              value={mediaAssetId}
              onChange={setMediaAssetId}
              accept={['audio']}
              emptyMessage="No audio files in this collective's Assets yet."
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
            <label className="field-label">File from Assets</label>
            <MediaPicker
              assets={assets}
              value={mediaAssetId}
              onChange={setMediaAssetId}
              accept={['document', 'other', 'audio', 'image']}
              emptyMessage="No files in this collective's Assets yet."
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

      {/* reflection_prompt uses a purpose-built editor (PromptEditor
          above); exercise is a specialised Content block rendered
          inline via the t === 'exercise' branch above. */}

      {t === 'callout' && (
        <>
          <div>
            <label className="field-label">Purpose</label>
            <div className="flex flex-wrap gap-2">
              {CALLOUT_PURPOSES_PICKER.map(p => {
                const selected = label === p.key
                return (
                  <button
                    key={p.key}
                    type="button"
                    onClick={() => {
                      setLabel(p.key)
                      // Seed the colour to the purpose's default when the
                      // writer hasn't explicitly picked one.
                      if (!caption) setCaption(p.defaultColour)
                    }}
                    className={`flex items-center gap-2 rounded-lg border px-3 py-1.5 text-[13px] font-medium transition-all ${
                      selected ? 'border-teal-500 ring-2 ring-teal-200 bg-teal-50' : 'border-slate-200 bg-white hover:border-slate-400'
                    }`}
                    aria-pressed={selected}
                  >
                    <span className="text-[15px]">{p.icon}</span>
                    <span className="text-navy-900">{p.label}</span>
                  </button>
                )
              })}
            </div>
            <p className="mt-1 text-[11.5px] text-slate-500">
              Purpose controls the icon and default colour shown to members.
            </p>
          </div>

          <div>
            <label className="field-label">Colour (optional override)</label>
            <CollectivePaletteColourPicker
              value={caption || null}
              onChange={(next) => setCaption(next ?? '')}
              label="Your palette"
            />
          </div>

          <div>
            <label className="field-label">Callout text</label>
            <RichTextEditor
              content={content}
              onChange={setContent}
              placeholder="Write the callout body…"
              minRows={4}
            />
          </div>
        </>
      )}

      {t === 'divider' && (
        <p className="text-[13px] italic text-black">Divider — no content needed.</p>
      )}

      {t === 'embed' && (
        <EmbedFields
          rawValue={embedUrl}
          onChange={setEmbedUrl}
          label={label}
          onLabelChange={setLabel}
          caption={caption}
          onCaptionChange={setCaption}
        />
      )}

      {t === 'button' && (
        <ButtonFields
          text={label}
          onTextChange={setLabel}
          url={embedUrl}
          onUrlChange={setEmbedUrl}
          style={caption}
          onStyleChange={setCaption}
          newTabPref={content}
          onNewTabPrefChange={setContent}
        />
      )}

      {t === 'resource' && (
        <ResourceFields
          resources={resources}
          assets={assets}
          resourceId={resourceId}
          onResourceIdChange={(id) => {
            setResourceId(id)
            if (id) setMediaAssetId(null)
          }}
          mediaAssetId={mediaAssetId}
          onMediaAssetIdChange={(id) => {
            setMediaAssetId(id)
            if (id) setResourceId(null)
          }}
          titleOverride={label}
          onTitleOverrideChange={setLabel}
          descriptionOverride={caption}
          onDescriptionOverrideChange={setCaption}
        />
      )}

      {supportsContainerStyle && (
        <ContainerStyleField value={containerStyle} onChange={setContainerStyle} />
      )}

      <div className="flex items-center gap-2 border-t border-slate-200 pt-4">
        {onDeleteRequested && (
          <button
            type="button"
            onClick={onDeleteRequested}
            className="rounded-full border border-slate-300 bg-white px-3.5 py-2 text-[13px] font-semibold text-red-600 transition-colors hover:border-red-500 hover:bg-red-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-red-400"
            title="Delete this block"
          >
            Delete block
          </button>
        )}
        <div className="flex-1" />
        {/* Explicit-save + Cancel remain on the right; the destructive
            control sits on the far left with a clear label and
            triggers the shared confirmation dialog. */}
        <button
          type="button"
          onClick={handleSave}
          disabled={saving}
          className="rounded-lg px-5 py-2.5 text-[14px] font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-50"
          style={{ background: '#38A09E' }}
        >
          {saving ? 'Saving…' : 'Save block'}
        </button>
        <button
          type="button"
          onClick={onCancel}
          disabled={saving}
          className="rounded-lg border border-slate-200 px-5 py-2.5 text-[14px] font-medium text-black transition-colors hover:bg-slate-50"
        >
          Cancel
        </button>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// ContainerStyleField — optional soft-coloured wrapper picker
// ---------------------------------------------------------------------------

function ContainerStyleField({
  value,
  onChange,
}: {
  value: string | null
  onChange: (v: string | null) => void
}) {
  return (
    <div className="border-t border-teal-100 pt-4">
      <label className="field-label">
        Container style <span className="text-black">(optional)</span>
      </label>
      <CollectivePaletteColourPicker
        value={value}
        onChange={onChange}
        allowClear
        label="Your palette"
      />
      <p className="mt-1.5 text-[12px] text-black">
        Wraps this block in a soft-coloured box on the member page.
      </p>
    </div>
  )
}

// ---------------------------------------------------------------------------
// EmbedFields — editor UI for `embed` blocks (URL or iframe paste + live preview)
// ---------------------------------------------------------------------------

function EmbedFields({
  rawValue,
  onChange,
  label,
  onLabelChange,
  caption,
  onCaptionChange,
}: {
  rawValue: string
  onChange: (v: string) => void
  label: string
  onLabelChange: (v: string) => void
  caption: string
  onCaptionChange: (v: string) => void
}) {
  const check = rawValue ? checkEmbed(rawValue) : null
  const isIframePaste = rawValue.toLowerCase().includes('<iframe')
  const provider: EmbedProvider | null = check?.ok ? check.provider : null

  return (
    <>
      <div>
        <label className="field-label">Embed URL or iframe code</label>
        <textarea
          value={rawValue}
          onChange={e => onChange(e.target.value)}
          className="field-input font-mono text-[12px] leading-relaxed"
          placeholder={'https://calendly.com/your-name/30min\nor paste the full <iframe ...> code'}
          rows={4}
          autoFocus
        />
        <p className="mt-1 text-[11px] text-black">
          Supported: {supportedEmbedsList()}.
          {' '}Other hosts will be rejected for safety.
        </p>
        {check && !check.ok && (
          <p className="mt-1 text-[12px] text-amber-600">⚠ {check.reason}</p>
        )}
        {check?.ok && (
          <p className="mt-1 text-[12px] text-teal-700">
            ✓ Recognised as <strong>{provider!.name}</strong>
            {isIframePaste && <span className="text-black"> · src extracted from iframe</span>}
          </p>
        )}
      </div>

      {check?.ok && (
        <div>
          <label className="field-label">Preview</label>
          <div className="rounded-lg border border-slate-200 bg-white p-2">
            <EmbedRenderer url={check.url} provider={provider!} title={label || 'Embed preview'} />
          </div>
        </div>
      )}

      <div>
        <label className="field-label">Title (optional)</label>
        <input
          value={label}
          onChange={e => onLabelChange(e.target.value)}
          className="field-input"
          placeholder="Booking calendar"
        />
      </div>

      <div>
        <label className="field-label">Caption (optional)</label>
        <input
          value={caption}
          onChange={e => onCaptionChange(e.target.value)}
          className="field-input"
          placeholder="Pick a time that works for you"
        />
      </div>
    </>
  )
}


// ---------------------------------------------------------------------------
// ButtonFields — editor UI for `button` blocks
// ---------------------------------------------------------------------------

function ButtonFields({
  text,
  onTextChange,
  url,
  onUrlChange,
  style,
  onStyleChange,
  newTabPref,
  onNewTabPrefChange,
}: {
  text: string
  onTextChange: (v: string) => void
  url: string
  onUrlChange: (v: string) => void
  /** The raw stored caption — legacy string, JSON envelope, or empty. */
  style: string
  /** Called with a new raw caption string. */
  onStyleChange: (v: string) => void
  newTabPref: string
  onNewTabPrefChange: (v: string) => void
}) {
  const urlError = url ? checkButtonUrl(url) : null

  // Parse the stored caption into ``{ style, colour }`` regardless of
  // whether it's a legacy chip or the new JSON envelope. Legacy chips
  // are mapped into the modern (Filled/Outline/Text) + palette-role
  // shape so the writer sees consistent controls — the *stored* row is
  // only rewritten when the writer touches Style or Colour.
  const parsed = parseButtonCaption(style)
  const currentStyle: ButtonNewStyle = parsed.kind === 'modern'
    ? parsed.style
    : mapLegacyStyleToModern(parsed.style)
  const currentColour: string = parsed.kind === 'modern'
    ? parsed.colour
    : mapLegacyStyleToColour(parsed.style)
  const isLegacy = parsed.kind === 'legacy'

  function updateStyle(next: ButtonNewStyle) {
    onStyleChange(encodeButtonCaption(next, currentColour))
  }
  function updateColour(next: string | null) {
    // Colour is required for buttons — treat a cleared value as a
    // safe fallback so we always store a valid JSON envelope.
    onStyleChange(encodeButtonCaption(currentStyle, next ?? 'palette:primary'))
  }

  // Tri-state: 'new_tab' | 'same_tab' | '' (auto based on URL type)
  const effectiveNewTab =
    newTabPref === 'new_tab' ? true :
    newTabPref === 'same_tab' ? false :
    (url ? defaultNewTab(url) : true)

  const collectivePalette = useCollectivePalette()
  const previewCaption = encodeButtonCaption(currentStyle, currentColour)

  return (
    <>
      <div>
        <label className="field-label">Button text</label>
        <input
          value={text}
          onChange={e => onTextChange(e.target.value)}
          className="field-input"
          placeholder="Book a session"
          maxLength={80}
          autoFocus
        />
      </div>

      <div>
        <label className="field-label">Link URL</label>
        <input
          value={url}
          onChange={e => onUrlChange(e.target.value)}
          className="field-input"
          placeholder="https://example.com  ·  /spaces/the-grove  ·  mailto:hello@example.com"
        />
        <p className="mt-1 text-[11px] text-black">
          Accepts external URLs (https://), internal paths (/spaces/…), or mailto: links.
        </p>
        {urlError && (
          <p className="mt-1 text-[12px] text-amber-600">⚠ {urlError}</p>
        )}
      </div>

      <div>
        <label className="field-label">Style</label>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
          {BUTTON_NEW_STYLES.map(s => {
            const selected = currentStyle === s.value
            // Each style tile shows a mini live-preview of what the
            // choice actually looks like — a real ButtonBlock render in
            // ``previewOnly`` mode with the currently-picked colour.
            // No more relying on the writer to decode "Text" as
            // "no background".
            const previewCaption = encodeButtonCaption(s.value, currentColour)
            return (
              <button
                key={s.value}
                type="button"
                onClick={() => updateStyle(s.value)}
                title={s.description}
                aria-pressed={selected}
                className={`flex flex-col items-center gap-2 rounded-xl border-2 bg-white px-3 py-4 text-left transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400 ${
                  selected ? 'border-teal-500 shadow-sm ring-2 ring-teal-200' : 'border-slate-200 hover:border-teal-300'
                }`}
              >
                <div className="flex h-11 w-full items-center justify-center rounded-md bg-slate-50 px-2">
                  <ButtonBlock
                    href="#"
                    text={s.label}
                    caption={previewCaption}
                    collectivePalette={collectivePalette}
                    previewOnly
                  />
                </div>
                <div className="w-full">
                  <p className={`text-[13px] font-semibold ${selected ? 'text-teal-700' : 'text-navy-900'}`}>
                    {s.label}
                  </p>
                  <p className="text-[11.5px] leading-snug text-slate-500">{s.description}</p>
                </div>
              </button>
            )
          })}
        </div>
        {isLegacy && (
          <p className="mt-1.5 text-[11.5px] italic text-slate-500">
            This button was created before the palette system. Picking a Style or Colour will save it in the new format.
          </p>
        )}
      </div>

      <div>
        <label className="field-label">Colour</label>
        <CollectivePaletteColourPicker
          value={currentColour}
          onChange={updateColour}
          label="Your palette"
        />
      </div>

      <div>
        <label className="field-label">Open link</label>
        <div className="flex flex-wrap gap-2">
          {[
            { value: '',         label: `Auto (${url && defaultNewTab(url) ? 'new tab' : 'same tab'})` },
            { value: 'new_tab',  label: 'New tab' },
            { value: 'same_tab', label: 'Same tab' },
          ].map(opt => (
            <button
              key={opt.value || 'auto'}
              type="button"
              onClick={() => onNewTabPrefChange(opt.value)}
              className={`rounded-lg border px-3.5 py-2 text-[13px] font-semibold transition-colors ${
                (newTabPref || '') === opt.value
                  ? 'border-teal-500 bg-teal-50 text-teal-700'
                  : 'border-slate-200 text-black hover:border-teal-300'
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
        <p className="mt-1 text-[11px] text-black">
          External links default to new tab. Internal paths default to same tab.
        </p>
      </div>

      <div>
        <label className="field-label">Preview</label>
        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <ButtonBlock
            href={url || '#'}
            text={text || 'Button'}
            caption={previewCaption}
            collectivePalette={collectivePalette}
            newTabPref={effectiveNewTab ? 'new_tab' : 'same_tab'}
            previewOnly
          />
        </div>
      </div>
    </>
  )
}


/** Convert a legacy Filled/Outline/Text intent from the four
 *  hard-coded pre-palette styles into the new tri-style vocabulary,
 *  used when a legacy button is opened in the editor for the first
 *  time. Nothing is written back until the writer picks a value. */
function mapLegacyStyleToModern(style: ButtonStyle): ButtonNewStyle {
  if (style === 'outline') return 'outline'
  // ``subtle`` was a soft slate fill; the closest modern intent is
  // Filled (with a neutral colour). ``primary`` and ``secondary``
  // are also Filled by intent.
  return 'filled'
}


/** Seed the palette colour that best matches each legacy hard-coded
 *  style, so opening a legacy button in the editor picks the closest
 *  palette role by default. This is a *display* seed; the row is only
 *  rewritten when the writer touches the picker. */
function mapLegacyStyleToColour(style: ButtonStyle): string {
  if (style === 'secondary') return 'palette:secondary'
  return 'palette:primary'
}


// ---------------------------------------------------------------------------
// ImageBlockFields — editor UI for `image` blocks
// ---------------------------------------------------------------------------

/**
 * Image editor with two equal source actions before an image is
 * selected — Choose from Assets (opens a grid modal) and Upload from
 * your computer (triggers a hidden file input that saves directly to
 * the current collective's Assets) — plus an External URL fallback.
 *
 * Once an image is selected, the source controls collapse to a large
 * preview + title + Replace/Remove. Replace returns the writer to the
 * source-choice UI without deleting the asset from Assets. Remove
 * clears the image reference on *this block only* — the underlying
 * asset stays in the library.
 *
 * Alt text lives on ``block.label`` (see buildPatch for the reasoning).
 * ``label = ''`` means the writer explicitly marked the image as
 * decorative; that empty string survives round-trip so the member
 * renderer can emit ``alt=""`` without falling back to the asset
 * title.
 */
function ImageBlockFields({
  assets,
  mediaAssetId,
  onMediaAssetIdChange,
  embedUrl,
  onEmbedUrlChange,
  caption,
  onCaptionChange,
  altText,
  onAltTextChange,
  altUnset,
  onAltUnsetChange,
  spaceSlug,
  uploadBusy,
  uploadError,
  onUploadFile,
}: {
  assets: CreatorMediaAsset[]
  mediaAssetId: string | null
  onMediaAssetIdChange: (id: string | null) => void
  embedUrl: string
  onEmbedUrlChange: (v: string) => void
  caption: string
  onCaptionChange: (v: string) => void
  /** Alt-text string. Only meaningful when ``altUnset`` is false:
   *   - ''     → decorative (writer's explicit choice)
   *   - '...'  → explicit alt text
   *  When ``altUnset`` is true the value is ignored (rendered as blank). */
  altText: string
  onAltTextChange: (v: string) => void
  /** True when this block has no explicit alt-text decision recorded
   *  yet (legacy row with ``label = null``, or the writer chose
   *  Remove which resets the state). Save path emits ``null``. */
  altUnset: boolean
  onAltUnsetChange: (v: boolean) => void
  spaceSlug?: string
  uploadBusy: boolean
  uploadError: string | null
  onUploadFile: (file: File) => void
}) {
  const [assetsOpen, setAssetsOpen] = useState(false)
  const [externalError, setExternalError] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement | null>(null)

  const selectedAsset = mediaAssetId
    ? assets.find((a) => a.id === mediaAssetId) ?? null
    : null
  const isSelected = !!selectedAsset || !!embedUrl.trim()
  // ``decorative`` is a specific writer choice: alt-text is intentionally
  // blank for a decorative image. Only ever true when the writer has
  // recorded a decision (``altUnset === false``) and the string is ''.
  const isDecorative = !altUnset && altText === ''

  function pickAsset(id: string | null) {
    onMediaAssetIdChange(id)
    // Picking an asset clears any external URL so the two sources
    // never conflict — the block renders one or the other, not both.
    onEmbedUrlChange('')
    setAssetsOpen(false)
    setExternalError(null)
  }

  function chooseUpload() {
    fileInputRef.current?.click()
  }

  function onFileChosen(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0]
    if (f) onUploadFile(f)
    e.target.value = ''
  }

  function replace() {
    // Return the writer to the source-choice UI without deleting the
    // asset. Clearing both sources hides the preview and re-shows the
    // two big actions. Alt state is preserved so the writer doesn't
    // have to re-type when they pick a similar replacement.
    onMediaAssetIdChange(null)
    onEmbedUrlChange('')
  }

  function remove() {
    // Same as replace() plus a hard alt-state reset — the block is
    // now genuinely empty, so future picks start fresh. The source
    // asset is untouched in the Assets library.
    onMediaAssetIdChange(null)
    onEmbedUrlChange('')
    onAltTextChange('')
    onAltUnsetChange(true)
  }

  function toggleDecorative(next: boolean) {
    if (next) {
      // Turn decorative ON: label = '', altUnset = false. Save path
      // writes '' so the member renderer emits alt="".
      onAltUnsetChange(false)
      onAltTextChange('')
    } else {
      // Turn decorative OFF: return to the "unset" state so the alt
      // input is enabled + empty. A subsequent keystroke flips
      // altUnset back to false, and save writes the entered text.
      // We MUST flip altUnset here — leaving it at ``false`` while
      // keeping the label as ``''`` would keep ``isDecorative`` true
      // and lock the checkbox on (the reported bug).
      onAltUnsetChange(true)
      onAltTextChange('')
      // Focus the freshly-enabled input so the writer can start
      // typing immediately.
      requestAnimationFrame(() => {
        const el = document.querySelector<HTMLInputElement>('input[data-alt-text-input="1"]')
        el?.focus()
      })
    }
  }

  function updateAlt(next: string) {
    // Any keystroke is a definite decision — flip out of "unset".
    onAltUnsetChange(false)
    onAltTextChange(next)
  }

  const externalPreviewSrc = embedUrl.trim() && !selectedAsset ? embedUrl.trim() : null
  const selectedPreviewSrc = selectedAsset ? resolveAssetUrl(selectedAsset.file_url) : null
  const previewSrc = selectedPreviewSrc ?? externalPreviewSrc
  // When the block is selected but the writer has not made an alt
  // decision (legacy or freshly-picked), gently prompt them — they
  // can still save; this is only a soft nudge, not a hard block.
  const showAltNudge = isSelected && altUnset

  return (
    <>
      {/* Hidden file input — triggered by the Upload button. */}
      <input
        ref={fileInputRef}
        type="file"
        accept="image/*"
        className="hidden"
        onChange={onFileChosen}
        disabled={uploadBusy || !spaceSlug}
      />

      {!isSelected && (
        <>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <button
              type="button"
              onClick={() => setAssetsOpen(true)}
              className="group flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-slate-300 bg-white px-4 py-6 text-navy-900 transition-colors hover:border-teal-400 hover:bg-teal-50/40 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400"
            >
              <span className="text-[26px]" aria-hidden="true">🖼</span>
              <span className="text-[14px] font-semibold">Choose from Assets</span>
              <span className="text-[12px] text-slate-600">
                Pick an image already saved to this collective
              </span>
            </button>
            <button
              type="button"
              onClick={chooseUpload}
              disabled={!spaceSlug || uploadBusy}
              className="group flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-slate-300 bg-white px-4 py-6 text-navy-900 transition-colors hover:border-teal-400 hover:bg-teal-50/40 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400 disabled:cursor-not-allowed disabled:opacity-60"
            >
              <span className="text-[26px]" aria-hidden="true">⬆</span>
              <span className="text-[14px] font-semibold">
                {uploadBusy ? 'Uploading…' : 'Upload from your computer'}
              </span>
              <span className="text-[12px] text-slate-600">
                Saved automatically to this collective&apos;s Assets
              </span>
            </button>
          </div>

          {uploadError && (
            <p className="text-[12px] text-red-600">{uploadError}</p>
          )}

          <div className="flex items-center gap-3">
            <div className="h-px flex-1 bg-slate-200" />
            <span className="text-[11px] font-semibold uppercase tracking-widest text-slate-500">OR</span>
            <div className="h-px flex-1 bg-slate-200" />
          </div>

          <div>
            <label className="field-label">External image URL</label>
            <input
              value={embedUrl}
              onChange={(e) => {
                onEmbedUrlChange(e.target.value)
                setExternalError(null)
              }}
              onBlur={() => {
                if (embedUrl.trim() && !isValidHttpUrl(embedUrl.trim())) {
                  setExternalError('URL must start with https:// or http://.')
                } else {
                  setExternalError(null)
                }
              }}
              className="field-input"
              placeholder="https://…"
            />
            <p className="mt-1 text-[11px] text-slate-500">
              External images are not saved into Assets — the source URL must stay reachable.
            </p>
            {externalError && (
              <p className="mt-1 text-[12px] text-red-600">{externalError}</p>
            )}
          </div>
        </>
      )}

      {isSelected && previewSrc && (
        <div className="space-y-3">
          <div className="overflow-hidden rounded-lg border border-slate-200 bg-slate-50">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={previewSrc}
              alt={
                isDecorative
                  ? ''
                  : (altUnset ? (selectedAsset?.title ?? '') : altText)
              }
              className="block w-full object-contain"
              style={{ maxHeight: 420 }}
              onError={(e) => {
                // For external URLs, surface a clear failure so the
                // writer knows to fix the URL rather than silently
                // publishing a broken image.
                if (externalPreviewSrc) {
                  (e.currentTarget as HTMLImageElement).style.display = 'none'
                  setExternalError('The image at this URL could not be loaded.')
                }
              }}
            />
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <div className="min-w-0 flex-1">
              <p className="truncate text-[14px] font-semibold text-navy-900">
                {selectedAsset?.title ?? selectedAsset?.original_filename ?? 'External image'}
              </p>
              {selectedAsset ? (
                <p className="truncate text-[11.5px] text-slate-500">
                  {selectedAsset.original_filename} · from Assets
                </p>
              ) : (
                <p className="truncate text-[11.5px] text-slate-500">
                  External URL · not stored in Assets
                </p>
              )}
            </div>
            <button
              type="button"
              onClick={replace}
              className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-[12.5px] font-semibold text-navy-900 transition-colors hover:border-navy-500 hover:bg-slate-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-500"
              title="Choose or upload a different image (this asset stays in Assets)"
            >
              Replace image
            </button>
            <button
              type="button"
              onClick={remove}
              className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-[12.5px] font-semibold text-red-600 transition-colors hover:border-red-500 hover:bg-red-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-red-400"
              title="Remove the image from this block (the asset stays in Assets)"
            >
              Remove
            </button>
          </div>

          {externalError && externalPreviewSrc && (
            <p className="text-[12px] text-red-600">{externalError}</p>
          )}
        </div>
      )}

      <div>
        <label className="field-label">Caption <span className="text-slate-500">(optional)</span></label>
        <input
          value={caption}
          onChange={(e) => onCaptionChange(e.target.value)}
          className="field-input"
          placeholder="A short caption shown beneath the image"
        />
        <p className="mt-1 text-[11px] text-slate-500">
          Caption is visible to every reader. Alt text is for screen readers — the two are not interchangeable.
        </p>
      </div>

      <div>
        <label className="field-label">Alt text</label>
        <input
          data-alt-text-input="1"
          value={isDecorative ? '' : (altUnset ? '' : altText)}
          onChange={(e) => updateAlt(e.target.value)}
          disabled={isDecorative}
          className="field-input"
          placeholder="Describe what the image shows, for screen readers"
        />
        <p className="mt-1 text-[11px] text-slate-500">
          Alt text should describe the image where appropriate. Skip this only for images that are purely decorative.
        </p>
        <label className="mt-2 inline-flex items-center gap-2 text-[12.5px] text-navy-900">
          <input
            type="checkbox"
            checked={isDecorative}
            onChange={(e) => toggleDecorative(e.target.checked)}
            className="h-4 w-4 rounded border-slate-300 text-teal-600 focus:ring-teal-400"
          />
          Mark as decorative — no alt text needed
        </label>
        {showAltNudge && (
          <p className="mt-2 text-[11.5px] text-amber-700">
            No alt text set yet. Add a short description, or tick <em>Mark as decorative</em> if the image adds no information for screen readers.
          </p>
        )}
      </div>

      {assetsOpen && (
        <AssetGridModal
          assets={assets}
          onPick={pickAsset}
          onClose={() => setAssetsOpen(false)}
          onUploadClick={() => {
            setAssetsOpen(false)
            chooseUpload()
          }}
        />
      )}
    </>
  )
}


/** Basic http(s) URL check — matches ImagePickerField/embedAllowlist
 *  style so writers get consistent feedback across image sources. */
function isValidHttpUrl(raw: string): boolean {
  try {
    const u = new URL(raw)
    return u.protocol === 'http:' || u.protocol === 'https:'
  } catch {
    return false
  }
}


/**
 * Modal grid of the current collective's image assets. Purely visual —
 * clicking a card returns the id via ``onPick``. No delete or rename
 * controls here; those live on the Assets page.
 */
function AssetGridModal({
  assets, onPick, onClose, onUploadClick,
}: {
  assets: CreatorMediaAsset[]
  onPick: (id: string) => void
  onClose: () => void
  onUploadClick: () => void
}) {
  const images = assets.filter((a) => a.media_type === 'image' && a.status === 'active')

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" role="dialog" aria-modal="true" aria-label="Choose from Assets">
      <div className="absolute inset-0 bg-black/40" onClick={onClose} aria-hidden="true" />
      <div className="relative flex w-full max-w-3xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl">
        <div className="flex items-center justify-between border-b border-slate-100 px-6 py-4">
          <h2 className="text-[16px] font-semibold text-navy-900">Choose from Assets</h2>
          <button
            type="button"
            onClick={onClose}
            className="flex h-8 w-8 items-center justify-center rounded text-slate-400 hover:bg-slate-100 hover:text-slate-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400"
            aria-label="Close"
          >
            ✕
          </button>
        </div>

        <div className="max-h-[60vh] overflow-y-auto px-6 py-5">
          {images.length === 0 ? (
            <div className="rounded-xl border border-dashed border-slate-200 p-8 text-center">
              <p className="text-[14px] font-semibold text-navy-900">No images in this collective&apos;s Assets yet.</p>
              <p className="mt-1 text-[12.5px] text-slate-500">
                Upload one now, or drop into the Assets page to add several at once.
              </p>
              <button
                type="button"
                onClick={onUploadClick}
                className="mt-4 inline-flex items-center gap-1.5 rounded-lg px-4 py-2 text-[13px] font-semibold text-white transition-opacity hover:opacity-90"
                style={{ background: '#38A09E' }}
              >
                ⬆ Upload from your computer
              </button>
            </div>
          ) : (
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4">
              {images.map((asset) => (
                <button
                  key={asset.id}
                  type="button"
                  onClick={() => onPick(asset.id)}
                  className="group overflow-hidden rounded-lg border border-slate-200 bg-white text-left transition-colors hover:border-teal-400 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400"
                  title={asset.title || asset.original_filename}
                >
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={resolveAssetUrl(asset.file_url)}
                    alt={asset.title || asset.original_filename}
                    className="block aspect-[4/3] w-full object-cover"
                  />
                  <div className="px-2.5 py-2">
                    <p className="truncate text-[12.5px] font-semibold text-navy-900 group-hover:text-teal-700">
                      {asset.title || asset.original_filename}
                    </p>
                    {asset.title && (
                      <p className="truncate text-[11px] text-slate-500">{asset.original_filename}</p>
                    )}
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}


// ---------------------------------------------------------------------------
// ResourceFields — editor UI for `resource` blocks (picker + optional overrides)
// ---------------------------------------------------------------------------

function ResourceFields({
  resources,
  assets,
  resourceId,
  onResourceIdChange,
  mediaAssetId,
  onMediaAssetIdChange,
  titleOverride,
  onTitleOverrideChange,
  descriptionOverride,
  onDescriptionOverrideChange,
}: {
  resources: CreatorResource[]
  assets: CreatorMediaAsset[]
  resourceId: string | null
  onResourceIdChange: (id: string | null) => void
  mediaAssetId: string | null
  onMediaAssetIdChange: (id: string | null) => void
  titleOverride: string
  onTitleOverrideChange: (v: string) => void
  descriptionOverride: string
  onDescriptionOverrideChange: (v: string) => void
}) {
  // Unified Library picker: files (CreatorMediaAsset) and links
  // (SpaceResource) surface in one dropdown, distinguished by an
  // internal kind. The block writes one FK or the other depending on
  // which item the creator picked.
  const activeAssets = assets.filter(a => a.status === 'active')
  const selectedAsset = mediaAssetId
    ? activeAssets.find(a => a.id === mediaAssetId) ?? null
    : null
  const selectedResource = resourceId
    ? resources.find(r => r.id === resourceId) ?? null
    : null
  const totalItems = activeAssets.length + resources.length
  const compositeValue = selectedAsset
    ? `file:${selectedAsset.id}`
    : selectedResource
      ? `link:${selectedResource.id}`
      : ''

  function handleCompositeChange(value: string) {
    if (!value) {
      onResourceIdChange(null)
      onMediaAssetIdChange(null)
      return
    }
    const [kind, id] = value.split(':', 2)
    if (kind === 'file') {
      onMediaAssetIdChange(id)
    } else {
      onResourceIdChange(id)
    }
  }

  if (totalItems === 0) {
    return (
      <div className="rounded-lg border border-dashed border-slate-200 bg-white p-4 text-center">
        <p className="text-[13px] text-black">Your Library is empty.</p>
        <Link
          href="/creator-studio/library"
          className="mt-1.5 inline-block text-[13px] font-medium text-teal-600 hover:underline"
        >
          Open Library →
        </Link>
        <p className="mt-2 text-[11px] text-black">
          Resource blocks link an existing Library item — they don&apos;t upload a new file.
        </p>
      </div>
    )
  }

  const sortedAssets = [...activeAssets].sort((a, b) => a.title.localeCompare(b.title))
  const sortedResources = [...resources].sort((a, b) => a.title.localeCompare(b.title))

  return (
    <>
      <div>
        <label className="field-label">Library item</label>
        <select
          value={compositeValue}
          onChange={e => handleCompositeChange(e.target.value)}
          className="field-input"
          autoFocus
        >
          <option value="">— Select from Library —</option>
          {sortedAssets.length > 0 && (
            <optgroup label="Files">
              {sortedAssets.map(a => (
                <option key={`file:${a.id}`} value={`file:${a.id}`}>
                  {a.title} · {a.media_type}
                </option>
              ))}
            </optgroup>
          )}
          {sortedResources.length > 0 && (
            <optgroup label="Links & Documents">
              {sortedResources.map(r => {
                const draft = r.status !== 'published'
                return (
                  <option key={`link:${r.id}`} value={`link:${r.id}`}>
                    {r.title} · {r.resource_type}{draft ? ' · Draft' : ''}
                  </option>
                )
              })}
            </optgroup>
          )}
        </select>
        <p className="mt-1 text-[11px] text-black">
          Pick a file or link from the Library. Edits to the item flow through
          to every step that embeds it.
        </p>
      </div>

      {selectedAsset && (
        <div className="rounded-lg border border-slate-100 bg-slate-50 p-3">
          <p className="text-[13px] font-semibold text-navy-900">{selectedAsset.title}</p>
          {selectedAsset.description && (
            <p className="mt-0.5 text-[12px] leading-snug text-black">{selectedAsset.description}</p>
          )}
          <p className="mt-1.5 text-[11px] text-black">
            {selectedAsset.media_type} · {selectedAsset.original_filename}
          </p>
        </div>
      )}

      {selectedResource && (
        <div className="rounded-lg border border-slate-100 bg-slate-50 p-3">
          <p className="text-[13px] font-semibold text-navy-900">{selectedResource.title}</p>
          {selectedResource.description && (
            <p className="mt-0.5 text-[12px] leading-snug text-black">{selectedResource.description}</p>
          )}
          <p className="mt-1.5 text-[11px] text-black">
            {selectedResource.resource_type}
            {selectedResource.status !== 'published' && (
              <span className="ml-1 font-semibold text-amber-700">· Draft (hidden from members)</span>
            )}
          </p>
        </div>
      )}

      <div>
        <label className="field-label">
          Title for this step <span className="text-black">(optional)</span>
        </label>
        <input
          value={titleOverride}
          onChange={e => onTitleOverrideChange(e.target.value)}
          className="field-input"
          placeholder={
            selectedAsset?.title
              ?? selectedResource?.title
              ?? 'Leave blank to use the Library item title'
          }
        />
      </div>

      <div>
        <label className="field-label">
          Description for this step <span className="text-black">(optional)</span>
        </label>
        <input
          value={descriptionOverride}
          onChange={e => onDescriptionOverrideChange(e.target.value)}
          className="field-input"
          placeholder={
            selectedAsset?.description
              ?? selectedResource?.description
              ?? 'Leave blank to use the Library item description'
          }
        />
      </div>
    </>
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
  resources = [],
  isActive,
  onActivate,
  onDeactivate,
  initialEditing,
  onMoveUp,
  onMoveDown,
  onDelete,
  onUpdate,
  spaceSlug,
  onAssetUploaded,
  hideMoveButtons,
  dragHandle,
}: {
  block: EditorBlock
  index: number
  total: number
  assets: CreatorMediaAsset[]
  resources?: CreatorResource[]
  /** Whether this block is currently the single active editor. Only
   *  one block is active at a time; the parent lifts this state so
   *  opening one collapses the others. */
  isActive?: boolean
  onActivate?: () => void
  onDeactivate?: () => void
  /** Legacy: open the block immediately on mount. Used by
   *  ``AboutPageEditor`` which has not yet migrated to the lifted
   *  active-editor model. Ignored when ``onActivate`` is passed. */
  initialEditing?: boolean
  onMoveUp: () => void
  onMoveDown: () => void
  onDelete: () => void
  onUpdate: (patch: Record<string, unknown>) => Promise<void>
  spaceSlug?: string
  onAssetUploaded?: (asset: CreatorMediaAsset) => void
  /** When true, the up/down arrow gutter is suppressed. Callers using
   *  drag-and-drop reordering set this so the block card has a single
   *  reorder affordance instead of two. */
  hideMoveButtons?: boolean
  /** Optional element rendered in the left gutter — the DraggableBlockList
   *  passes a drag handle so drag lives inside the card, not clipped
   *  outside it. */
  dragHandle?: React.ReactNode
}) {
  // ``editing`` follows ``isActive`` when the parent lifts state; falls
  // back to local when a caller (AboutPageEditor still on the old path)
  // does not provide the props.
  const parentControlled = onActivate !== undefined
  const [localEditing, setLocalEditing] = useState(!!initialEditing)
  const editing = parentControlled ? !!isActive : localEditing
  const setEditing = (v: boolean) => {
    if (parentControlled) {
      if (v) onActivate?.()
      else onDeactivate?.()
    } else {
      setLocalEditing(v)
    }
  }

  const [saving, setSaving] = useState(false)
  const [autosaveStatus, setAutosaveStatus] = useState<'idle' | 'saving' | 'saved'>('idle')
  const autosaveSavedTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const [confirmingDelete, setConfirmingDelete] = useState(false)

  async function handleSave(patch: Record<string, unknown>) {
    setSaving(true)
    await onUpdate(patch)
    setSaving(false)
    setEditing(false)
  }

  /** Autosave path — persist without closing the edit form. */
  async function handleAutosave(patch: Record<string, unknown>) {
    setAutosaveStatus('saving')
    try {
      await onUpdate(patch)
      setAutosaveStatus('saved')
      if (autosaveSavedTimer.current) clearTimeout(autosaveSavedTimer.current)
      autosaveSavedTimer.current = setTimeout(() => setAutosaveStatus('idle'), 1500)
    } catch {
      setAutosaveStatus('idle')
    }
  }

  // Prose-shaped blocks read as ordinary document paragraphs — clicking
  // them enters edit mode directly (Notion-style). Structured blocks
  // (button, embed, resource, video, file, image) keep their explicit
  // edit affordance so the click target for "open configuration" is
  // predictable.
  const isProseBlock = ['text', 'heading', 'callout', 'reflection_prompt', 'exercise'].includes(block.block_type)

  return (
    <div
      className={`group/row relative flex items-start gap-1 ${editing ? 'py-2' : 'py-1'}`}
    >
      {/* Left gutter — arrow buttons (legacy) OR the drag handle (new).
          Fixed narrow width so content flows in a single column. */}
      {hideMoveButtons ? (
        <div className="flex w-5 shrink-0 items-start pt-2 transition-opacity opacity-100 focus-within:opacity-100 sm:opacity-0 sm:group-hover/row:opacity-100">
          {dragHandle}
        </div>
      ) : (
        <div className="flex w-8 shrink-0 flex-col gap-1 pt-0.5">
          <button
            type="button"
            onClick={onMoveUp}
            disabled={index === 0}
            className="flex h-6 w-6 items-center justify-center rounded text-[12px] text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700 disabled:opacity-20"
            title="Move up"
          >↑</button>
          <button
            type="button"
            onClick={onMoveDown}
            disabled={index === total - 1}
            className="flex h-6 w-6 items-center justify-center rounded text-[12px] text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700 disabled:opacity-20"
            title="Move down"
          >↓</button>
        </div>
      )}

      {/* The block body itself. In preview mode it flows as document
          content — no borders, no padding, no chrome. In edit mode a
          single light teal left-border marks the active surface for
          both prose and structured blocks, unifying the editorial
          language across every block type. */}
      <div
        className={`min-w-0 flex-1 ${editing ? 'border-l-2 border-teal-400 pl-4' : ''}`}
      >
        {!editing && (
          <>
            {/* Type badge sits ABOVE the preview and is dimmed until hover
                — the reader's eye lands on content, not on chrome. Neutral
                slate so it reads as a quiet orientation label rather than
                a branded chip. */}
            <div
              className="mb-1 flex items-center gap-2 text-[10.5px] font-medium uppercase tracking-[0.14em] text-slate-400 transition-opacity opacity-100 focus-within:opacity-100 sm:opacity-0 sm:group-hover/row:opacity-100"
              aria-hidden="true"
            >
              <span>{blockIcon(block.block_type)}</span>
              <span>{blockBadgeLabel(block)}</span>
            </div>
            <div
              className={isProseBlock ? 'cursor-text' : ''}
              onClick={isProseBlock ? () => setEditing(true) : undefined}
              onKeyDown={isProseBlock ? (e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault()
                  setEditing(true)
                }
              } : undefined}
              tabIndex={isProseBlock ? 0 : -1}
              role={isProseBlock ? 'button' : undefined}
              aria-label={isProseBlock ? `Edit ${blockLabel(block.block_type)}` : undefined}
            >
              <BlockPreview block={block} assets={assets} resources={resources} />
            </div>
          </>
        )}

        {editing && (
          <>
            {/* Edit-mode header — a quiet uppercase micro-label in neutral
                slate. The teal left-accent border already tells the writer
                which block is active; the label doesn't need to repeat the
                signal in colour. Autosave "Saved" keeps a subtle teal
                because it IS a live state, not chrome. */}
            <div className="mb-3 flex items-center gap-3">
              <span className="flex items-center gap-1.5 text-[10.5px] font-semibold uppercase tracking-[0.14em] text-slate-500">
                <span>{blockIcon(block.block_type)}</span>
                <span>{blockBadgeLabel(block)}</span>
              </span>
              {autosaveStatus !== 'idle' && (
                <span
                  className="text-[11.5px] italic"
                  style={{ color: autosaveStatus === 'saving' ? 'rgba(0,0,0,0.40)' : '#0f766e' }}
                >
                  {autosaveStatus === 'saving' ? 'Saving…' : 'Saved'}
                </span>
              )}
            </div>
            <BlockEditForm
              block={block}
              assets={assets}
              resources={resources}
              onSave={handleSave}
              onAutosave={handleAutosave}
              onCancel={() => setEditing(false)}
              onDeleteRequested={() => setConfirmingDelete(true)}
              saving={saving}
              spaceSlug={spaceSlug}
              onAssetUploaded={onAssetUploaded}
            />
          </>
        )}
      </div>

      {/* Right gutter — Edit + Delete controls, PREVIEW STATE ONLY.
          Ghost-style icon buttons: no border, no background at rest,
          soft-tinted hover. The chrome disappears completely into the
          document until the writer approaches the row. In edit mode
          this gutter is dropped so the writing surface has the full
          canvas; Delete lives inside the editor footer instead. */}
      {!editing && (
      <div className="flex w-16 shrink-0 items-center justify-end gap-0.5 pt-1 transition-opacity opacity-100 focus-within:opacity-100 sm:opacity-0 sm:group-hover/row:opacity-100 sm:pt-2">
        <button
          type="button"
          onClick={() => setEditing(true)}
          className="flex h-7 w-7 items-center justify-center rounded-md text-slate-400 transition-colors hover:bg-slate-100 hover:text-navy-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400"
          title="Edit block"
          aria-label="Edit block"
        >
          <PencilIcon />
        </button>
        <button
          type="button"
          onClick={() => setConfirmingDelete(true)}
          className="flex h-7 w-7 items-center justify-center rounded-md text-slate-400 transition-colors hover:bg-red-50 hover:text-red-500 focus:outline-none focus-visible:ring-2 focus-visible:ring-red-400"
          title="Delete block"
          aria-label="Delete block"
        >
          <TrashIcon />
        </button>
      </div>
      )}

      {/* Delete confirmation — a compact modal centred on screen. */}
      {confirmingDelete && (
        <DeleteBlockConfirm
          onCancel={() => setConfirmingDelete(false)}
          onConfirm={() => {
            setConfirmingDelete(false)
            onDelete()
          }}
        />
      )}
    </div>
  )
}


/** Solid pencil icon — the "edit block" affordance for prose rows. */
function PencilIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M4 20h4l10.5-10.5-4-4L4 16v4zM14.5 5.5l4 4"
        stroke="currentColor"
        strokeWidth="1.7"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}


/** Solid trash icon — clear destructive signal, no ambiguity with "close". */
function TrashIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M4 7h16M9 7V5a1 1 0 011-1h4a1 1 0 011 1v2m-9 0v12a1 1 0 001 1h8a1 1 0 001-1V7M10 11v6M14 11v6"
        stroke="currentColor"
        strokeWidth="1.7"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}


/**
 * DeleteBlockConfirm — plain-language dialog gate before we destroy a
 * block. Keyboard-friendly (Escape cancels, Enter confirms), traps
 * click-outside to cancel.
 */
function DeleteBlockConfirm({ onCancel, onConfirm }: { onCancel: () => void; onConfirm: () => void }) {
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onCancel()
      if (e.key === 'Enter') onConfirm()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onCancel, onConfirm])

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onCancel() }}
      role="dialog"
      aria-modal="true"
      aria-labelledby="wg-delete-block-title"
    >
      <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-xl">
        <h2 id="wg-delete-block-title" className="mb-2 font-serif text-[20px] text-navy-900">
          Delete this block?
        </h2>
        <p className="mb-5 text-[13.5px] leading-relaxed text-black">
          This block and its contents will be permanently removed. This cannot be undone.
        </p>
        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="rounded-full border border-slate-300 bg-white px-4 py-1.5 text-[13px] font-semibold text-navy-900 transition-colors hover:border-slate-400 hover:bg-slate-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400"
          >
            Go back
          </button>
          <button
            type="button"
            onClick={onConfirm}
            autoFocus
            className="rounded-full bg-red-600 px-4 py-1.5 text-[13px] font-semibold text-white transition-opacity hover:opacity-90 focus:outline-none focus-visible:ring-2 focus-visible:ring-red-400"
          >
            Delete block
          </button>
        </div>
      </div>
    </div>
  )
}


// ---------------------------------------------------------------------------
// PromptEditor — Reflection prompt purpose-built editor
// ---------------------------------------------------------------------------


/**
 * Reflection Prompt editing surface. Deliberately not a rich-text
 * document editor: a prompt is one intentional question, not a piece
 * of prose. The main field is a serif italic autosizing textarea; a
 * small plain-text supporting-context field sits below it. No
 * toolbar, no palette, no Save button — autosave carries changes.
 */
function PromptEditor({
  content, caption,
  onContentChange, onCaptionChange,
  onAutosave, onDone, onDeleteRequested,
}: {
  content: string
  caption: string
  onContentChange: (v: string) => void
  onCaptionChange: (v: string) => void
  onAutosave?: () => void
  onDone: () => void
  onDeleteRequested?: () => void
}) {
  const promptRef = useRef<HTMLTextAreaElement | null>(null)
  const debounce = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Autoresize on content change so the prompt stays fully visible.
  useEffect(() => {
    const ta = promptRef.current
    if (!ta) return
    ta.style.height = 'auto'
    ta.style.height = `${Math.max(ta.scrollHeight, 96)}px`
  }, [content])

  // Autosave on either field change.
  useEffect(() => {
    if (!onAutosave) return
    if (debounce.current) clearTimeout(debounce.current)
    debounce.current = setTimeout(() => onAutosave(), 700)
    return () => { if (debounce.current) clearTimeout(debounce.current) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [content, caption])

  return (
    <div className="w-full">
      <div className="mb-2 flex items-center gap-2 text-[10.5px] font-semibold uppercase tracking-[0.16em] text-slate-500">
        <span aria-hidden="true" className="text-[15px] leading-none">❝</span>
        Reflection prompt
      </div>
      <textarea
        ref={promptRef}
        value={content}
        onChange={(e) => onContentChange(e.target.value)}
        placeholder="What would you like the member to pause and consider?"
        rows={2}
        className="block w-full resize-none border-0 bg-transparent p-0 font-serif text-[22px] leading-snug italic text-navy-900 outline-none placeholder:text-slate-400"
        style={{ fontFamily: 'Georgia, "Times New Roman", serif' }}
        autoFocus
      />
      <div className="mt-4">
        <label className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-slate-600">
          Supporting context (optional)
        </label>
        <input
          value={caption}
          onChange={(e) => onCaptionChange(e.target.value)}
          className="block w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-[14px] text-black outline-none focus:border-teal-400"
          placeholder="A short note to give this prompt context."
        />
      </div>
      <div className="mt-5 flex items-center">
        {onDeleteRequested && (
          <button
            type="button"
            onClick={onDeleteRequested}
            className="rounded-full border border-slate-300 bg-white px-3.5 py-1.5 text-[13px] font-semibold text-red-600 transition-colors hover:border-red-500 hover:bg-red-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-red-400"
          >
            Delete block
          </button>
        )}
        <div className="flex-1" />
        <button
          type="button"
          onClick={onDone}
          className="rounded-full border border-slate-300 bg-white px-4 py-1.5 text-[13px] font-semibold text-navy-900 transition-colors hover:border-navy-500 hover:bg-slate-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-500"
        >
          Done
        </button>
      </div>
    </div>
  )
}


// Exercise no longer has a specialised editor — it flows through the
// shared BlockEditForm's Content branch with an optional Title input.
// ``exerciseContentToRichText`` in @/lib/exerciseSteps migrates legacy
// step-envelope rows to TipTap JSON on load so writers keep their
// history without needing a data migration.


// ---------------------------------------------------------------------------
// ColumnsPreview + ColumnsEditor — multi-column layout block
// ---------------------------------------------------------------------------


/**
 * Read-only preview shown inside the pathway editor's block stack.
 * Renders the CSS grid at authoring width, stacks on mobile, and shows
 * a hairline empty-state for cells the writer hasn't filled yet.
 */
function ColumnsPreview({ content }: { content: string | null }) {
  const payload = decodeColumns(content)
  return (
    <div className="my-1">
      <div
        className="fc-columns-grid grid gap-4 sm:gap-5"
        style={{ ['--fc-cols' as string]: gridTemplateForVariant(payload.layout.variant) }}
      >
        {payload.cells.map((cell, i) => (
          <div
            key={i}
            className="min-w-0 rounded-md border border-slate-200 bg-white p-3 text-[14.5px] leading-relaxed text-black"
          >
            {cell.content?.trim()
              ? <RichTextRenderer content={cell.content} />
              : <span className="italic text-slate-400">Column {i + 1} — click Edit to add content.</span>}
          </div>
        ))}
      </div>
    </div>
  )
}


/**
 * Purpose-built editor for the columns block. Renders one RichTextEditor
 * per cell inside a CSS grid whose template mirrors the chosen variant.
 * Layout selection sits above the grid; changing the variant preserves
 * as many cells as still fit.
 *
 * The block's ``content`` column stores the ``ColumnsPayload`` JSON
 * envelope — no schema changes are needed.
 */
function ColumnsEditor({
  content, onContentChange, onAutosave, onDone, onDeleteRequested,
}: {
  content: string
  onContentChange: (v: string) => void
  onAutosave?: () => void
  onDone: () => void
  onDeleteRequested?: () => void
}) {
  const [payload, setPayload] = useState<ColumnsPayload>(() => decodeColumns(content))
  const debounce = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    onContentChange(encodeColumns(payload))
    if (!onAutosave) return
    if (debounce.current) clearTimeout(debounce.current)
    debounce.current = setTimeout(() => onAutosave(), 700)
    return () => { if (debounce.current) clearTimeout(debounce.current) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [payload])

  function updateCell(i: number, value: string) {
    setPayload((prev) => ({
      ...prev,
      cells: prev.cells.map((c, j) => (j === i ? { ...c, content: value } : c)),
    }))
  }

  function changeVariant(v: ColumnsVariant) {
    setPayload((prev) => resizeColumns(prev, v))
  }

  return (
    <div className="w-full">
      <div className="mb-2 flex items-center gap-2 text-[10.5px] font-semibold uppercase tracking-[0.16em] text-slate-700">
        <span aria-hidden="true" className="text-[13px]">▥</span>
        Columns
      </div>

      <label className="mb-1.5 block text-[11px] font-semibold uppercase tracking-wide text-slate-600">
        Layout
      </label>
      <div className="mb-4 flex flex-wrap gap-2.5">
        {COLUMNS_VARIANTS.map((v) => {
          const selected = payload.layout.variant === v
          return (
            <button
              key={v}
              type="button"
              onClick={() => changeVariant(v)}
              className={`flex flex-col items-center gap-1.5 rounded-lg border px-3 py-2 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400 ${
                selected
                  ? 'border-teal-500 bg-teal-50 ring-2 ring-teal-200'
                  : 'border-slate-200 bg-white hover:border-teal-300'
              }`}
              aria-pressed={selected}
              title={labelForVariant(v)}
              aria-label={labelForVariant(v)}
            >
              <span
                className="grid h-6 w-[52px] gap-[3px]"
                style={{ gridTemplateColumns: gridTemplateForVariant(v) }}
                aria-hidden="true"
              >
                {Array.from({ length: cellCountForVariant(v) }).map((_, i) => (
                  <span
                    key={i}
                    className="rounded-[3px]"
                    style={{ background: selected ? '#38A09E' : 'rgba(15,23,42,0.22)' }}
                  />
                ))}
              </span>
              <span
                className={`text-[11px] font-semibold leading-none ${selected ? 'text-teal-700' : 'text-navy-900'}`}
              >
                {variantShortLabel(v)}
              </span>
            </button>
          )
        })}
      </div>

      <div
        className="fc-columns-grid grid gap-4"
        style={{ ['--fc-cols' as string]: gridTemplateForVariant(payload.layout.variant) }}
      >
        {payload.cells.map((cell, i) => (
          <div key={i} className="min-w-0">
            <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
              Column {i + 1}
            </div>
            <RichTextEditor
              content={cell.content}
              onChange={(next) => updateCell(i, next)}
              placeholder={`Column ${i + 1}…`}
              minRows={6}
            />
          </div>
        ))}
      </div>

      <p className="mt-3 text-[12px] text-slate-500">
        Columns stack vertically on narrow screens so each cell remains readable on mobile.
      </p>

      <div className="mt-5 flex items-center">
        {onDeleteRequested && (
          <button
            type="button"
            onClick={onDeleteRequested}
            className="rounded-full border border-slate-300 bg-white px-3.5 py-1.5 text-[13px] font-semibold text-red-600 transition-colors hover:border-red-500 hover:bg-red-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-red-400"
          >
            Delete block
          </button>
        )}
        <div className="flex-1" />
        <button
          type="button"
          onClick={onDone}
          className="rounded-full border border-slate-300 bg-white px-4 py-1.5 text-[13px] font-semibold text-navy-900 transition-colors hover:border-navy-500 hover:bg-slate-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-500"
        >
          Done
        </button>
      </div>
    </div>
  )
}


