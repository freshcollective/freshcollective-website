'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { apiUrl } from '@/lib/api'
import PostTypeTag, { POST_TYPE_OPTIONS } from './PostTypeTag'

/**
 * CommunitySearch — search bar + filter chips + results list.
 *
 * Rendered above the composer on the Community page. Search is
 * strictly scoped to the current collective (server-enforced). Empty
 * query renders nothing so the normal feed stays visible.
 */

interface SearchHit {
  kind: 'post' | 'comment'
  post_id: string
  post_type: string
  post_title: string | null
  author_name: string
  excerpt: string
  created_at: string
  match_field: string
}

interface SearchResponse {
  query: string
  total: number
  hits: SearchHit[]
}

const FILTERS: ReadonlyArray<{ value: string; label: string }> = [
  { value: 'all', label: 'All' },
  ...POST_TYPE_OPTIONS.map((t) => ({
    value: t.value,
    label: t.label === 'Reflection' ? 'Reflections'
         : t.label === 'Question' ? 'Questions'
         : t.label === 'Poll' ? 'Polls'
         : t.label === 'Announcement' ? 'Announcements'
         : t.label === 'Celebration' ? 'Celebrations'
         : `${t.label}s`,
  })),
]

interface Props {
  spaceSlug: string
  /** When set, search scope is limited to this Channel. When omitted,
   *  the backend searches across every Channel the caller can view. */
  channelSlug?: string
}

export default function CommunitySearch({ spaceSlug, channelSlug }: Props) {
  const [q, setQ] = useState('')
  const [type, setType] = useState('all')
  const [busy, setBusy] = useState(false)
  const [results, setResults] = useState<SearchResponse | null>(null)
  const debouncedQ = useDebounced(q, 250)

  useEffect(() => {
    if (!debouncedQ.trim()) {
      setResults(null)
      return
    }
    let cancelled = false
    setBusy(true)
    const channelQ = channelSlug ? `&channel=${encodeURIComponent(channelSlug)}` : ''
    const url = apiUrl(
      `/api/spaces/${spaceSlug}/community/search`
      + `?q=${encodeURIComponent(debouncedQ)}`
      + `&type=${encodeURIComponent(type)}${channelQ}`,
    )
    fetch(url, { credentials: 'include' })
      .then(async (res) => {
        if (!res.ok) return null
        return (await res.json()) as SearchResponse
      })
      .then((data) => {
        if (cancelled) return
        setResults(data)
      })
      .finally(() => {
        if (!cancelled) setBusy(false)
      })
    return () => { cancelled = true }
  }, [debouncedQ, type, spaceSlug, channelSlug])

  return (
    <div className="mb-5">
      <div className="flex items-center gap-2">
        <input
          type="search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search conversations…"
          className="w-full rounded-full border border-border bg-white px-4 py-2 text-sm text-navy-900 placeholder:text-slate-400 focus:border-[color:var(--fc-accent,#38A09E)] focus:outline-none focus:ring-2 focus:ring-[color:var(--fc-accent-soft,rgba(56,160,158,0.10))]"
        />
      </div>

      {q.trim() && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {FILTERS.map((f) => {
            const active = type === f.value
            return (
              <button
                key={f.value}
                type="button"
                onClick={() => setType(f.value)}
                className="rounded-full px-3 py-1 text-[12px] font-medium transition-colors"
                style={active
                  ? { background: 'var(--fc-accent, #0d9488)', color: '#FFFFFF' }
                  : { background: 'transparent', color: 'rgba(12,24,38,0.65)' }}
              >
                {f.label}
              </button>
            )
          })}
        </div>
      )}

      {q.trim() && (
        <div className="mt-4">
          {busy && !results && (
            <p className="text-[13px] text-slate-500">Searching…</p>
          )}
          {results && results.hits.length === 0 && (
            <div
              className="rounded-2xl bg-white px-6 py-8 text-center"
              style={{ border: '1px dashed rgba(12,24,38,0.14)' }}
            >
              <p className="text-[14px] italic" style={{ color: 'rgba(12,24,38,0.62)', fontFamily: 'Georgia, serif' }}>
                Nothing matches &ldquo;{results.query}&rdquo; here.
              </p>
              <p className="mt-1 text-[12px] text-slate-500">
                Try different words, or clear the filter.
              </p>
            </div>
          )}
          {results && results.hits.length > 0 && (
            <div className="flex flex-col gap-2">
              {results.hits.map((h, i) => (
                <SearchResult key={i} spaceSlug={spaceSlug} hit={h} query={debouncedQ} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function SearchResult({ hit, spaceSlug, query }: { hit: SearchHit; spaceSlug: string; query: string }) {
  const href = `/spaces/${spaceSlug}/community/${hit.post_id}`
  return (
    <Link
      href={href}
      className="block rounded-xl bg-white px-4 py-3 transition-colors hover:border-[color:var(--fc-accent-ring,rgba(56,160,158,0.40))]"
      style={{ border: '1px solid rgba(12,24,38,0.08)' }}
    >
      <div className="mb-1 flex items-center gap-2">
        <PostTypeTag type={hit.post_type} />
        {hit.kind === 'comment' && (
          <span className="text-[11px] text-slate-500">Reply by {hit.author_name}</span>
        )}
      </div>
      {hit.post_title && (
        <p className="text-[14px] font-semibold text-navy-900">
          {highlight(hit.post_title, query)}
        </p>
      )}
      <p className="mt-0.5 text-[13px] leading-relaxed text-black line-clamp-2">
        {highlight(hit.excerpt, query)}
      </p>
    </Link>
  )
}

function highlight(text: string, q: string): React.ReactNode {
  if (!q.trim()) return text
  const lower = text.toLowerCase()
  const needle = q.toLowerCase()
  const parts: React.ReactNode[] = []
  let cursor = 0
  let idx = lower.indexOf(needle, cursor)
  while (idx !== -1) {
    if (idx > cursor) parts.push(text.slice(cursor, idx))
    parts.push(
      <mark
        key={idx}
        className="rounded px-0.5"
        style={{ background: 'var(--fc-accent-soft, rgba(56,160,158,0.20))', color: 'inherit' }}
      >
        {text.slice(idx, idx + q.length)}
      </mark>,
    )
    cursor = idx + q.length
    idx = lower.indexOf(needle, cursor)
  }
  if (cursor < text.length) parts.push(text.slice(cursor))
  return parts
}

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return v
}
