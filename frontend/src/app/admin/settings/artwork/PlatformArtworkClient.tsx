'use client'

import { useCallback, useRef, useState } from 'react'
import { apiUrl, resolveMediaUrl } from '@/lib/api'
import type { PlatformArtworkItem } from '@/lib/serverApi'

interface Props {
  initialItems: PlatformArtworkItem[]
}

// Per-slot display config. Not on the API because it's purely presentational
// — the backend registry stays a flat key/title/description map.
type SlotDisplay = {
  aspectRatio: string
  guidance: string
  placeholderBody?: string
}
const DISPLAY_BY_KEY: Record<string, SlotDisplay> = {
  mother_world_hero: {
    aspectRatio: '3 / 1',
    guidance: 'Wide panoramic image · recommended 16:5 or 3:1 · minimum width 1600px · JPG, PNG or WebP.',
    placeholderBody: 'Add a panoramic view of the world to welcome the World Management team.',
  },
  discover_places: {
    aspectRatio: '3 / 2',
    guidance: 'Landscape image · recommended 3:2 · minimum width 1200px · JPG, PNG or WebP.',
    placeholderBody: 'The image shown on the Discover Places tile on the member dashboard.',
  },
  ways_to_connect: {
    aspectRatio: '3 / 2',
    guidance: 'Landscape image · recommended 3:2 · minimum width 1200px · JPG, PNG or WebP.',
    placeholderBody: 'The image shown on the Ways to Connect tile on the member dashboard.',
  },
  new_to_fresh_collective: {
    aspectRatio: '3 / 2',
    guidance: 'Landscape image · recommended 3:2 · minimum width 1200px · JPG, PNG or WebP. A gentle first horizon — unhurried, warm.',
    placeholderBody: 'The tile shown in “Elsewhere in the world” for members who haven’t yet completed the orientation. Falls back to a soft gold + teal atmospheric scene when empty.',
  },
  auth_background: {
    aspectRatio: '16 / 9',
    guidance: 'Wide landscape · recommended 16:9 or wider · minimum width 1920px · JPG, PNG or WebP. Rendered full-bleed under a deep navy overlay — mid-tone or richly-lit images sit best.',
    placeholderBody: 'The world artwork behind /login and /signup. Falls back to the bundled login-hero.png when empty.',
  },
  // ── Public homepage — discovery cards (4:3 / 5:3 landscape) ───────
  homepage_explore_collectives: {
    aspectRatio: '5 / 3',
    guidance: 'Landscape image · recommended 4:3 or 5:3 · minimum width 1200px · JPG, PNG or WebP.',
    placeholderBody: 'The hero image on the Explore Collectives card on the public homepage.',
  },
  homepage_discover_places: {
    aspectRatio: '5 / 3',
    guidance: 'Landscape image · recommended 4:3 or 5:3 · minimum width 1200px · JPG, PNG or WebP.',
    placeholderBody: 'The hero image on the Discover Places card on the public homepage.',
  },
  homepage_ways_to_connect: {
    aspectRatio: '5 / 3',
    guidance: 'Landscape image · recommended 4:3 or 5:3 · minimum width 1200px · JPG, PNG or WebP.',
    placeholderBody: 'The hero image on the Ways to Connect card on the public homepage.',
  },
  // ── Public homepage — Creator Studio anchor (wide 16:9) ───────────
  homepage_creator_studio: {
    aspectRatio: '16 / 9',
    guidance: 'Wide landscape · recommended 16:9 · minimum width 1600px · JPG, PNG or WebP.',
    placeholderBody: 'The large editorial image anchoring the For Creators section on the public homepage.',
  },
  // ── Public homepage — Closing invitation (optional, panoramic) ────
  homepage_closing_invitation: {
    aspectRatio: '16 / 9',
    guidance: 'Wide landscape or panoramic · recommended 16:9 or wider · optional — leave empty to render without an image.',
    placeholderBody: 'Optional supporting image behind the closing invitation. Only shown if uploaded.',
  },
  // ── Public homepage — Life inside a Collective (4 atmospheric frames) ──
  // Each holds a floating UI in the centre, so the artwork breathes
  // around a card in the middle rather than needing to hold detail
  // there. 4:3 is a comfortable editorial proportion.
  homepage_pathways: {
    aspectRatio: '4 / 3',
    guidance: 'Landscape image · recommended 4:3 · minimum width 1200px · JPG, PNG or WebP. Reused as the Pathways page hero.',
    placeholderBody: 'The atmospheric image behind the Pathways feature. Falls back to a tasteful gradient if empty.',
  },
  homepage_gatherings: {
    aspectRatio: '4 / 3',
    guidance: 'Landscape image · recommended 4:3 · minimum width 1200px · JPG, PNG or WebP. Reused as the Gatherings page hero.',
    placeholderBody: 'The atmospheric image behind the Gatherings feature. Falls back to a tasteful gradient if empty.',
  },
  homepage_conversations: {
    aspectRatio: '4 / 3',
    guidance: 'Landscape image · recommended 4:3 · minimum width 1200px · JPG, PNG or WebP. Reused as the Conversations page hero.',
    placeholderBody: 'The atmospheric image behind the Conversations feature. Falls back to a tasteful gradient if empty.',
  },
  homepage_resources: {
    aspectRatio: '4 / 3',
    guidance: 'Landscape image · recommended 4:3 · minimum width 1200px · JPG, PNG or WebP. Reused as the Resources page hero.',
    placeholderBody: 'The atmospheric image behind the Resources feature. Falls back to a tasteful gradient if empty.',
  },
  // ── For Creators page — one image per creator account (4 rows) ───
  for_creators_community: {
    aspectRatio: '4 / 3',
    guidance: 'Landscape image · recommended 4:3 · minimum width 1200px · JPG, PNG or WebP. Local, welcoming, small-group energy.',
    placeholderBody: 'Editorial image for the Community Collective row on /for-creators.',
  },
  for_creators_creator: {
    aspectRatio: '4 / 3',
    guidance: 'Landscape image · recommended 4:3 · minimum width 1200px · JPG, PNG or WebP. A single creator at work.',
    placeholderBody: 'Editorial image for the Creator row on /for-creators.',
  },
  for_creators_pro: {
    aspectRatio: '4 / 3',
    guidance: 'Landscape image · recommended 4:3 · minimum width 1200px · JPG, PNG or WebP. Several places thriving under one hand.',
    placeholderBody: 'Editorial image for the Creator Portfolio row on /for-creators.',
  },
  for_creators_organisation: {
    aspectRatio: '4 / 3',
    guidance: 'Landscape image · recommended 4:3 · minimum width 1200px · JPG, PNG or WebP. A wider connected ecosystem.',
    placeholderBody: 'Editorial image for the Ecosystem row on /for-creators.',
  },
  for_creators_world_builders: {
    aspectRatio: '4 / 3',
    guidance: 'Landscape image · recommended 4:3 · minimum width 1200px · JPG, PNG or WebP. Creators learning together — considered practice, shared workspace.',
    placeholderBody: 'Editorial image for the World Builders Collective section on /for-creators.',
  },
  // ── Onboarding — Member (wide hero on each step) ─────────────────
  member_onboarding_welcome: {
    aspectRatio: '16 / 9',
    guidance: 'Wide landscape · recommended 16:9 · minimum width 1600px · JPG, PNG or WebP. A first horizon.',
    placeholderBody: 'Hero image for the opening step of the Member orientation. Falls back to a small SVG horizon when empty.',
  },
  member_onboarding_interests: {
    aspectRatio: '16 / 9',
    guidance: 'Wide landscape · recommended 16:9 · minimum width 1600px · JPG, PNG or WebP. A sense of choosing a direction.',
    placeholderBody: 'Hero image for the interests step of the Member orientation. Falls back to a small SVG compass when empty.',
  },
  member_onboarding_how_it_works: {
    aspectRatio: '16 / 9',
    guidance: 'Wide landscape · recommended 16:9 · minimum width 1600px · JPG, PNG or WebP. A living environment with several rooms held together.',
    placeholderBody: 'Hero image for the "How this place works" step. Falls back to a small SVG scene when empty.',
  },
  member_onboarding_arrival: {
    aspectRatio: '16 / 9',
    guidance: 'Wide landscape · recommended 16:9 · minimum width 1600px · JPG, PNG or WebP. A threshold — an invitation to enter.',
    placeholderBody: 'Hero image for the final arrival step. Falls back to a small SVG archipelago when empty.',
  },
  // ── Onboarding — Creator (welcome + ritual steps) ───────────────
  creator_onboarding_welcome: {
    aspectRatio: '16 / 9',
    guidance: 'Wide landscape · recommended 16:9 · minimum width 1600px · JPG, PNG or WebP. A calm arrival at a new vantage point.',
    placeholderBody: 'Hero image for /creator-onboarding — shown once after Creator plan activation.',
  },
  creator_ritual_atmosphere: {
    aspectRatio: '16 / 9',
    guidance: 'Wide landscape · recommended 16:9 · minimum width 1600px · JPG, PNG or WebP. Evokes feeling and mood — light, weather, air.',
    placeholderBody: 'Hero image for the Atmosphere step of Build Your Collective.',
  },
  creator_ritual_identity: {
    aspectRatio: '16 / 9',
    guidance: 'Wide landscape · recommended 16:9 · minimum width 1600px · JPG, PNG or WebP. A single, clear mark — the heart of the space.',
    placeholderBody: 'Hero image for the Identity Statement step of Build Your Collective.',
  },
  creator_ritual_welcome_message: {
    aspectRatio: '16 / 9',
    guidance: 'Wide landscape · recommended 16:9 · minimum width 1600px · JPG, PNG or WebP. A door opening, a room warmed for arrival.',
    placeholderBody: 'Hero image for the Welcome Message step of Build Your Collective.',
  },
  creator_ritual_practical: {
    aspectRatio: '16 / 9',
    guidance: 'Wide landscape · recommended 16:9 · minimum width 1600px · JPG, PNG or WebP. Grounded, considered, plain.',
    placeholderBody: 'Hero image for the Practical Details step of Build Your Collective.',
  },
  // ── Homepage — Product Screenshots (real UI captures, not atmosphere) ─
  // Per-slot aspects match the natural aspect of the intended source
  // screen so preview + homepage render feel identical. Capture at
  // desktop width so type stays legible after downscaling.
  homepage_onboarding_begin_shaping: {
    aspectRatio: '1 / 1',
    guidance: 'Product screenshot · natural roughly square · minimum width 1000px · JPG, PNG or WebP. Capture at desktop size so type stays legible.',
    placeholderBody: 'Homepage use: onboarding walkthrough tile 1 — the “Let’s begin shaping your collective.” step.',
  },
  homepage_onboarding_shape_the_feeling: {
    aspectRatio: '6 / 5',
    guidance: 'Product screenshot · comfortable 6:5 landscape · minimum width 1000px · JPG, PNG or WebP. Capture at desktop size so type stays legible.',
    placeholderBody: 'Homepage use: onboarding walkthrough tile 2 — the atmosphere / “how do you want people to feel?” step.',
  },
  homepage_onboarding_choose_island: {
    aspectRatio: '2 / 3',
    guidance: 'Product screenshot · portrait 2:3 · minimum width 1000px · JPG, PNG or WebP. Tall scroll captures render top-aligned so the heading + first few island options are visible.',
    placeholderBody: 'Homepage use: onboarding walkthrough tile 3 — the location / “Choose your island” step.',
  },
  homepage_onboarding_practical_settings: {
    aspectRatio: '2 / 3',
    guidance: 'Product screenshot · portrait 2:3 · minimum width 1000px · JPG, PNG or WebP. Rendered top-aligned so the first few fields are visible.',
    placeholderBody: 'Homepage use: onboarding walkthrough tile 4 — the “Now for the practical things.” step.',
  },
  homepage_world_builders: {
    aspectRatio: '16 / 10',
    guidance: 'Product screenshot · recommended 16:10 · minimum width 1600px · JPG, PNG or WebP. Capture the Collective looking alive — real posts, real people, not an empty shell.',
    placeholderBody: 'Homepage use: the “You don’t build yours alone” section — proof that the Collective every creator joins is a working one.',
  },
  homepage_friction_conversation: {
    aspectRatio: '4 / 5',
    guidance: 'Editorial photograph · recommended 4:5 portrait · minimum width 1200px · JPG, PNG or WebP. Genuine human connection or conversation — a circle, a shared moment, people talking. Not an interface, not a landscape.',
    placeholderBody: 'Homepage use: the “Maybe you’ve done this before…” friction section — the emotional anchor beside the copy about people opening up when something already feels familiar.',
  },
}
const DEFAULT_DISPLAY: SlotDisplay = {
  aspectRatio: '3 / 2',
  guidance: 'Drag & drop a JPG, PNG or WebP onto the preview — or use the buttons below.',
}


