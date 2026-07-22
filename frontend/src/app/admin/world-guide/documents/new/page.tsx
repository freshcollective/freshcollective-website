'use client'

import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useState } from 'react'
import { apiUrl, extractErrorMessage, type ApiError } from '@/lib/api'
import { AUDIENCE_LABEL, CATEGORY_LABEL, WG } from '@/lib/worldGuide'

/**
 * Create document — shell only.
 *
 * Deliberately minimal. Title, slug, category, audience — that's it.
 * The writing experience (summary, effective date, content, publish)
 * happens in the editor.
 */

function slugify(title: string): string {
  return title
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9\s-]/g, '')
    .replace(/\s+/g, '-')
    .replace(/-+/g, '-')
    .slice(0, 128)
}


export default function NewDocumentPage() {
  const router = useRouter()
  const [title, setTitle] = useState('')
  const [slug, setSlug] = useState('')
  const [slugTouched, setSlugTouched] = useState(false)
  const [category, setCategory] = useState<string>('governance')
  const [audience, setAudience] = useState<string>('everyone')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function updateTitle(next: string) {
    setTitle(next)
    if (!slugTouched) setSlug(slugify(next))
  }

  const canSubmit = !busy && title.trim().length > 0 && slug.trim().length > 0

  async function submit() {
    setBusy(true)
    setError(null)
    try {
      const res = await fetch(apiUrl('/api/admin/world-guide/documents'), {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: title.trim(),
          slug: slug.trim(),
          category,
          audience,
        }),
      })
      if (!res.ok) {
        const body = (await res.json().catch(() => ({}))) as Partial<ApiError>
        setError(body.detail ? extractErrorMessage(body as ApiError) : `Create: ${res.status}`)
        setBusy(false)
        return
      }
      const doc = await res.json() as { id: string }
      router.push(`/admin/world-guide/documents/${doc.id}`)
    } catch (e) {
      setError((e as Error).message); setBusy(false)
    }
  }

  return (
    <div style={{ background: WG.pageBg, minHeight: '100%' }}>
      <div className="mx-auto max-w-[640px] px-6 py-14 md:px-10 md:py-20">

        <Link href="/admin/world-guide/documents" className="text-[13px]" style={{ color: WG.inkMuted }}>
          ← Documents
        </Link>
        <h1
          className="mt-3 font-serif text-[30px] leading-tight md:text-[36px]"
          style={{ color: WG.inkStrong }}
        >
          Create document
        </h1>
        <p className="mt-3 text-[14.5px] leading-relaxed" style={{ color: WG.inkMuted }}>
          Just the shell for now — you&rsquo;ll write the document itself in the editor.
        </p>

        <div className="mt-10 space-y-6">
          <Field label="Title" required>
            <input
              type="text"
              value={title}
              onChange={(e) => updateTitle(e.target.value)}
              placeholder="Terms of Use"
              className="w-full rounded-lg px-3.5 py-2.5 text-[15px] outline-none focus:ring-2"
              style={{
                background: '#FFFFFF',
                border: WG.divider,
                color: WG.ink,
                boxShadow: 'none',
              }}
            />
          </Field>

          <Field label="Slug" required hint="Used in the URL — /world-guide/<slug>">
            <input
              type="text"
              value={slug}
              onChange={(e) => { setSlug(e.target.value); setSlugTouched(true) }}
              placeholder="terms-of-use"
              className="w-full rounded-lg px-3.5 py-2.5 font-mono text-[14px] outline-none"
              style={{ background: '#FFFFFF', border: WG.divider, color: WG.ink }}
            />
          </Field>

          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Category">
              <select
                value={category}
                onChange={(e) => setCategory(e.target.value)}
                className="w-full cursor-pointer rounded-lg px-3.5 py-2.5 text-[14.5px] outline-none"
                style={{ background: '#FFFFFF', border: WG.divider, color: WG.ink }}
              >
                {Object.entries(CATEGORY_LABEL).map(([k, l]) => (
                  <option key={k} value={k}>{l}</option>
                ))}
              </select>
            </Field>

            <Field label="Audience">
              <select
                value={audience}
                onChange={(e) => setAudience(e.target.value)}
                className="w-full cursor-pointer rounded-lg px-3.5 py-2.5 text-[14.5px] outline-none"
                style={{ background: '#FFFFFF', border: WG.divider, color: WG.ink }}
              >
                {Object.entries(AUDIENCE_LABEL).map(([k, l]) => (
                  <option key={k} value={k}>{l}</option>
                ))}
              </select>
            </Field>
          </div>

          {error && (
            <p className="text-[13px]" style={{ color: WG.danger }}>{error}</p>
          )}

          <div className="flex justify-end gap-2 pt-2">
            <Link
              href="/admin/world-guide/documents"
              className="rounded-full px-5 py-2 text-[13.5px]"
              style={{ background: '#FFFFFF', border: WG.divider, color: WG.ink }}
            >
              Cancel
            </Link>
            <button
              type="button"
              disabled={!canSubmit}
              onClick={submit}
              className="rounded-full px-6 py-2 text-[13.5px] font-semibold text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
              style={{ background: WG.navy }}
            >
              {busy ? 'Creating…' : 'Create document'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}


function Field({
  label, hint, required, children,
}: {
  label: string
  hint?: string
  required?: boolean
  children: React.ReactNode
}) {
  return (
    <label className="block">
      <span
        className="mb-1.5 block text-[12px] font-semibold uppercase tracking-wide"
        style={{ color: WG.inkSofter }}
      >
        {label}{required && <span style={{ color: WG.danger }}> *</span>}
      </span>
      {children}
      {hint && (
        <span className="mt-1.5 block text-[12px]" style={{ color: WG.inkSofter }}>
          {hint}
        </span>
      )}
    </label>
  )
}
