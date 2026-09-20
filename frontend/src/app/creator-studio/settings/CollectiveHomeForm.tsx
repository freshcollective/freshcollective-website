'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import Link from 'next/link'

import ImagePickerField from '@/components/creator/ImagePickerField'
import { apiUrl } from '@/lib/api'
import {
  DEFAULT_TILE_ORDER,
  HOME_TILE_LABEL,
  HOME_TILE_DEFAULT_COPY,
  MAX_HOME_DESCRIPTION,
  type TileKey,
} from '@/lib/collectiveHomeTiles'

/**
 * Collective Home editor — tile order, visibility, imagery and copy.
 *
 * Lives in the Collective Home tab of Collective Settings, below the
 * member-directory setting that decides whether a Members tile may be
 * offered at all. No new settings area was invented for it.
 *
 * Ordering uses the ↑ / ↓ buttons the platform already uses in the
 * Offer Page editor and the pathway Step list. Drag-and-drop would be
 * a new interaction to build, test and make keyboard-accessible, for
 * a list of six.
 *
 * No live preview. The Offer Page editor — the closest comparable
 * surface — links out with "Preview →" rather than embedding a
 * renderer, and matching that costs nothing where a live preview would
 * mean running the member Home inside Creator Studio with a second
 * theme scope. The "View Collective Home" link does the same job
 * honestly, showing the real page.
 */

interface TileState {
  key: TileKey
  visible: boolean
  image_url: string | null
  description: string
}

interface Props {
  slug: string
  /** Bumped by the settings tab when the member-directory setting
   *  saves. Refetching is how the Members row appears or disappears
   *  without a page reload — the server owns which tiles may be
   *  offered, so the client asks again rather than guessing. */
  reloadKey?: number
}

/** Stored rows first in their saved order, then every remaining tile
 *  the platform permits. That is what lets a Collective configured
 *  before a tile type existed still be offered it, without anyone
 *  migrating stored configuration. */
function seedRows(
  availableKeys: TileKey[],
  stored: { key: string; visible?: boolean; image_url?: string | null; description?: string | null }[],
): TileState[] {
  const known = stored.filter((t): t is typeof t & { key: TileKey } =>
    availableKeys.includes(t.key as TileKey))
  const seen = new Set(known.map((t) => t.key))
  return [
    ...known.map((t) => ({
      key: t.key,
      visible: t.visible !== false,
      image_url: t.image_url ?? null,
      description: t.description ?? '',
    })),
    ...availableKeys.filter((k) => !seen.has(k)).map((k) => ({
      key: k, visible: true, image_url: null, description: '',
    })),
  ]
}