// Grouping metadata for the manager UI. Order here is render order.
// Any key not listed here falls into the "Other" group so a forgotten
// backend addition still appears in the manager rather than vanishing.
interface Group {
  key: string
  label: string
  description: string
  keys: string[]
}

const GROUPS: Group[] = [
  {
    key: 'member_dashboard',
    label: 'Member Dashboard',
    description: 'Artwork on the Your World tiles that members see when they sign in.',
    keys: ['explore_collectives', 'creator_studio', 'discover_places', 'ways_to_connect', 'new_to_fresh_collective'],
  },
  {
    key: 'homepage',
    label: 'Public Homepage',
    description: 'Artwork used across the public homepage at /. Each slot has a graceful atmospheric fallback when no image is uploaded.',
    keys: [
      'homepage_explore_collectives',
      'homepage_discover_places',
      'homepage_ways_to_connect',
      'homepage_pathways',
      'homepage_gatherings',
      'homepage_conversations',
      'homepage_resources',
      'homepage_creator_studio',
      'homepage_closing_invitation',
    ],
  },
  {
    key: 'for_creators',
    label: 'For Creators',
    description: 'Artwork on the public /for-creators page. One image per creator account row (Community Collective, Creator, Creator Portfolio, Ecosystem). Each has an atmospheric fallback when empty.',
    keys: [
      'for_creators_community',
      'for_creators_creator',
      'for_creators_pro',
      'for_creators_organisation',
      'for_creators_world_builders',
    ],
  },
  {
    key: 'auth_pages',
    label: 'Auth Pages',
    description: 'Shared artwork behind /login and /signup. Both pages read from the same slot so they feel like one coherent entry experience.',
    keys: ['auth_background'],
  },
  {
    key: 'onboarding_member',
    label: 'Onboarding — Member',
    description: 'Hero artwork shown at the top of each Member orientation step at /onboarding. Each step has a small SVG fallback when no image is uploaded.',
    keys: [
      'member_onboarding_welcome',
      'member_onboarding_interests',
      'member_onboarding_how_it_works',
      'member_onboarding_arrival',
    ],
  },
  {
    key: 'onboarding_creator',
    label: 'Onboarding — Creator',
    description: 'Hero artwork for the Creator welcome (/creator-onboarding) and the ritual steps in Build Your Collective. Island and Colour Palette are deliberately omitted — those steps already have native artwork.',
    keys: [
      'creator_onboarding_welcome',
      'creator_ritual_atmosphere',
      'creator_ritual_identity',
      'creator_ritual_welcome_message',
      'creator_ritual_practical',
    ],
  },
  {
    key: 'homepage_product_screenshots',
    label: 'Homepage — Product Screenshots',
    description: 'Real captures of the product UI, shown on the public homepage as proof that the guided creator ritual and the World Builders Collective exist. Deliberately separate from the atmospheric Public Homepage slots above — each of these tiles shows honest “Product screenshot pending” placeholder copy on the homepage when empty (never a stock/atmospheric fallback).',
    keys: [
      'homepage_onboarding_begin_shaping',
      'homepage_onboarding_shape_the_feeling',
      'homepage_onboarding_choose_island',
      'homepage_onboarding_practical_settings',
      'homepage_world_builders',
      'homepage_friction_conversation',
    ],
  },
  {
    key: 'world_management',
    label: 'World Management',
    description: 'Artwork inside the admin surfaces.',
    keys: ['mother_world_hero'],
  },
]

