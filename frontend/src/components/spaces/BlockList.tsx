import React from 'react'
import type { StepBlock } from '@/types/platform'
import type { CollectivePaletteMeta } from '@/lib/collectivePalette'
import {
  resolveCalloutPalette,
  resolveCalloutPurposeIcon,
  resolveCalloutPurposeLabel,
  resolveContainerPalette,
} from '@/lib/calloutPalette'
import { exerciseContentToRichText } from '@/lib/exerciseSteps'
import { decodeColumns } from '@/lib/columnsBlock'
import ColumnsGrid from '@/components/spaces/ColumnsGrid'
import RichTextRenderer from '@/components/RichTextRenderer'
import EmbedRenderer from '@/components/EmbedRenderer'
import ButtonBlock from '@/components/ButtonBlock'
import MediaBlockHeading from '@/components/spaces/MediaBlockHeading'
import ExerciseResponse from '@/components/spaces/ExerciseResponse'
import { resolveMediaUrl } from '@/lib/api'
import { safeHref } from '@/lib/safeHref'

/**
 * BlockList — the single renderer for pathway-step blocks.
 *
 * Both the Guided Experience per-step page and the Knowledge Guide
 * continuous document render blocks through this component so a
 * change to, say, how a callout looks propagates to both surfaces
 * automatically. There is deliberately no branching on pathway type
 * here — a block renders identically regardless of the presentation
 * that wraps it.
 */

function resolveUrl(url: string): string {
  // Thin wrapper around ``resolveMediaUrl`` (the shared same-origin
  // resolver) — keeps the string-in/string-out shape the callers
  // below expect. See ``lib/api.ts:resolveMediaUrl`` for behaviour.
  return resolveMediaUrl(url) ?? url
}

function getVideoEmbed(url: string): string | null {
  try {
    const u = new URL(url)
    if (u.hostname.includes('youtube.com')) {
      const id = u.searchParams.get('v')
      return id ? `https://www.youtube.com/embed/${id}` : null
    }
    if (u.hostname.includes('youtu.be')) {
      const id = u.pathname.slice(1)
      return id ? `https://www.youtube.com/embed/${id}` : null
    }
    if (u.hostname.includes('vimeo.com')) {
      const id = u.pathname.split('/').filter(Boolean).pop()
      return id ? `https://player.vimeo.com/video/${id}` : null
    }
    if (u.hostname.includes('loom.com') && u.pathname.includes('/share/')) {
      const id = u.pathname.split('/share/')[1]?.split('?')[0]
      return id ? `https://www.loom.com/embed/${id}` : null
    }
  } catch {}
  return null
}

/**
 * Wrap a rendered block in a soft-coloured container when block.container_style
 * is set. Divider/heading/callout are excluded (callout is its own container;
 * divider/heading don't take wrappers). Otherwise returns the node unchanged.
 */
function withContainerBase(
  node: React.ReactNode,
  block: StepBlock,
  key: string,
  collectivePalette: CollectivePaletteMeta | null = null,
): React.ReactNode {
  if (node == null) return null
  const palette = resolveContainerPalette(block.container_style, collectivePalette)
  if (!palette) {
    // Callers invoke this from inside a ``blocks.map()``, so React
    // needs a stable ``key`` on whatever element we return — even
    // when no soft-tint wrapper is applied. Cloning here attaches
    // ``key`` at the single site every non-wrapped block flows
    // through, instead of asking every caller to pre-key its JSX.
    return React.isValidElement(node) ? React.cloneElement(node, { key }) : node
  }
  // ``--fc-quote-accent`` scopes the blockquote accent colour to this
  // container. RichTextRenderer's blockquote reads it, so a quote
  // inside a Sunrise-pink container gets Sunrise's own strong accent
  // rather than the platform teal. Cascades through the whole subtree
  // — no per-block wiring needed.
  const scopedStyle = {
    background: palette.bg,
    borderColor: palette.border,
    ['--fc-quote-accent' as string]: palette.accent,
  } as React.CSSProperties
  return (
    <div
      key={key}
      className="my-6 rounded-xl border px-5 py-5"
      style={scopedStyle}
    >
      {node}
    </div>
  )
}

/** Where the member is, when they are somewhere a response belongs.
 *
 *  Passing this is what turns Exercise blocks interactive. It is
 *  optional, and the omission is the feature: the Knowledge Guide
 *  renders the same blocks as a continuous document and has no
 *  reflection area of its own, and the public About pages have no
 *  authenticated member at all. Neither passes a context, so neither
 *  can render a response box — that exclusion is structural rather
 *  than a condition someone has to remember. */