export default function CollectiveHomeForm({ slug, reloadKey = 0 }: Props) {
  const [tiles, setTiles] = useState<TileState[]>([])
  const [loaded, setLoaded] = useState(false)
  const [saving, setSaving] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const liveRegion = useRef<HTMLParagraphElement | null>(null)

  // Loaded from the endpoint rather than threaded through the settings
  // shell: the creator space payload carries neither the stored config
  // nor the privacy rule that decides which tiles may be offered, and
  // widening it for one tab would have pushed both onto every other
  // Creator Studio surface that reads it.
  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const res = await fetch(apiUrl(`/api/creator/spaces/${slug}/home-config`), {
          credentials: 'include',
        })
        if (!res.ok) throw new Error('load failed')
        const data = await res.json() as {
          home_config: { tiles?: TileState[] } | null
          available_keys: TileKey[]
        }
        if (cancelled) return
        // Re-seed from whatever is on screen rather than from storage,
        // so unsaved edits survive a directory toggle; only the set of
        // permitted tiles changes under them. First load has nothing on
        // screen yet and falls back to the stored configuration.
        setTiles((prev) => seedRows(
          data.available_keys,
          prev.length > 0 ? prev : (data.home_config?.tiles ?? []),
        ))
      } catch {
        if (!cancelled) {
          setTiles(seedRows(DEFAULT_TILE_ORDER, []))
          setError('Could not load the saved layout — showing defaults.')
        }
      } finally {
        if (!cancelled) setLoaded(true)
      }
    })()
    return () => { cancelled = true }
  }, [slug, reloadKey])

  const move = useCallback((index: number, delta: number) => {
    setTiles((prev) => {
      const next = [...prev]
      const target = index + delta
      if (target < 0 || target >= next.length) return prev
      ;[next[index], next[target]] = [next[target], next[index]]
      return next
    })
  }, [])

  const patch = useCallback((key: TileKey, change: Partial<TileState>) => {
    setTiles((prev) => prev.map((t) => (t.key === key ? { ...t, ...change } : t)))
  }, [])

  const save = useCallback(async () => {
    setSaving(true)
    setError(null)
    setNotice(null)
    try {
      const res = await fetch(apiUrl(`/api/creator/spaces/${slug}/home-config`), {
        method: 'PUT',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          tiles: tiles.map((t) => ({
            key: t.key,
            visible: t.visible,
            image_url: t.image_url,
            description: t.description.trim() || null,
          })),
        }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        throw new Error(
          typeof data.detail === 'string' ? data.detail : 'Could not save the Home layout.',
        )
      }
      setNotice('Collective Home saved.')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save the Home layout.')
    } finally {
      setSaving(false)
    }
  }, [slug, tiles])

  const visibleCount = tiles.filter((t) => t.visible).length
  if (!loaded) {
    return (
      <section className="rounded-2xl bg-white px-6 py-6" style={{ border: '1px solid rgba(12,24,38,0.08)' }}>
        <p className="text-[13.5px] text-slate-500">Loading the Home layout…</p>
      </section>
    )
  }

  return (
    <section className="rounded-2xl bg-white px-6 py-6 md:px-8 md:py-7"
      style={{ border: '1px solid rgba(12,24,38,0.08)' }}>
      <div className="mb-5 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h3 className="font-serif text-[20px] text-navy-900">Collective Home</h3>
          <p className="mt-1.5 max-w-[560px] text-[13.5px] leading-relaxed text-slate-600">
            The first thing members see when they enter. Choose which
            doorways appear, what order they sit in, and how each one
            looks. Everything here is optional — leave it alone and
            members get a complete Home.
          </p>
        </div>
        <Link
          href={`/spaces/${slug}`}
          className="shrink-0 rounded-full border border-slate-200 px-4 py-2 text-[13px] font-semibold text-slate-700 transition-colors hover:bg-slate-50"
        >
          View Collective Home →
        </Link>
      </div>

      {visibleCount === 0 && (
        <p className="mb-4 rounded-lg bg-amber-50 px-3 py-2.5 text-[12.5px] text-amber-800">
          Every tile is hidden. Members will still reach these areas from
          the Collective navigation, but the Home will be empty.
        </p>
      )}

      <ul className="list-none space-y-4 p-0">
        {tiles.map((tile, index) => (
          <li
            key={tile.key}
            className="rounded-xl px-4 py-4"
            style={{ border: '1px solid rgba(12,24,38,0.08)' }}
          >
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <span className="font-semibold text-[14.5px] text-navy-900">
                  {HOME_TILE_LABEL[tile.key]}
                </span>
                {!tile.visible && (
                  <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10.5px] font-semibold uppercase tracking-[0.12em] text-slate-500">
                    Hidden
                  </span>
                )}
              </div>
              <div className="flex items-center gap-1">
                <button
                  type="button" onClick={() => move(index, -1)} disabled={index === 0}
                  aria-label={`Move ${HOME_TILE_LABEL[tile.key]} up`}
                  className="rounded p-1 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700 disabled:opacity-30"
                  title="Move up"
                >↑</button>
                <button
                  type="button" onClick={() => move(index, 1)} disabled={index === tiles.length - 1}
                  aria-label={`Move ${HOME_TILE_LABEL[tile.key]} down`}
                  className="rounded p-1 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700 disabled:opacity-30"
                  title="Move down"
                >↓</button>
                <label className="ml-2 inline-flex items-center gap-2 text-[13px] text-slate-600">
                  <input
                    type="checkbox"
                    checked={tile.visible}
                    onChange={(e) => patch(tile.key, { visible: e.target.checked })}
                  />
                  Show
                </label>
              </div>
            </div>

            <div className="mt-3 grid gap-3 md:grid-cols-2">
              <div>
                <label className="mb-1 block text-[12px] font-medium text-slate-600">
                  Description
                </label>
                <input
                  type="text"
                  value={tile.description}
                  maxLength={MAX_HOME_DESCRIPTION}
                  placeholder={HOME_TILE_DEFAULT_COPY[tile.key]}
                  onChange={(e) => patch(tile.key, { description: e.target.value })}
                  className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[13.5px]"
                />
                <p className="mt-1 text-[11.5px] text-slate-500">
                  Leave blank to use the Fresh Collective wording shown above.
                </p>
              </div>
              <div>
                <label className="mb-1 block text-[12px] font-medium text-slate-600">
                  Image
                </label>
                <ImagePickerField
                  spaceSlug={slug}
                  value={tile.image_url}
                  onChange={(url) => patch(tile.key, { image_url: url })}
                />
                <p className="mt-1 text-[11.5px] text-slate-500">
                  Optional. Without one, the tile uses Fresh Collective
                  artwork for this area, then your Collective&rsquo;s colours.
                </p>
              </div>
            </div>
          </li>
        ))}
      </ul>

      <div className="mt-5 flex flex-wrap items-center gap-3">
        <button
          type="button" onClick={save} disabled={saving}
          className="rounded-full px-5 py-2.5 text-[13.5px] font-semibold text-white transition-opacity disabled:opacity-50"
          style={{ background: 'var(--fc-accent-500, #38A09E)' }}
        >
          {saving ? 'Saving…' : 'Save Home layout'}
        </button>
        <p ref={liveRegion} aria-live="polite" className="text-[13px]">
          {notice && <span className="text-teal-700">{notice}</span>}
          {error && <span className="text-red-600">{error}</span>}
        </p>
      </div>
    </section>
  )
}