function groupItems(items: PlatformArtworkItem[]) {
  const byKey = new Map(items.map((it) => [it.key, it]))
  const seen = new Set<string>()
  const groups = GROUPS.map((g) => {
    const groupItems = g.keys
      .map((k) => byKey.get(k))
      .filter((it): it is PlatformArtworkItem => Boolean(it))
    groupItems.forEach((it) => seen.add(it.key))
    return { ...g, items: groupItems }
  }).filter((g) => g.items.length > 0)
  const other = items.filter((it) => !seen.has(it.key))
  if (other.length > 0) {
    groups.push({
      key: 'other',
      label: 'Other',
      description: 'Slots not yet grouped in the manager. Add them to GROUPS in PlatformArtworkClient.tsx.',
      keys: other.map((it) => it.key),
      items: other,
    })
  }
  return groups
}

/**
 * Admin surface for World Artwork — a small, named collection of
 * shared interface images. Each entry has a title, a short explanation,
 * a current preview, and Upload / Remove controls with drag-and-drop.
 *
 * Internal routes and API paths still use the "platform-artwork" name
 * so existing rows keep working; only the user-facing wording changed.
 */
export default function PlatformArtworkClient({ initialItems }: Props) {
  const [items, setItems] = useState<PlatformArtworkItem[]>(initialItems)

  const replaceItem = useCallback((next: PlatformArtworkItem) => {
    setItems((prev) => prev.map((it) => (it.key === next.key ? next : it)))
  }, [])

  return (
    <div className="mx-auto max-w-[900px] px-6 py-10 md:px-10">
      <header className="mb-10">
        <p
          className="mb-3 text-[11px] font-semibold uppercase tracking-[0.28em]"
          style={{ color: '#38A09E' }}
        >
          World Settings
        </p>
        <h1 className="font-serif text-[32px] leading-tight md:text-[40px]" style={{ color: '#0C1826' }}>
          World Artwork
        </h1>
        <p
          className="mt-3 max-w-[560px] text-[15px] leading-relaxed italic"
          style={{ color: 'rgba(12, 24, 38, 0.65)', fontFamily: 'Georgia, serif' }}
        >
          The shared imagery that brings Fresh Collective and its many places to life.
        </p>
      </header>

      <div className="space-y-14">
        {groupItems(items).map((group) => (
          <section key={group.key}>
            <div className="mb-5">
              <p
                className="text-[10.5px] font-semibold uppercase tracking-[0.28em]"
                style={{ color: '#38A09E' }}
              >
                {group.label}
              </p>
              <p
                className="mt-2 max-w-[560px] text-[13.5px] italic leading-relaxed"
                style={{ color: 'rgba(12, 24, 38, 0.62)', fontFamily: 'Georgia, serif' }}
              >
                {group.description}
              </p>
            </div>
            <div className="space-y-8">
              {group.items.map((item) => (
                <ArtworkRow key={item.key} item={item} onChange={replaceItem} />
              ))}
            </div>
          </section>
        ))}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Single artwork row — preview + upload/remove controls
// ---------------------------------------------------------------------------

function ArtworkRow({
  item, onChange,
}: {
  item: PlatformArtworkItem
  onChange: (next: PlatformArtworkItem) => void
}) {
  const [busy, setBusy] = useState<'upload' | 'remove' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [dragActive, setDragActive] = useState(false)
  const inputRef = useRef<HTMLInputElement | null>(null)

  const upload = useCallback(async (file: File) => {
    setBusy('upload')
    setError(null)
    try {
      const body = new FormData()
      body.append('file', file)
      const res = await fetch(apiUrl(`/api/admin/platform-artwork/${item.key}`), {
        method: 'POST',
        credentials: 'include',
        body,
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(typeof data.detail === 'string' ? data.detail : 'Upload failed.')
      }
      onChange(await res.json() as PlatformArtworkItem)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Upload failed.')
    } finally {
      setBusy(null)
    }
  }, [item.key, onChange])

  const remove = useCallback(async () => {
    if (!confirm(`Remove the artwork for “${item.title}”?`)) return
    setBusy('remove')
    setError(null)
    try {
      const res = await fetch(apiUrl(`/api/admin/platform-artwork/${item.key}`), {
        method: 'DELETE',
        credentials: 'include',
      })
      if (!res.ok) throw new Error('Could not remove artwork.')
      onChange(await res.json() as PlatformArtworkItem)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not remove artwork.')
    } finally {
      setBusy(null)
    }
  }, [item.key, item.title, onChange])

  const handleFile = useCallback((file: File | null | undefined) => {
    if (!file) return
    const okType = /^image\/(jpeg|png|webp)$/i.test(file.type)
      || /\.(jpe?g|png|webp)$/i.test(file.name)
    if (!okType) {
      setError('Only JPG, PNG, and WebP images are allowed.')
      return
    }
    upload(file)
  }, [upload])

  const previewUrl = resolveMediaUrl(item.image_url ?? item.thumbnail_url ?? undefined)
  const display = DISPLAY_BY_KEY[item.key] ?? DEFAULT_DISPLAY

  return (
    <section
      className="rounded-2xl bg-white px-6 py-6 md:px-8 md:py-8"
      style={{
        border: '1px solid rgba(12, 24, 38, 0.06)',
        boxShadow: '0 1px 3px rgba(12, 24, 38, 0.03)',
      }}
    >
      <div className="mb-4">
        <h2 className="font-serif text-[20px]" style={{ color: '#0C1826' }}>
          {item.title}
        </h2>
        <p
          className="mt-1 text-[13.5px] italic"
          style={{ color: 'rgba(12, 24, 38, 0.60)', fontFamily: 'Georgia, serif' }}
        >
          {item.description}
        </p>
      </div>

      <div
        onDragOver={(e) => { e.preventDefault(); setDragActive(true) }}
        onDragEnter={(e) => { e.preventDefault(); setDragActive(true) }}
        onDragLeave={(e) => {
          if (e.currentTarget === e.target) setDragActive(false)
        }}
        onDrop={(e) => {
          e.preventDefault()
          setDragActive(false)
          handleFile(e.dataTransfer.files?.[0])
        }}
        className="mb-4 overflow-hidden rounded-2xl bg-white transition-all"
        style={{
          aspectRatio: display.aspectRatio,
          border: dragActive
            ? '1px dashed rgba(56, 160, 158, 0.65)'
            : '1px solid rgba(12, 24, 38, 0.08)',
          boxShadow: dragActive
            ? '0 0 0 6px rgba(56, 160, 158, 0.12), 0 12px 32px rgba(12, 24, 38, 0.08)'
            : '0 6px 20px rgba(12, 24, 38, 0.06)',
        }}
      >
        {previewUrl ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={previewUrl}
            alt={item.title}
            className="h-full w-full"
            style={{ objectFit: 'cover', objectPosition: 'center' }}
          />
        ) : (
          <PlaceholderArt title={item.title} body={display.placeholderBody} />
        )}
      </div>

      <p
        className="mb-3 text-[12.5px] italic"
        style={{ color: 'rgba(12, 24, 38, 0.55)', fontFamily: 'Georgia, serif' }}
      >
        {display.guidance}
      </p>

      {error && (
        <p className="mb-3 text-[13px]" style={{ color: '#A64526' }}>
          {error}
        </p>
      )}

      <div className="flex flex-wrap gap-2">
        <input
          ref={inputRef}
          type="file"
          accept="image/jpeg,image/png,image/webp"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0]
            if (f) handleFile(f)
            e.target.value = ''
          }}
        />
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          disabled={busy !== null}
          className="rounded-full px-6 py-2.5 text-[13px] font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-40"
          style={{
            background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)',
            letterSpacing: '0.06em',
          }}
        >
          {busy === 'upload'
            ? 'Uploading…'
            : item.image_url ? 'Replace artwork' : 'Upload artwork'}
        </button>
        {item.image_url && (
          <button
            type="button"
            onClick={remove}
            disabled={busy !== null}
            className="rounded-full px-4 py-2.5 text-[13px] font-medium transition-colors hover:bg-black/[4%] disabled:opacity-40"
            style={{
              background: '#FFFFFF',
              border: '1px solid rgba(12,24,38,0.14)',
              color: '#0C1826',
            }}
          >
            {busy === 'remove' ? 'Removing…' : 'Remove'}
          </button>
        )}
      </div>
    </section>
  )
}

