'use client'

import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useRef, useState } from 'react'

import { apiUrl } from '@/lib/api'
import { GUIDE_CATEGORIES } from '@/lib/guides'

/**
 * /admin/guides/new — the three things a Guide needs to exist.
 *
 * Title, slug and category, then straight into the editor. Creating
 * a row first means the editor always has somewhere to save into,
 * rather than holding a whole article in browser state and losing it
 * to a closed tab.
 */

/** Title → slug. The same shape the backend validates against. */
function slugify(title: string): string {
  return title
    .toLowerCase()
    .replace(/['’]/g, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 160)
    .replace(/-+$/, '')
}

export default function NewGuidePage() {
  const router = useRouter()
  const [title, setTitle] = useState('')
  const [slug, setSlug] = useState('')
  const [category, setCategory] = useState<string>(GUIDE_CATEGORIES[0].slug)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  // Once the slug has been typed in by hand it stops following the
  // title. A slug is a URL that may already be shared.
  const slugTouched = useRef(false)

  function onTitle(value: string) {
    setTitle(value)
    if (!slugTouched.current) setSlug(slugify(value))
  }

  async function create() {
    setSaving(true)
    setError(null)
    try {
      const res = await fetch(apiUrl('/api/admin/guides'), {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: title.trim(), slug: slug.trim(), category }),
      })
      const data = await res.json().catch(() => null)
      if (!res.ok) {
        setError(
          typeof data?.detail === 'string'
            ? data.detail
            : 'That Guide could not be created.',
        )
        return
      }
      router.push(`/admin/guides/${data.id}`)
    } catch {
      setError('That Guide could not be created.')
    } finally {
      setSaving(false)
    }
  }

  const ready = title.trim().length > 0 && slug.trim().length > 0

  return (
    <div className="max-w-[46rem]">
      <nav className="mb-5 text-[13px]">
        <Link href="/admin/guides" className="text-teal-700 hover:text-teal-800">
          ← Guides
        </Link>
      </nav>

      <h1 className="text-[1.5rem] font-bold text-navy-950">New Guide</h1>
      <p className="mt-1 text-[13px] text-navy-700">
        It starts as a draft. Nothing is public until you publish it.
      </p>

      <div
        className="mt-6 space-y-5 rounded-2xl bg-white px-6 py-6"
        style={{ boxShadow: '0 0 0 1px rgba(15,30,55,0.08)' }}
      >
        <div>
          <label htmlFor="guide-title" className="block text-[13px] font-semibold text-navy-950">
            Title
          </label>
          <input
            id="guide-title"
            value={title}
            onChange={(e) => onTitle(e.target.value)}
            className="mt-1.5 w-full rounded-lg border border-navy-100 px-3 py-2 text-[14px] text-navy-950 focus:border-teal-500 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-200"
          />
        </div>

        <div>
          <label htmlFor="guide-slug" className="block text-[13px] font-semibold text-navy-950">
            Web address
          </label>
          <div className="mt-1.5 flex items-center gap-1.5">
            <span className="text-[13.5px] text-navy-500">/guides/</span>
            <input
              id="guide-slug"
              value={slug}
              onChange={(e) => { slugTouched.current = true; setSlug(e.target.value) }}
              className="flex-1 rounded-lg border border-navy-100 px-3 py-2 text-[14px] text-navy-950 focus:border-teal-500 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-200"
            />
          </div>
          <p className="mt-1.5 text-[12.5px] text-navy-500">
            Fills in from the title until you change it. Lowercase words joined
            by hyphens.
          </p>
        </div>

        <div>
          <label htmlFor="guide-category" className="block text-[13px] font-semibold text-navy-950">
            Category
          </label>
          <select
            id="guide-category"
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            className="mt-1.5 w-full rounded-lg border border-navy-100 px-3 py-2 text-[14px] text-navy-950 focus:border-teal-500 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-200"
          >
            {GUIDE_CATEGORIES.map((c) => (
              <option key={c.slug} value={c.slug}>{c.label}</option>
            ))}
          </select>
        </div>

        {error && (
          <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-[13px] text-red-700">
            {error}
          </p>
        )}

        <button
          type="button"
          onClick={create}
          disabled={!ready || saving}
          className="rounded-lg bg-teal-700 px-5 py-2.5 text-[14px] font-semibold text-white transition-colors hover:bg-teal-800 disabled:opacity-50"
        >
          {saving ? 'Creating…' : 'Create and start writing'}
        </button>
      </div>
    </div>
  )
}
