import { notFound } from 'next/navigation'
import Link from 'next/link'
import { getPathwayOverview, getPathwayAboutBlocks } from '@/lib/serverApi'
import { getPathwayCoverStyle } from '@/lib/coverArt'
import { resolveMediaUrl, apiUrl } from '@/lib/api'
import { isPathwayLocked, formatPathwayPrice, unlockCtaLabel } from '@/lib/pathwayAccess'
import RichTextRenderer from '@/components/RichTextRenderer'
import type { PathwayWithSteps, PathwayAboutBlock, StepBlockMedia } from '@/types/platform'

interface Props {
  params: Promise<{ slug: string; 'pathway-slug': string }>
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

function resolveAssetUrl(url: string): string {
  return url.startsWith('http') ? url : `${API_BASE}/api/uploads/${url}`
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
  } catch {}
  return null
}

const CALLOUT_STYLES: Record<string, { color: string; accent: string; label: string }> = {
  info:    { color: 'rgba(59,130,246,0.09)',  accent: '#1d4ed8', label: 'Info' },
  tip:     { color: 'rgba(56,160,158,0.09)', accent: '#0f766e', label: 'Tip' },
  warning: { color: 'rgba(234,179,8,0.11)',  accent: '#92400e', label: 'Warning' },
}

function BlockRenderer({ block }: { block: PathwayAboutBlock }) {
  const t = block.block_type
  const asset = block.media_asset as StepBlockMedia | null

  if (t === 'divider') return <hr className="border-slate-200" />

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
    <div className="prose prose-sm max-w-none text-slate-700">
      <RichTextRenderer content={block.content} />
    </div>
  )

  if (t === 'image') {
    const src = asset ? resolveAssetUrl(asset.file_url) : block.embed_url
    if (!src) return null
    return (
      <figure>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={src} alt={block.caption ?? ''} className="w-full rounded-xl object-cover" />
        {block.caption && (
          <figcaption className="mt-2 text-center text-[12px] text-slate-400">{block.caption}</figcaption>
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
            <figcaption className="mt-2 text-center text-[12px] text-slate-400">{block.caption}</figcaption>
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
          className="flex items-center gap-2 rounded-xl border border-border bg-white px-4 py-3 text-[14px] font-medium text-teal-700 transition-colors hover:border-teal-200"
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
      <div className="rounded-xl border border-border bg-white p-4">
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
        className="flex items-center gap-3 rounded-xl border border-border bg-white px-5 py-3.5 transition-colors hover:border-teal-200"
      >
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-lg"
          style={{ background: 'rgba(56,160,158,0.08)' }}>
          ↓
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-[14px] font-semibold text-navy-900">{block.label || asset.title}</p>
          <p className="text-[12px] text-slate-400">{asset.original_filename}</p>
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
        className="flex items-center gap-3 rounded-xl border border-border bg-white px-5 py-3.5 transition-colors hover:border-teal-200"
      >
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-lg"
          style={{ background: 'rgba(56,160,158,0.08)' }}>
          🔗
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-[14px] font-semibold text-navy-900">{block.label || block.embed_url}</p>
          {block.caption && <p className="text-[12px] text-slate-400">{block.caption}</p>}
        </div>
        <span className="shrink-0 text-slate-300">→</span>
      </a>
    )
  }

  if (t === 'reflection_prompt') return (
    <div className="rounded-xl border-l-4 border-teal-300 bg-teal-50/40 py-4 pl-5 pr-4">
      <p className="mb-1.5 text-[10px] font-bold uppercase tracking-widest text-teal-600">Reflection</p>
      <div className="text-[15px] italic leading-relaxed text-slate-700">
        <RichTextRenderer content={block.content} />
      </div>
    </div>
  )

  if (t === 'exercise') return (
    <div className="rounded-xl border border-slate-200 bg-white px-5 py-4">
      <p className="mb-2 text-[10px] font-bold uppercase tracking-widest text-slate-400">Exercise</p>
      <div className="text-[14px] leading-relaxed text-slate-700">
        <RichTextRenderer content={block.content} />
      </div>
    </div>
  )

  if (t === 'callout') {
    const style = CALLOUT_STYLES[block.label ?? 'info'] ?? CALLOUT_STYLES.info
    return (
      <div className="rounded-xl px-5 py-4" style={{ background: style.color }}>
        <p className="mb-1.5 text-[10px] font-bold uppercase tracking-widest" style={{ color: style.accent }}>
          {style.label}
        </p>
        <div className="text-[14px] leading-relaxed text-slate-700">
          <RichTextRenderer content={block.content} />
        </div>
      </div>
    )
  }

  return null
}

export default async function PathwayAboutPage({ params }: Props) {
  const { slug, 'pathway-slug': pathwaySlug } = await params

  const [pathway, aboutBlocks]: [PathwayWithSteps | null, PathwayAboutBlock[]] = await Promise.all([
    getPathwayOverview(slug, pathwaySlug),
    getPathwayAboutBlocks(slug, pathwaySlug),
  ])

  if (!pathway) notFound()

  const cs = getPathwayCoverStyle(pathwaySlug)
  const coverImageUrl = resolveMediaUrl(pathway.cover_image_url)
  const isComingSoon = pathway.status === 'coming_soon'
  // Use server-computed user_has_access — covers free, included, paid+entitlement, admin/creator
  const locked = !isComingSoon && !pathway.user_has_access

  const priceLabel = locked
    ? formatPathwayPrice(pathway.price_cents, pathway.currency, pathway.billing_interval)
    : null
  const unlockLabel = locked
    ? unlockCtaLabel(pathway.access_type, pathway.price_cents, pathway.currency, pathway.billing_interval)
    : null

  const nextIncomplete = pathway.steps.find(s => !s.is_completed)
  const continueHref = nextIncomplete
    ? `/spaces/${slug}/pathways/${pathwaySlug}/${nextIncomplete.slug}`
    : `/spaces/${slug}/pathways/${pathwaySlug}/${pathway.steps[0]?.slug}`

  const progressPct = pathway.step_count > 0
    ? Math.round((pathway.completed_count / pathway.step_count) * 100)
    : 0

  return (
    <div className="mx-auto max-w-5xl px-4 py-8 md:px-6">

      {/* Back link */}
      <div className="mb-6">
        <Link
          href={`/spaces/${slug}/pathways`}
          className="text-sm text-slate-400 transition-colors hover:text-teal-600"
        >
          ← All Pathways
        </Link>
      </div>

      {/* ── Two-column layout on desktop ── */}
      <div className="grid gap-8 lg:grid-cols-[1fr_300px]">

        {/* ── Main content ── */}
        <div>
          {/* Hero banner */}
          <div
            className="relative mb-7 overflow-hidden rounded-2xl"
            style={{
              background: cs.background,
              backgroundSize: cs.backgroundSize ?? 'auto',
            }}
          >
            {coverImageUrl && (
              <>
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={coverImageUrl}
                  alt=""
                  aria-hidden="true"
                  className="absolute inset-0 h-full w-full object-cover"
                />
                <div
                  className="absolute inset-0"
                  style={{ background: 'linear-gradient(135deg, rgba(7,24,36,0.75) 0%, rgba(7,56,58,0.58) 100%)' }}
                />
              </>
            )}
            <div className="relative px-7 py-10 md:px-9 md:py-12">
              <div className="mb-3 h-[2px] w-8 rounded-full bg-teal-400" />
              <p
                className="mb-1 text-[9px] font-bold uppercase tracking-[0.20em]"
                style={{ color: coverImageUrl ? 'rgba(255,255,255,0.65)' : cs.labelColor }}
              >
                Pathway
              </p>
              <h1
                className="font-serif text-2xl md:text-3xl"
                style={{ color: coverImageUrl ? '#FFFFFF' : cs.titleColor }}
              >
                {pathway.title}
              </h1>
              {pathway.description && (
                <p
                  className="mt-2.5 max-w-md text-[14px] leading-relaxed"
                  style={{ color: (coverImageUrl || cs.isDark) ? 'rgba(255,255,255,0.72)' : '#64748B' }}
                >
                  {pathway.description}
                </p>
              )}
            </div>
          </div>

          {/* About blocks */}
          {aboutBlocks.length > 0 ? (
            <div className="space-y-6">
              {aboutBlocks.map(block => (
                <BlockRenderer key={block.id} block={block} />
              ))}
            </div>
          ) : (
            /* Fallback when no about blocks exist */
            <div className="space-y-4">
              {pathway.description && (
                <p className="text-[16px] leading-relaxed text-slate-600">{pathway.description}</p>
              )}
              {pathway.step_count > 0 && (
                <p className="text-[14px] text-slate-400">
                  {pathway.step_count} step{pathway.step_count !== 1 ? 's' : ''} in this pathway.
                </p>
              )}
            </div>
          )}
        </div>

        {/* ── Right sidebar ── */}
        <div className="flex flex-col gap-4 lg:sticky lg:top-6 lg:self-start">

          {/* CTA card */}
          <div className="rounded-2xl border border-border bg-white p-6">
            <div className="mb-4 space-y-2">
              {/* Access badge */}
              {locked ? (
                <>
                  {priceLabel && (
                    <p className="font-serif text-2xl font-bold text-navy-900">{priceLabel}</p>
                  )}
                  <p className="text-[13px] text-slate-500">
                    {pathway.access_type === 'subscription' ? 'Monthly access required' : 'One-off purchase'}
                  </p>
                </>
              ) : isComingSoon ? (
                <p className="text-[14px] font-semibold text-slate-500">Coming soon</p>
              ) : pathway.step_count > 0 ? (
                <>
                  <div className="mb-1 flex items-baseline justify-between text-xs text-slate-400">
                    <span>{pathway.completed_count} of {pathway.step_count} complete</span>
                    <span>{progressPct}%</span>
                  </div>
                  <div className="h-1.5 w-full overflow-hidden rounded-full bg-teal-100">
                    <div
                      className="h-full rounded-full bg-teal-500 transition-all"
                      style={{ width: `${progressPct}%` }}
                    />
                  </div>
                </>
              ) : null}
            </div>

            {/* Step count */}
            {pathway.step_count > 0 && (
              <p className="mb-4 text-[13px] text-slate-500">
                {pathway.step_count} step{pathway.step_count !== 1 ? 's' : ''}
              </p>
            )}

            {/* CTA button */}
            {isComingSoon ? (
              <div
                className="flex w-full items-center justify-center gap-2 rounded-full px-5 py-2.5 text-[14px] font-medium"
                style={{ background: 'rgba(56,160,158,0.08)', color: '#073B3A' }}
              >
                <svg className="h-3.5 w-3.5 text-teal-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                Coming soon
              </div>
            ) : locked ? (
              <>
                <Link
                  href={`/spaces/${slug}/pathways/${pathwaySlug}/checkout`}
                  className="block w-full rounded-full px-5 py-2.5 text-center text-[14px] font-semibold text-white transition-opacity hover:opacity-90"
                  style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
                >
                  {unlockLabel ?? 'Unlock'}
                </Link>
                <p className="mt-2 text-center text-[11px] text-slate-400">Secure checkout via Stripe</p>
              </>
            ) : pathway.steps.length > 0 && continueHref ? (
              <Link
                href={continueHref}
                className="block w-full rounded-full px-5 py-2.5 text-center text-[14px] font-semibold text-white transition-opacity hover:opacity-90"
                style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
              >
                {pathway.completed_count === 0 ? 'Begin pathway' : pathway.completed_count >= pathway.step_count ? 'Review' : 'Continue'}
              </Link>
            ) : (
              <Link
                href={`/spaces/${slug}/pathways/${pathwaySlug}`}
                className="block w-full rounded-full px-5 py-2.5 text-center text-[14px] font-semibold text-white transition-opacity hover:opacity-90"
                style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
              >
                View pathway
              </Link>
            )}

            {/* Link to full pathway overview */}
            <Link
              href={`/spaces/${slug}/pathways/${pathwaySlug}`}
              className="mt-3 block text-center text-[12px] text-slate-400 transition-colors hover:text-teal-600"
            >
              View all steps →
            </Link>
          </div>

          {/* Access type label */}
          {!locked && !isComingSoon && (
            <div className="rounded-xl border border-border bg-white px-4 py-3 text-center">
              <span
                className="rounded-full px-3 py-1 text-[11px] font-semibold"
                style={
                  pathway.access_type === 'free'
                    ? { background: 'rgba(16,185,129,0.10)', color: '#065F46' }
                    : { background: 'rgba(56,160,158,0.10)', color: '#073B3A' }
                }
              >
                {pathway.access_type === 'free'
                  ? 'Free'
                  : pathway.access_type === 'included'
                  ? 'Included'
                  : 'Access granted'}
              </span>
            </div>
          )}
        </div>
      </div>

    </div>
  )
}