function PlaceholderArt({ title, body }: { title: string; body?: string }) {
  const safeId = title.replace(/[^\w-]/g, '_')
  return (
    <div className="relative h-full w-full">
      <svg
        viewBox="0 0 400 260"
        preserveAspectRatio="xMidYMid slice"
        className="absolute inset-0 h-full w-full"
        aria-hidden="true"
      >
        <defs>
          <radialGradient id={`pa-ph-${safeId}`} cx="0.5" cy="0.5" r="0.65">
            <stop offset="0%" stopColor="#E5F0EF" />
            <stop offset="60%" stopColor="#F4F7F6" />
            <stop offset="100%" stopColor="#FBFDFC" />
          </radialGradient>
        </defs>
        <rect width="400" height="260" fill={`url(#pa-ph-${safeId})`} />
        <g fill="none" stroke="rgba(56, 160, 158, 0.18)" strokeWidth="0.9">
          <ellipse cx="200" cy="140" rx="120" ry="60" />
          <ellipse cx="200" cy="140" rx="80" ry="40" />
        </g>
      </svg>
      <div className="relative flex h-full w-full items-center justify-center px-6 text-center">
        <div className="max-w-[420px]">
          <p className="font-serif text-[18px] leading-tight md:text-[20px]" style={{ color: '#0C1826' }}>
            {title}
          </p>
          {body ? (
            <p
              className="mt-2 text-[13px] leading-relaxed italic md:text-[13.5px]"
              style={{ color: 'rgba(12, 24, 38, 0.60)', fontFamily: 'Georgia, serif' }}
            >
              {body}
            </p>
          ) : (
            <p
              className="mt-2 text-[13px] italic"
              style={{ color: 'rgba(12, 24, 38, 0.50)', fontFamily: 'Georgia, serif' }}
            >
              No artwork uploaded.
            </p>
          )}
        </div>
      </div>
    </div>
  )
}
