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
}
const DEFAULT_DISPLAY: SlotDisplay = {
  aspectRatio: '3 / 2',
  guidance: 'Drag & drop a JPG, PNG or WebP onto the preview — or use the buttons below.',
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

      <div className="space-y-8">
        {items.map((item) => (
          <ArtworkRow key={item.key} item={item} onChange={replaceItem} />
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