export interface ExerciseResponseContext {
  spaceSlug: string
  pathwaySlug: string
  stepSlug: string
}

export function renderBlocks(
  blocks: StepBlock[],
  collectivePalette: CollectivePaletteMeta | null,
  exerciseContext?: ExerciseResponseContext,
): React.ReactNode {
  // Closure-scoped helpers so every callsite below reads from the
  // active collective palette without having to thread it through
  // every call. Palette-linked block colours (``palette:primary`` …)
  // resolve here; ``custom:#hex`` and legacy chip keys are handled by
  // the resolver itself.
  const withContainer = (node: React.ReactNode, block: StepBlock, key: string): React.ReactNode =>
    withContainerBase(node, block, key, collectivePalette)
  const resolveContainer = (v: string | null | undefined) =>
    resolveContainerPalette(v, collectivePalette)
  const resolveCallout = (caption: string | null | undefined, label: string | null | undefined) =>
    resolveCalloutPalette(caption, label, undefined, collectivePalette)

  return blocks.map((block) => {
    const { id, block_type: t } = block

    if (t === 'divider') return <hr key={id} className="my-8 border-border" />

    if (t === 'columns') {
      return withContainer(
        <ColumnsGrid payload={decodeColumns(block.content)} className="my-1.5" />,
        block, id,
      )
    }

    if (t === 'heading') {
      const level = block.label === 'h1' ? 'h1' : block.label === 'h3' ? 'h3' : 'h2'
      const cls = level === 'h1'
        ? 'mb-3 mt-9 font-semibold text-[1.5rem] leading-tight text-navy-900 first:mt-0'
        : level === 'h3'
        ? 'mb-2 mt-7 font-semibold text-[1.05rem] text-navy-900 first:mt-0'
        : 'mb-3 mt-9 font-semibold text-[1.2rem] text-navy-900 first:mt-0'
      return React.createElement(level, { key: id, className: cls }, block.content)
    }

    if (t === 'text' && block.content) {
      // ``my-4`` — 16px between adjacent Content blocks. 6px proved too
      // tight to read as a break: two separate blocks still looked like
      // one, because the gap between them was smaller than the leading
      // inside them.
      //
      // Set on the block, not on its paragraphs, so the rhythm *within*
      // a block is untouched — a block of three lines still reads as
      // three lines. Adjacent margins collapse, so this is a floor and
      // not an addition: a Content block beside an image still resolves
      // to the image's 24px, and beside a file card to that card's own
      // 16px. Nothing with a larger margin moves.
      //
      // Dropped when the block sits in a soft-tinted container: that
      // wrapper has its own padding, so an inner margin cannot collapse
      // out of it and would instead show up as 16px of unexplained
      // space inside the tint. Same reasoning as ``audio``,
      // ``reflection_prompt`` and ``exercise`` above.
      // ``fc-content-block`` carries no styling of its own. It exists so
      // that one rule in ``globals.css`` can give *consecutive* Content
      // blocks 32px while leaving every other pairing alone — see the
      // rule for why a plain larger margin could not do that.
      //
      // Only the un-tinted branch is marked. A tinted block already
      // reads as a separate object through its own border and fill, and
      // marking it would stack extra space on top of the container's
      // own margin.
      const wrapped = !!resolveContainer(block.container_style)
      return withContainer(
        <div className={wrapped ? undefined : 'fc-content-block my-4'}>
          <RichTextRenderer content={block.content} />
        </div>,
        block, id,
      )
    }

    if (t === 'image') {
      const src = block.media_asset ? resolveUrl(block.media_asset.file_url) : block.embed_url
      if (!src) return null
      // Alt-text resolution — three-state semantics preserved:
      //   * ``label = null``  → legacy row; fall back to asset.title,
      //                          then '' if there's no asset title.
      //   * ``label = ''``    → decorative image; ``alt=""`` wins and
      //                          we do NOT fall back to the asset title.
      //   * ``label = '...'`` → writer's explicit alt text.
      // ``??`` is intentional — using ``||`` here would silently
      // replace an intentionally decorative image with the asset
      // title, breaking screen-reader intent.
      const alt = block.label ?? block.media_asset?.title ?? ''
      // Subtle neutral drop shadow so screenshots and diagrams don't
      // vanish into a white page background. Deliberately understated:
      // no border, no bg, no surrounding frame — just enough depth to
      // separate the image from the page. Kept neutral (navy-tinted)
      // so palette-coloured containers never bleed into the shadow.
      return withContainer(
        <figure className="my-6">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={src}
            alt={alt}
            className="w-full rounded-xl shadow-[0_1px_3px_rgba(15,30,55,0.08),0_2px_8px_rgba(15,30,55,0.04)]"
          />
          {block.caption && <figcaption className="mt-2 text-center text-[12px] text-black">{block.caption}</figcaption>}
        </figure>,
        block, id,
      )
    }

    if (t === 'video_embed' && block.embed_url) {
      const embedSrc = getVideoEmbed(block.embed_url)
      // SEC-016 — defence-in-depth for the fallback anchor path.
      const href = embedSrc ? null : safeHref(block.embed_url)
      return withContainer(
        <figure className="my-6">
          <MediaBlockHeading heading={block.heading} />
          {embedSrc ? (
            <div className="aspect-video overflow-hidden rounded-xl bg-slate-100">
              <iframe
                src={embedSrc}
                className="h-full w-full"
                allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                allowFullScreen
              />
            </div>
          ) : href ? (
            <a
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              className="group flex items-center gap-3 rounded-xl border border-border bg-white px-4 py-3 hover:border-[color:var(--fc-accent-ring,rgba(56,160,158,0.40))]"
            >
              <span className="text-black">▶</span>
              <span className="text-[14px] font-medium text-navy-900 group-hover:underline">
                {block.caption || block.embed_url}
              </span>
              <span className="ml-auto text-[12px] text-black">↗</span>
            </a>
          ) : (
            <p className="text-[14px] text-black">
              {block.caption || block.embed_url}
            </p>
          )}
          {embedSrc && block.caption && (
            <figcaption className="mt-2 text-center text-[12px] text-black">{block.caption}</figcaption>
          )}
        </figure>,
        block, id,
      )
    }

    if (t === 'audio') {
      const asset = block.media_asset
      if (!asset) return null
      // When wrapped in a soft container, drop the audio block's own
      // white-rounded border so we don't get a box-in-box look.
      const wrapped = !!resolveContainer(block.container_style)
      return withContainer(
        <figure className={wrapped ? '' : 'my-6 rounded-xl border border-border bg-white p-4'}>
          {/* A creator-supplied heading replaces the stock "Audio"
              label rather than stacking above it: two labels on one
              player is noise, and "Audio" is only there to say what
              the thing is when nobody has said anything better. */}
          {block.heading?.trim() ? (
            <MediaBlockHeading heading={block.heading} />
          ) : (
            <p className="mb-2 text-[11px] font-semibold uppercase tracking-widest text-black">Audio</p>
          )}
          <audio controls className="w-full" src={resolveUrl(asset.file_url)} />
          {block.caption && <figcaption className="mt-2 text-[12px] text-black">{block.caption}</figcaption>}
        </figure>,
        block, id,
      )
    }

    if (t === 'file_download' && block.media_asset) return withContainer(
      <div className="my-4">
        <MediaBlockHeading heading={block.heading} />
        <a
          href={resolveUrl(block.media_asset.file_url)}
          download
          className="group inline-flex items-center gap-2 rounded-xl border border-border bg-white px-4 py-3 text-[14px] font-medium text-navy-900 transition-colors hover:border-[color:var(--fc-accent-ring,rgba(56,160,158,0.40))] hover:text-[color:var(--fc-accent,#0f766e)]"
        >
          <span>↓</span>
          {block.label || block.media_asset.title}
          <span className="ml-1 text-[11px] font-normal text-black">{block.media_asset.original_filename}</span>
        </a>
      </div>,
      block, id,
    )

    if (t === 'link' && block.embed_url) {
      // SEC-016 — defence-in-depth. Backend rejects unsafe schemes on
      // write; if a legacy row slips through render a plain card
      // instead of a live anchor.
      const href = safeHref(block.embed_url)
      if (!href) {
        return (
          <div key={id} className="my-4">
            <div className="rounded-xl border border-border bg-white px-4 py-3">
              <p className="text-[14px] font-medium text-navy-900">
                {block.label || block.embed_url}
              </p>
              {block.caption && <p className="mt-0.5 text-[12px] text-black">{block.caption}</p>}
            </div>
          </div>
        )
      }
      return (
        <div key={id} className="my-4">
          <a
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            className="group flex items-start justify-between gap-4 rounded-xl border border-border bg-white px-4 py-3 transition-colors hover:border-[color:var(--fc-accent-ring,rgba(56,160,158,0.40))]"
          >
            <div>
              <p className="text-[14px] font-medium text-navy-900 group-hover:underline underline-offset-2">
                {block.label || block.embed_url}
              </p>
              {block.caption && <p className="mt-0.5 text-[12px] text-black">{block.caption}</p>}
            </div>
            <span className="shrink-0 text-[12px] text-black">↗</span>
          </a>
        </div>
      )
    }

    if (t === 'reflection_prompt' && block.content) {
      // Journal-quote treatment: prompt rendered as a serif italic
      // question with the supporting context (caption) below in a
      // smaller plain paragraph. When wrapped in a soft container,
      // the container provides the visual treatment instead.
      const wrapped = !!resolveContainer(block.container_style)
      // Prompt content is plain text from the purpose-built PromptEditor;
      // legacy prompts may still be TipTap JSON, in which case
      // RichTextRenderer handles the rendering.
      const isJson = (() => { try { return JSON.parse(block.content!).type === 'doc' } catch { return false } })()
      return (
        <div
          key={id}
          className={wrapped ? 'my-6' : 'my-6 rounded-xl border-l-4 px-6 py-5'}
          style={wrapped ? undefined : {
            borderColor: 'var(--fc-accent-line, #5eead4)',
            background: 'var(--fc-accent-soft, #f0fdfa)',
          }}
        >
          <p
            className="mb-2 flex items-center gap-2 text-[10.5px] font-semibold uppercase tracking-[0.16em]"
            style={{ color: 'var(--fc-accent, #0d9488)' }}
          >
            <span aria-hidden="true" className="text-[15px] leading-none">❝</span>
            Reflection prompt
          </p>
          {isJson ? (
            <div className="font-serif italic text-[18px] leading-snug text-navy-900">
              <RichTextRenderer content={block.content} />
            </div>
          ) : (
            /* ``whitespace-pre-wrap``: the prompt is plain text from
               PromptEditor's textarea and authors lay it out in lines.
               The newlines are stored — 4 of the 8 reflection prompts in
               the database contain them — and were only being collapsed
               here, by ordinary HTML whitespace handling. ``pre-wrap``
               keeps author breaks and blank lines while still wrapping
               long lines normally. No content is manipulated and the
               text stays escaped by JSX. */
            <p className="whitespace-pre-wrap font-serif italic text-[18px] leading-snug text-navy-900">
              {block.content}
            </p>
          )}
          {block.caption && (
            /* The supporting context under the prompt — same plain
               text, same treatment, so the two cannot disagree. */
            <p className="mt-2 whitespace-pre-wrap text-[14px] leading-relaxed text-black">
              {block.caption}
            </p>
          )}
        </div>
      )
    }

    if (t === 'exercise' && block.content) {
      // Exercise is now a specialised Content block: soft card + label
      // + optional title + rich body. Legacy step-envelope rows are
      // migrated to TipTap JSON on the fly by exerciseContentToRichText
      // so old and new rows render through the same path.
      const body = exerciseContentToRichText(block.content)
      const wrapped = !!resolveContainer(block.container_style)
      return (
        <div
          key={id}
          className={wrapped ? 'my-6' : 'my-6 rounded-xl border border-slate-200 bg-white px-6 py-5'}
        >
          <p className="mb-1 flex items-center gap-2 text-[10.5px] font-semibold uppercase tracking-[0.16em] text-slate-700">
            <span aria-hidden="true" className="text-[13px]">✏</span>
            Exercise
          </p>
          {block.label && (
            <p className="mt-1 mb-3 font-serif text-[20px] leading-tight text-navy-900">
              {block.label}
            </p>
          )}
          {body && <RichTextRenderer content={body} />}
          {/* The response area sits inside the exercise card, under a
              hairline, so the instructions and the answer read as one
              activity rather than two blocks. Rendered only where a
              member and a step actually exist, and only while the
              creator is still inviting a response. */}
          {exerciseContext && block.response_enabled !== false && (
            <ExerciseResponse
              spaceSlug={exerciseContext.spaceSlug}
              pathwaySlug={exerciseContext.pathwaySlug}
              stepSlug={exerciseContext.stepSlug}
              blockId={id}
            />
          )}
        </div>
      )
    }

    if (t === 'callout' && block.content) {
      // Creator-chosen colour + purpose. If the writer set a purpose
      // (Highlight / Tip / Placeholder / …), we surface it as an
      // icon + label tag above the content so members can read the
      // intent, not just the tint. Callouts with no purpose set stay
      // as a soft tinted box.
      const palette = resolveCallout(block.caption, block.label)
      const icon = resolveCalloutPurposeIcon(block.label)
      const purposeLabel = resolveCalloutPurposeLabel(block.label)
      return (
        <div
          key={id}
          className="my-5 rounded-xl border px-5 py-4"
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
          <RichTextRenderer content={block.content} />
        </div>
      )
    }

    if (t === 'embed' && block.embed_url) {
      return withContainer(
        <figure className="my-6">
          {block.label && (
            <p className="mb-2 text-[11px] font-semibold uppercase tracking-widest text-black">
              {block.label}
            </p>
          )}
          <EmbedRenderer url={block.embed_url} title={block.label ?? undefined} />
          {block.caption && (
            <figcaption className="mt-2 text-center text-[12px] text-black">
              {block.caption}
            </figcaption>
          )}
        </figure>,
        block, id,
      )
    }

    if (t === 'button' && block.embed_url && block.label) {
      const newTab = block.content === 'new_tab' || block.content === 'same_tab' ? block.content : null
      return withContainer(
        <div className="my-5">
          <ButtonBlock
            href={block.embed_url}
            text={block.label}
            caption={block.caption ?? null}
            collectivePalette={collectivePalette}
            newTabPref={newTab}
          />
        </div>,
        block, id,
      )
    }

    if (t === 'resource') {
      // A resource block card can point at either a Library link
      // (SpaceResource, ``block.resource``) or a Library file
      // (CreatorMediaAsset, ``block.media_asset``). Both come from
      // the same unified Library — the block editor picks whichever
      // the creator selected. Hide the block if neither is populated
      // (deleted / draft link) so member surfaces self-heal.
      const linkRef = block.resource && block.resource.status === 'published' ? block.resource : null
      const mediaRef = block.media_asset ?? null

      let title = ''
      let description: string | null = null
      let href: string | null = null
      let cardTypeLabel = ''
      let isFile = false
      let downloadName: string | undefined
      if (linkRef) {
        title = block.label || linkRef.title
        description = block.caption || linkRef.description
        href = linkRef.url ? resolveUrl(linkRef.url) : null
        cardTypeLabel = linkRef.resource_type
        isFile = !!linkRef.file_name || ['file', 'guide', 'template', 'replay', 'audio', 'video'].includes(linkRef.resource_type)
        downloadName = isFile && linkRef.file_name ? linkRef.file_name : undefined
      } else if (mediaRef) {
        title = block.label || mediaRef.title
        description = block.caption || null
        href = mediaRef.file_url ? resolveUrl(mediaRef.file_url) : null
        cardTypeLabel = mediaRef.media_type
        // Every media asset backs a downloadable file — audio/video
        // still render as a Download card here (creators embed them
        // inline via audio/video_embed blocks when they want playback).
        isFile = true
        downloadName = mediaRef.original_filename ?? undefined
      }

      if (!href) return null
      const ctaLabel = isFile ? 'Download resource' : 'Open resource'
      return withContainerBase(
        <a
          key={id}
          href={href}
          target={isFile ? undefined : '_blank'}
          rel={isFile ? undefined : 'noopener noreferrer'}
          download={downloadName}
          className="group my-5 flex items-start gap-4 rounded-xl border border-border bg-white px-5 py-4 transition-colors hover:border-[color:var(--fc-accent-ring,rgba(56,160,158,0.40))]"
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
                {cardTypeLabel}
              </span>
            </div>
            {description && (
              <p className="mt-1 text-[13px] leading-relaxed text-black">{description}</p>
            )}
          </div>
          <span className="shrink-0 self-center rounded-full border border-border bg-white px-3 py-1.5 text-[12px] font-medium text-black group-hover:border-[color:var(--fc-accent-ring,rgba(56,160,158,0.40))] group-hover:text-[color:var(--fc-accent,#0f766e)]">
            {ctaLabel} {isFile ? '↓' : '↗'}
          </span>
        </a>,
        block, id, collectivePalette,
      )
    }

    return null
  })
}

/** Component wrapper for use in JSX. Prefer this over calling
 *  `renderBlocks` directly so React tree shape stays predictable. */
export default function BlockList({
  blocks,
  collectivePalette = null,
}: {
  blocks: StepBlock[]
  collectivePalette?: CollectivePaletteMeta | null
}) {
  return <>{renderBlocks(blocks, collectivePalette)}</>
}
