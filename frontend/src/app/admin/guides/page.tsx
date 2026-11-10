'use client'

import Link from 'next/link'
import { useCallback, useEffect, useState } from 'react'

import { apiUrl } from '@/lib/api'
import { categoryLabel, formatGuideDate } from '@/lib/guides'

/**
 * /admin/guides — the work list.
 *
 * Ordered by when each Guide was last touched rather than when it
 * was published, because this is a list of work: the one you were
 * editing belongs at the top whether or not it has ever gone live.
 */

interface Row {
  id: string
  slug: string
  title: string
  category: string
  status: string
  featured: boolean
  published_at: string | null
  updated_at: string
  reading_time_minutes: number
}

const FILTERS = [
  { value: 'all', label: 'All' },
  { value: 'draft', label: 'Drafts' },
  { value: 'published', label: 'Published' },
] as const

export default function AdminGuidesPage() {
  const [rows, setRows] = useState<Row[] | null>(null)
  const [filter, setFilter] = useState<string>('all')
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    const query = filter === 'all' ? '' : `?status=${filter}`
    fetch(apiUrl(`/api/admin/guides${query}`), { credentials: 'include' })
      .then(async (r) => {
        if (!r.ok) throw new Error(`Guides: ${r.status}`)
        return r.json() as Promise<Row[]>
      })
      .then((data) => { setRows(data); setError(null) })
      .catch((e: Error) => setError(e.message))
  }, [filter])

  useEffect(load, [load])

  return (
    <div>
      <header className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-[1.5rem] font-bold text-navy-950">Guides</h1>
          <p className="mt-1 text-[13px] text-navy-700">
            Free, public articles. Anyone can read them without an account.
          </p>
        </div>
        <Link
          href="/admin/guides/new"
          className="inline-flex items-center rounded-lg bg-teal-700 px-4 py-2.5 text-[14px] font-semibold text-white transition-colors hover:bg-teal-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400 focus-visible:ring-offset-2"
        >
          New Guide
        </Link>
      </header>

      <StarterKitPanel />

      <div className="mb-4 flex gap-2" role="group" aria-label="Filter by status">
        {FILTERS.map((f) => {
          const on = filter === f.value
          return (
            <button
              key={f.value}
              type="button"
              aria-pressed={on}
              onClick={() => setFilter(f.value)}
              className={
                on
                  ? 'rounded-lg bg-navy-950 px-3.5 py-1.5 text-[13px] font-medium text-white'
                  : 'rounded-lg border border-navy-100 bg-white px-3.5 py-1.5 text-[13px] font-medium text-navy-700 transition-colors hover:border-navy-200'
              }
            >
              {f.label}
            </button>
          )
        })}
      </div>

      {error && (
        <p className="rounded-lg bg-red-50 px-4 py-3 text-[13px] text-red-700">
          {error}
        </p>
      )}

      {rows === null && !error && (
        <p className="py-8 text-[13px] text-navy-500">Loading…</p>
      )}

      {rows !== null && rows.length === 0 && (
        <div
          className="rounded-2xl bg-white px-6 py-10 text-center"
          style={{ boxShadow: '0 0 0 1px rgba(15,30,55,0.08)' }}
        >
          <p className="text-[14px] text-navy-700">
            No Guides here yet.
          </p>
        </div>
      )}

      {rows !== null && rows.length > 0 && (
        <div
          className="overflow-x-auto rounded-2xl bg-white"
          style={{ boxShadow: '0 0 0 1px rgba(15,30,55,0.08)' }}
        >
          <table className="w-full min-w-[720px] text-left text-[13.5px]">
            <thead>
              <tr className="border-b border-navy-50 text-[12px] uppercase tracking-wide text-navy-500">
                <th scope="col" className="px-5 py-3 font-semibold">Title</th>
                <th scope="col" className="px-5 py-3 font-semibold">Category</th>
                <th scope="col" className="px-5 py-3 font-semibold">Status</th>
                <th scope="col" className="px-5 py-3 font-semibold">Published</th>
                <th scope="col" className="px-5 py-3 font-semibold">Featured</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id} className="border-b border-navy-50 last:border-0">
                  <td className="px-5 py-3.5">
                    <Link
                      href={`/admin/guides/${row.id}`}
                      className="font-medium text-navy-950 underline-offset-2 hover:underline"
                    >
                      {row.title}
                    </Link>
                    <span className="block text-[12px] text-navy-500">
                      /guides/{row.slug}
                    </span>
                  </td>
                  <td className="px-5 py-3.5 text-navy-700">
                    {categoryLabel(row.category)}
                  </td>
                  <td className="px-5 py-3.5">
                    <StatusPill status={row.status} />
                  </td>
                  <td className="px-5 py-3.5 text-navy-700">
                    {row.published_at ? formatGuideDate(row.published_at) : '—'}
                  </td>
                  <td className="px-5 py-3.5">
                    {row.featured
                      ? <span className="text-navy-950">★ Featured</span>
                      : <span className="text-navy-300">—</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function StatusPill({ status }: { status: string }) {
  const published = status === 'published'
  return (
    <span
      className={
        published
          ? 'inline-flex items-center rounded-full bg-teal-50 px-2.5 py-1 text-[12px] font-medium text-teal-800'
          : 'inline-flex items-center rounded-full bg-navy-50 px-2.5 py-1 text-[12px] font-medium text-navy-500'
      }
    >
      {published ? 'Published' : 'Draft'}
    </span>
  )
}

/**
 * The one setting that switches the Creator Starter Kit on.
 *
 * Sits above the list because it is the thing most likely to be
 * looked for and least likely to be found anywhere else. The help
 * text says plainly what empty means, so nobody has to deduce it
 * from the absence of a band on a public page.
 */
function StarterKitPanel() {
  const [url, setUrl] = useState('')
  const [loaded, setLoaded] = useState(false)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState<{ tone: 'ok' | 'bad'; text: string } | null>(
    null,
  )

  useEffect(() => {
    fetch(apiUrl('/api/admin/guides/settings'), { credentials: 'include' })
      .then(async (r) => (r.ok ? r.json() : null))
      .then((data: { starter_kit_url: string | null } | null) => {
        setUrl(data?.starter_kit_url ?? '')
        setLoaded(true)
      })
      .catch(() => setLoaded(true))
  }, [])

  async function save() {
    setSaving(true)
    setMessage(null)
    try {
      const res = await fetch(apiUrl('/api/admin/guides/settings'), {
        method: 'PUT',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ starter_kit_url: url.trim() || null }),
      })
      const data = await res.json().catch(() => null)
      if (!res.ok) {
        setMessage({
          tone: 'bad',
          text: data?.detail ?? 'That link could not be saved.',
        })
      } else {
        setUrl(data?.starter_kit_url ?? '')
        setMessage({
          tone: 'ok',
          text: data?.starter_kit_url
            ? 'Saved. The Starter Kit now appears on Guides.'
            : 'Cleared. The Starter Kit is hidden again.',
        })
      }
    } catch {
      setMessage({ tone: 'bad', text: 'That link could not be saved.' })
    } finally {
      setSaving(false)
    }
  }

  return (
    <section
      className="mb-6 rounded-2xl bg-white px-5 py-5"
      style={{ boxShadow: '0 0 0 1px rgba(15,30,55,0.08)' }}
      aria-labelledby="starter-kit-setting"
    >
      <h2 id="starter-kit-setting" className="text-[14px] font-semibold text-navy-950">
        Creator Starter Kit link
      </h2>
      <p className="mt-1 max-w-[70ch] text-[13px] leading-[1.6] text-navy-700">
        Leave this empty and the Starter Kit is hidden everywhere — no band at
        the foot of Guides, no card in any Guide&apos;s sidebar. Add a link and
        both appear.
      </p>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <label htmlFor="starter-kit-url" className="sr-only">
          Creator Starter Kit link
        </label>
        <input
          id="starter-kit-url"
          type="url"
          value={url}
          disabled={!loaded}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://… or /for-creators"
          className="min-w-[260px] flex-1 rounded-lg border border-navy-100 px-3 py-2 text-[13.5px] text-navy-950 focus:border-teal-500 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-200"
        />
        <button
          type="button"
          onClick={save}
          disabled={saving || !loaded}
          className="rounded-lg bg-navy-950 px-4 py-2 text-[13.5px] font-semibold text-white transition-colors hover:bg-navy-900 disabled:opacity-50"
        >
          {saving ? 'Saving…' : 'Save'}
        </button>
      </div>

      {message && (
        <p
          role="status"
          className={
            message.tone === 'ok'
              ? 'mt-2 text-[13px] text-teal-800'
              : 'mt-2 text-[13px] text-red-700'
          }
        >
          {message.text}
        </p>
      )}
    </section>
  )
}
