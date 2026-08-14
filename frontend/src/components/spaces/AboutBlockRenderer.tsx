import React from 'react'
import type { CollectivePaletteMeta } from '@/lib/collectivePalette'
import {
  resolveCalloutPalette,
  resolveCalloutPurposeIcon,
  resolveCalloutPurposeLabel,
  resolveContainerPalette,
} from '@/lib/calloutPalette'
import RichTextRenderer from '@/components/RichTextRenderer'
import EmbedRenderer from '@/components/EmbedRenderer'
import ButtonBlock from '@/components/ButtonBlock'
import { decodeColumns, gridTemplateForVariant } from '@/lib/columnsBlock'
import { exerciseContentToRichText } from '@/lib/exerciseSteps'
import type { PathwayAboutBlock, StepBlockMedia } from '@/types/platform'

/**
 * AboutBlockRenderer
 *
 * Shared, owner-agnostic block renderer for About pages. The
 * ``pathway_about_blocks`` table is polymorphic (migration 113 —
 * ``owner_kind`` + ``owner_id``) and can carry Pathway or
 * Gathering Series content, so the renderer lives here and both
 * consumers import from this file:
 *
 *   * ``/spaces/[slug]/pathways/[pathway-slug]/about/page.tsx``
 *   * ``/spaces/[slug]/gathering-series/[series-slug]/page.tsx``
 *
 * The two pages differ in how they *lay out* the page (header,
 * ways-to-join, gatherings list) but the block-rendering logic
 * itself is identical. Extracting it here removes the temptation
 * to write a second renderer that drifts.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

export function resolveAssetUrl(url: string): string {
  if (url.startsWith('http')) return url
  return url.startsWith('/') ? `${API_BASE}${url}` : `${API_BASE}/api/uploads/${url}`
}

function getEmbedUrl(raw: string): string | null {
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
  } catch { /* fall through */ }
  return null
}

/** Container-aware wrapper around a single block. Owner-agnostic. */
export function AboutBlockRenderer({
  block, collectivePalette,
}: {
  block: PathwayAboutBlock
  collectivePalette: CollectivePaletteMeta | null
}) {
  const inner = renderInner(block, collectivePalette)
  if (inner == null) return null
  const palette = resolveContainerPalette(block.container_style, collectivePalette)
  if (!palette) return inner
  return (
    <div
      className="rounded-xl border px-5 py-5"
      style={{ background: palette.bg, borderColor: palette.border }}
    >
      {inner}
    </div>
  )
}

function renderInner(
  block: PathwayAboutBlock,
  collectivePalette: CollectivePaletteMeta | null,
): React.ReactElement | null {
  const t = block.block_type
  const asset = block.media_asset as StepBlockMedia | null
  const wrapped = !!resolveContainerPalette(block.container_style, collectivePalette)

  if (t === 'divider') return <hr className="border-slate-200" />

  if (t === 'columns') {
    const payload = decodeColumns(block.content)
    return (
      <div
        className="fc-columns-grid grid gap-6"
        style={{ ['--fc-cols' as string]: gridTemplateForVariant(payload.layout.variant) }}
      >
        {payload.cells.map((cell, i) => (
          <div key={i} className="min-w-0 prose prose-sm max-w-none text-black">
            {cell.content?.trim() ? <RichTextRenderer content={cell.content} /> : null}
          </div>
        ))}
      </div>
    )
  }

  if (t === 'heading') {
    const level = block.label ?? 'h2'
    const classes = level === 'h1'
      ? 'font-serif text-3xl text-navy-900'
      : level === 'h3'
      ? 'font-serif text-xl font-semibold text-navy-900'
      : 'font-serif text-2xl text-navy-900'
    return <p className={classes}>{block.content}</p>
  }

  if (t === 'text') return (
    <div className="prose prose-sm max-w-none text-black">
      <RichTextRenderer content={block.content} />
    </div>
  )

  if (t === 'image') {
    const src = asset ? resolveAssetUrl(asset.file_url) : block.embed_url
    if (!src) return null
    // ``label`` semantics (unchanged from the original renderer):
    //   * null → legacy row; fall back to asset.title.
    //   * ''   → decorative; ``alt=""`` wins.
    //   * '…'  → writer's explicit alt text.
    const alt = block.label ?? asset?.title ?? ''
    return (
      <figure>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={src} alt={alt} className="w-full rounded-xl object-cover" />
        {block.caption && (
          <figcaption className="mt-2 text-center text-[12px] text-black">{block.caption}</figcaption>
        )}
      </figure>
    )
  }

  if (t === 'video_embed') {
    const embed = block.embed_url ? getEmbedUrl(block.embed_url) : null
    if (embed) {
      return (
        <figure>
          <div className="overflow-hidden rounded-xl bg-black" style={{ aspectRatio: '16/9' }}>
            <iframe
              src={embed}
              className="h-full w-full"
              allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
              allowFullScreen
            />
          </div>
          {block.caption && (
            <figcaption className="mt-2 text-center text-[12px] text-black">{block.caption}</figcaption>
          )}
        </figure>
      )
    }
    if (block.embed_url) {
      return (
        <a
          href={block.embed_url}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-2 rounded-xl border border-border bg-white px-4 py-3 text-[14px] font-medium text-[color:var(--fc-accent,#0f766e)] transition-colors hover:border-[color:var(--fc-accent-line,rgba(56,160,158,0.30))]"
        >
          <span>▶</span>
          {block.caption || block.embed_url}
        </a>
      )
    }
    return null
  }

  if (t === 'audio') {
    if (!asset) return null
    return (
      <div className={wrapped ? '' : 'rounded-xl border border-border bg-white p-4'}>
        {block.caption && <p className="mb-2 text-[13px] font-medium text-navy-900">{block.caption}</p>}
        <audio controls className="w-full" src={resolveAssetUrl(asset.file_url)} />
      </div>
    )
  }

  if (t === 'file_download') {
    if (!asset) return null
    return (
      <a
        href={resolveAssetUrl(asset.file_url)}
        download
        className="flex items-center gap-3 rounded-xl border border-border bg-white px-5 py-3.5 transition-colors hover:border-[color:var(--fc-accent-line,rgba(56,160,158,0.30))]"
      >
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-lg"
          style={{
            background: 'var(--fc-accent-soft, rgba(56,160,158,0.08))',
            color: 'var(--fc-accent, #0f766e)',
          }}>
          ↓
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-[14px] font-semibold text-navy-900">{block.label || asset.title}</p>
          <p className="text-[12px] text-black">{asset.original_filename}</p>
        </div>
      </a>
    )
  }

  if (t === 'link') {
    if (!block.embed_url) return null
    return (
      <a
        href={block.embed_url}
        target="_blank"
        rel="noopener noreferrer"
        className="flex items-center gap-3 rounded-xl border border-border bg-white px-5 py-3.5 transition-colors hover:border-[color:var(--fc-accent-line,rgba(56,160,158,0.30))]"
      >
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-lg"
          style={{
            background: 'var(--fc-accent-soft, rgba(56,160,158,0.08))',
            color: 'var(--fc-accent, #0f766e)',
          }}>
          🔗
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-[14px] font-semibold text-navy-900">{block.label || block.embed_url}</p>
          {block.caption && <p className="text-[12px] text-black">{block.caption}</p>}
        </div>
        <span className="shrink-0 text-black">→</span>
      </a>
    )
  }

  if (t === 'reflection_prompt') return (
    <div
      className={wrapped ? '' : 'rounded-xl border-l-4 py-4 pl-5 pr-4'}
      style={wrapped ? undefined : {
        borderColor: 'var(--fc-accent-line, #5eead4)',
        background: 'var(--fc-accent-soft, rgba(240,253,250,0.60))',
      }}
    >
      <p
        className="mb-1.5 text-[10px] font-bold uppercase tracking-widest"
        style={{ color: 'var(--fc-accent, #0d9488)' }}
      >Reflection</p>
      <div className="text-[15px] italic leading-relaxed text-black">
        <RichTextRenderer content={block.content} />
      </div>
    </div>
  )

  if (t === 'exercise') {
    const body = exerciseContentToRichText(block.content)
    return (
      <div className={wrapped ? '' : 'rounded-xl border border-slate-200 bg-white px-5 py-4'}>
        <p className="mb-1 flex items-center gap-2 text-[10.5px] font-semibold uppercase tracking-[0.16em] text-slate-700">
          <span aria-hidden="true" className="text-[13px]">✏</span>
          Exercise
        </p>
        {block.label && (
          <p className="mt-0.5 mb-3 font-serif text-[19px] leading-tight text-navy-900">
            {block.label}
          </p>
        )}
        {body && (
          <div className="text-[14px] leading-relaxed text-black">
            <RichTextRenderer content={body} />
          </div>
        )}
      </div>
    )
  }

  if (t === 'callout') {
    const palette = resolveCalloutPalette(block.caption, block.label, undefined, collectivePalette)
    const icon = resolveCalloutPurposeIcon(block.label)
    const purposeLabel = resolveCalloutPurposeLabel(block.label)
    return (
      <div
        className="rounded-xl border px-5 py-4"
        style={{ background: palette.bg, borderColor: palette.border }}
      >
        {purposeLabel && (
          <p
            className="mb-2 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-widest"
            style={{ color: palette.border }}
          >
            {icon && <span aria-hidden="true" className="text-[13px] leading-none">{icon}</span>}
            <span>{purposeLabel}</span>
          </p>
        )}
        <div className="text-[14px] leading-relaxed text-black">
          <RichTextRenderer content={block.content} />
        </div>
      </div>
    )
  }

  if (t === 'embed' && block.embed_url) {
    return (
      <figure>
        {block.label && (
          <p className="mb-2 text-[11px] font-semibold uppercase tracking-widest text-black">
            {block.label}
          </p>
        )}
        <EmbedRenderer url={block.embed_url} title={block.label ?? undefined} />
        {block.caption && (
          <figcaption className="mt-2 text-center text-[12px] text-slate-400">
            {block.caption}
          </figcaption>
        )}
      </figure>
    )
  }

  if (t === 'button' && block.embed_url && block.label) {
    const newTab = block.content === 'new_tab' || block.content === 'same_tab' ? block.content : null
    return (
      <ButtonBlock
        href={block.embed_url}
        text={block.label}
        caption={block.caption ?? null}
        collectivePalette={collectivePalette}
        newTabPref={newTab}
      />
    )
  }

  if (t === 'resource') {
    const r = block.resource
    if (!r || r.status !== 'published') return null
    const title = block.label || r.title
    const description = block.caption || r.description
    const href = r.url ? (r.url.startsWith('http') ? r.url : `${API_BASE}${r.url.startsWith('/') ? r.url : `/api/uploads/${r.url}`}`) : null
    if (!href) return null
    const isFile = !!r.file_name || ['file', 'guide', 'template', 'replay', 'audio', 'video'].includes(r.resource_type)
    const ctaLabel = isFile ? 'Download resource' : 'Open resource'
    return (
      <a
        href={href}
        target={isFile ? undefined : '_blank'}
        rel={isFile ? undefined : 'noopener noreferrer'}
        download={isFile && r.file_name ? r.file_name : undefined}
        className="group flex items-start gap-4 rounded-xl border border-border bg-white px-5 py-4 transition-colors hover:border-[color:var(--fc-accent-ring,rgba(56,160,158,0.40))]"
      >
        <span
          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg text-[16px]"
          style={{
            background: 'var(--fc-accent-soft, rgba(56,160,158,0.08))',
            color: 'var(--fc-accent, #0f766e)',
          }}
        >
          ◰
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <p className="truncate text-[15px] font-semibold text-navy-900 group-hover:text-[color:var(--fc-accent,#0f766e)]">{title}</p>
            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-slate-500">
              {r.resource_type}
            </span>
          </div>
          {description && (
            <p className="mt-1 text-[13px] leading-relaxed text-black">{description}</p>
          )}
        </div>
        <span className="shrink-0 self-center rounded-full border border-border bg-white px-3 py-1.5 text-[12px] font-medium text-black group-hover:border-[color:var(--fc-accent-ring,rgba(56,160,158,0.40))] group-hover:text-[color:var(--fc-accent,#0f766e)]">
          {ctaLabel} {isFile ? '↓' : '↗'}
        </span>
      </a>
    )
  }

  return null
}
