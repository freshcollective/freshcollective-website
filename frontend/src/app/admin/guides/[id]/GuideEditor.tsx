'use client'

import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useRef, useState } from 'react'

import AboutRichTextEditor from '@/components/ui/AboutRichTextEditor'
import { apiUrl } from '@/lib/api'
import { GUIDE_CATEGORIES } from '@/lib/guides'

/**
 * The Guide editor.
 *
 * Save and Publish are separate buttons because they are separate
 * decisions, and the API agrees: ``PATCH`` has no ``status`` field,
 * so there is no way for a save to publish by accident even if this
 * form were wrong about it.
 *
 * The SEO counts are advisory and never block a save. 60 and 155 are
 * where Google starts truncating, not limits anyone agreed to, and a
 * disabled button would be the editor overruling the writer about
 * their own title.
 */

export interface GuideDetail {
  id: string
  slug: string
  title: string
  standfirst: string
  body: string
  category: string
  hero_image_url: string | null
  hero_image_alt: string | null
  seo_title: string | null
  seo_description: string | null
  author_name: string
  featured: boolean
  status: string
  published_at: string | null
  reading_time_minutes: number
  cta_heading: string | null
  cta_text: string | null
  cta_label: string | null
  cta_href: string | null
}

const SEO_TITLE_TARGET = 60
const SEO_DESCRIPTION_TARGET = 155

function slugify(title: string): string {
  return title
    .toLowerCase()
    .replace(/['’]/g, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 160)
    .replace(/-+$/, '')
}

export default function GuideEditor({ initial }: { initial: GuideDetail }) {
  const router = useRouter()
  const [g, setG] = useState<GuideDetail>(initial)
  const [busy, setBusy] = useState<string | null>(null)
  const [message, setMessage] = useState<
    { tone: 'ok' | 'bad'; text: string } | null
  >(null)

  // A slug is a URL that may already be shared, so it follows the
  // title only until someone decides otherwise. Seeded from whether
  // the two already disagree, so reopening a Guide whose slug was
  // hand-edited does not start overwriting it again.
  const slugTouched = useRef(slugify(initial.title) !== initial.slug)

  function set<K extends keyof GuideDetail>(key: K, value: GuideDetail[K]) {
    setG((prev) => ({ ...prev, [key]: value }))
  }

  function onTitle(value: string) {
    setG((prev) => ({
      ...prev,
      title: value,
      slug: slugTouched.current ? prev.slug : slugify(value),
    }))
  }

  /**
   * Nudge the one cached artefact a Guide change touches.
   *
   * ``/guides`` and ``/guides/[slug]`` need nothing — they are
   * uncached and show the change on the next request. ``sitemap.xml``
   * is generated hourly, so this clears it.
   *
   * Deliberately silent, success or failure. A stale sitemap for up
   * to an hour is not something to interrupt the writer about, and
   * telling them a step they did not ask for had failed would read
   * as "the publish did not work" when the publish worked fine.
   */
  async function refreshSitemap() {
    try {
      await fetch(apiUrl('/api/internal/guides/revalidate'), {
        method: 'POST',
        credentials: 'include',
      })
    } catch {
      // See above.
    }
  }

  async function send(
    path: string,
    init: RequestInit,
    okText: string,
    label: string,
  ) {
    setBusy(label)
    setMessage(null)
    try {
      const res = await fetch(apiUrl(path), {
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        ...init,
      })
      if (res.status === 204) {
        // Deleted. The sitemap still lists it until this clears.
        await refreshSitemap()
        router.push('/admin/guides')
        return null
      }
      const data = await res.json().catch(() => null)
      if (!res.ok) {
        setMessage({
          tone: 'bad',
          text: typeof data?.detail === 'string'
            ? data.detail
            : 'That could not be saved.',
        })
        return null
      }
      setG(data as GuideDetail)
      setMessage({ tone: 'ok', text: okText })
      await refreshSitemap()
      return data as GuideDetail
    } catch {
      setMessage({ tone: 'bad', text: 'That could not be saved.' })
      return null
    } finally {
      setBusy(null)
    }
  }

  function save() {
    return send(
      `/api/admin/guides/${g.id}`,
      {
        method: 'PATCH',
        body: JSON.stringify({
          title: g.title,
          slug: g.slug,
          standfirst: g.standfirst,
          body: g.body,
          category: g.category,
          hero_image_url: g.hero_image_url,
          hero_image_alt: g.hero_image_alt,
          seo_title: g.seo_title,
          seo_description: g.seo_description,
          author_name: g.author_name,
          cta_heading: g.cta_heading,
          cta_text: g.cta_text,
          cta_label: g.cta_label,
          cta_href: g.cta_href,
        }),
      },
      'Saved.',
      'save',
    )
  }

  async function publish() {
    // Saved first, or publishing would make the last-saved version
    // public rather than the one on screen.
    const saved = await save()
    if (!saved) return
    await send(
      `/api/admin/guides/${g.id}/publish`,
      { method: 'POST' },
      'Published. It is live on /guides now.',
      'publish',
    )
  }

  function unpublish() {
    return send(
      `/api/admin/guides/${g.id}/unpublish`,
      { method: 'POST' },
      'Unpublished. It is a draft again and no longer public.',
      'unpublish',
    )
  }

  function toggleFeatured() {
    return send(
      `/api/admin/guides/${g.id}/feature`,
      { method: 'POST', body: JSON.stringify({ featured: !g.featured }) },
      g.featured
        ? 'No longer featured.'
        : 'Featured. Any other featured Guide has been cleared.',
      'feature',
    )
  }

  async function remove() {
    const ok = window.confirm(
      `Delete "${g.title}"? This cannot be undone.`,
    )
    if (!ok) return
    await send(`/api/admin/guides/${g.id}`, { method: 'DELETE' }, '', 'delete')
  }

  /** Upload a file and return its stored URL. */
  async function upload(file: File): Promise<string | null> {
    const form = new FormData()
    form.append('file', file)
    const res = await fetch(apiUrl('/api/admin/guides/images'), {
      method: 'POST',
      credentials: 'include',
      body: form,
    })
    const data = await res.json().catch(() => null)
    if (!res.ok) {
      setMessage({
        tone: 'bad',
        text: typeof data?.detail === 'string'
          ? data.detail
          : 'That image could not be uploaded.',
      })
      return null
    }
    return data.url as string
  }

  async function pickHero(file: File | undefined) {
    if (!file) return
    const url = await upload(file)
    if (url) set('hero_image_url', url)
  }

  /** The editor's image button: upload, then ask for alt text. */
  async function requestInlineImage() {
    return new Promise<{ src: string; alt: string } | null>((resolve) => {
      const input = document.createElement('input')
      input.type = 'file'
      input.accept = 'image/png,image/jpeg,image/gif,image/webp'
      input.onchange = async () => {
        const file = input.files?.[0]
        if (!file) return resolve(null)
        const src = await upload(file)
        if (!src) return resolve(null)
        const alt = window.prompt(
          'Describe this image for someone who cannot see it:',
          '',
        )
        resolve({ src, alt: alt ?? '' })
      }
      input.click()
    })
  }

  const heroNeedsAlt =
    !!g.hero_image_url && !(g.hero_image_alt ?? '').trim()
  const published = g.status === 'published'

  return (
    <div className="max-w-[60rem]">
      <nav className="mb-5 text-[13px]">
        <Link href="/admin/guides" className="text-teal-700 hover:text-teal-800">
          ← Guides
        </Link>
      </nav>

      <header className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-[1.5rem] font-bold text-navy-950">
            {g.title || 'Untitled Guide'}
          </h1>
          <p className="mt-1 text-[13px] text-navy-700">
            {published ? 'Published' : 'Draft'} · {g.reading_time_minutes} min read
            {' · '}
            <Link
              href={`/admin/guides/${g.id}/preview`}
              className="text-teal-700 hover:text-teal-800"
            >
              Preview
            </Link>
          </p>
        </div>

        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={save}
            disabled={!!busy || heroNeedsAlt}
            className="rounded-lg border border-navy-200 bg-white px-4 py-2 text-[13.5px] font-semibold text-navy-950 transition-colors hover:border-navy-300 disabled:opacity-50"
          >
            {busy === 'save' ? 'Saving…' : 'Save'}
          </button>
          {published ? (
            <button
              type="button"
              onClick={unpublish}
              disabled={!!busy}
              className="rounded-lg border border-navy-200 bg-white px-4 py-2 text-[13.5px] font-semibold text-navy-950 transition-colors hover:border-navy-300 disabled:opacity-50"
            >
              {busy === 'unpublish' ? 'Unpublishing…' : 'Unpublish'}
            </button>
          ) : (
            <button
              type="button"
              onClick={publish}
              disabled={!!busy || heroNeedsAlt}
              className="rounded-lg bg-teal-700 px-4 py-2 text-[13.5px] font-semibold text-white transition-colors hover:bg-teal-800 disabled:opacity-50"
            >
              {busy === 'publish' ? 'Publishing…' : 'Publish'}
            </button>
          )}
          <button
            type="button"
            onClick={toggleFeatured}
            disabled={!!busy}
            className="rounded-lg border border-navy-200 bg-white px-4 py-2 text-[13.5px] font-semibold text-navy-950 transition-colors hover:border-navy-300 disabled:opacity-50"
          >
            {g.featured ? '★ Featured' : 'Feature'}
          </button>
          <button
            type="button"
            onClick={remove}
            disabled={!!busy}
            className="rounded-lg px-4 py-2 text-[13.5px] font-semibold text-red-700 transition-colors hover:bg-red-50 disabled:opacity-50"
          >
            Delete
          </button>
        </div>
      </header>

      {heroNeedsAlt && (
        <p
          role="alert"
          className="mb-4 rounded-lg bg-amber-50 px-4 py-3 text-[13px] text-amber-900"
        >
          Saving is paused until the hero image has alt text. Describe what the
          image shows, for a reader who cannot see it.
        </p>
      )}

      {message && (
        <p
          role="status"
          className={
            message.tone === 'ok'
              ? 'mb-4 rounded-lg bg-teal-50 px-4 py-3 text-[13px] text-teal-800'
              : 'mb-4 rounded-lg bg-red-50 px-4 py-3 text-[13px] text-red-700'
          }
        >
          {message.text}
        </p>
      )}

      <div className="space-y-6">
        <Panel title="The article">
          <Field label="Title" htmlFor="f-title">
            <input
              id="f-title"
              value={g.title}
              onChange={(e) => onTitle(e.target.value)}
              className={INPUT}
            />
          </Field>

          <Field
            label="Web address"
            htmlFor="f-slug"
            hint="Fills in from the title until you change it. Changing it after publishing breaks any link already shared."
          >
            <div className="flex items-center gap-1.5">
              <span className="text-[13.5px] text-navy-500">/guides/</span>
              <input
                id="f-slug"
                value={g.slug}
                onChange={(e) => { slugTouched.current = true; set('slug', e.target.value) }}
                className={INPUT}
              />
            </div>
          </Field>

          <Field
            label="Standfirst"
            htmlFor="f-standfirst"
            hint="The one sentence under the title. Also the fallback for the search-result description."
          >
            <textarea
              id="f-standfirst"
              value={g.standfirst}
              rows={2}
              onChange={(e) => set('standfirst', e.target.value)}
              className={INPUT}
            />
          </Field>

          <Field label="Category" htmlFor="f-category">
            <select
              id="f-category"
              value={g.category}
              onChange={(e) => set('category', e.target.value)}
              className={INPUT}
            >
              {GUIDE_CATEGORIES.map((c) => (
                <option key={c.slug} value={c.slug}>{c.label}</option>
              ))}
            </select>
          </Field>

          <Field label="Author" htmlFor="f-author" hint='"Linds" gets the founder byline; any other name gets a plain one.'>
            <input
              id="f-author"
              value={g.author_name}
              onChange={(e) => set('author_name', e.target.value)}
              className={INPUT}
            />
          </Field>
        </Panel>

        <Panel title="Hero image">
          <div className="flex flex-wrap items-start gap-4">
            <div className="h-[120px] w-[200px] shrink-0 overflow-hidden rounded-xl bg-teal-50">
              {g.hero_image_url && (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={g.hero_image_url}
                  alt=""
                  className="h-full w-full object-cover"
                />
              )}
            </div>
            <div className="min-w-[240px] flex-1 space-y-3">
              <input
                type="file"
                accept="image/png,image/jpeg,image/gif,image/webp"
                onChange={(e) => pickHero(e.target.files?.[0])}
                className="block w-full text-[13px] text-navy-700"
                aria-label="Upload a hero image"
              />
              <Field label="Alt text (required with an image)" htmlFor="f-alt">
                <input
                  id="f-alt"
                  value={g.hero_image_alt ?? ''}
                  onChange={(e) => set('hero_image_alt', e.target.value)}
                  className={INPUT}
                />
              </Field>
              {g.hero_image_url && (
                <button
                  type="button"
                  onClick={() => { set('hero_image_url', null); set('hero_image_alt', null) }}
                  className="text-[13px] text-red-700 hover:underline"
                >
                  Remove image
                </button>
              )}
            </div>
          </div>
        </Panel>

        <Panel title="Body">
          <AboutRichTextEditor
            value={g.body}
            onChange={(html) => set('body', html)}
            extendedMarks
            blockquote
            onRequestImage={requestInlineImage}
            minHeight="420px"
            placeholder="Write the Guide here. Headings become the “On this page” list."
          />
        </Panel>

        <Panel title="Search engines">
          <Field
            label="SEO title"
            htmlFor="f-seo-title"
            hint="Leave empty to use the Guide's title."
            count={{ value: (g.seo_title ?? '').length, target: SEO_TITLE_TARGET }}
          >
            <input
              id="f-seo-title"
              value={g.seo_title ?? ''}
              onChange={(e) => set('seo_title', e.target.value)}
              className={INPUT}
            />
          </Field>
          <Field
            label="SEO description"
            htmlFor="f-seo-desc"
            hint="Leave empty to use the standfirst."
            count={{
              value: (g.seo_description ?? '').length,
              target: SEO_DESCRIPTION_TARGET,
            }}
          >
            <textarea
              id="f-seo-desc"
              rows={3}
              value={g.seo_description ?? ''}
              onChange={(e) => set('seo_description', e.target.value)}
              className={INPUT}
            />
          </Field>
        </Panel>

        <Panel
          title="Call to action"
          hint="Shown at the end of the article. All four fields, or none."
        >
          <Field label="Heading" htmlFor="f-cta-heading">
            <input
              id="f-cta-heading"
              value={g.cta_heading ?? ''}
              onChange={(e) => set('cta_heading', e.target.value)}
              className={INPUT}
            />
          </Field>
          <Field label="One line of text" htmlFor="f-cta-text">
            <input
              id="f-cta-text"
              value={g.cta_text ?? ''}
              onChange={(e) => set('cta_text', e.target.value)}
              className={INPUT}
            />
          </Field>
          <Field label="Button label" htmlFor="f-cta-label">
            <input
              id="f-cta-label"
              value={g.cta_label ?? ''}
              onChange={(e) => set('cta_label', e.target.value)}
              className={INPUT}
            />
          </Field>
          <Field label="Link" htmlFor="f-cta-href" hint="An https:// address, or a path like /for-creators.">
            <input
              id="f-cta-href"
              value={g.cta_href ?? ''}
              onChange={(e) => set('cta_href', e.target.value)}
              className={INPUT}
            />
          </Field>
        </Panel>
      </div>
    </div>
  )
}

const INPUT =
  'w-full rounded-lg border border-navy-100 px-3 py-2 text-[14px] text-navy-950 focus:border-teal-500 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-200'

function Panel({
  title, hint, children,
}: {
  title: string
  hint?: string
  children: React.ReactNode
}) {
  return (
    <section
      className="rounded-2xl bg-white px-6 py-6"
      style={{ boxShadow: '0 0 0 1px rgba(15,30,55,0.08)' }}
    >
      <h2 className="text-[14px] font-semibold text-navy-950">{title}</h2>
      {hint && <p className="mt-1 text-[12.5px] text-navy-500">{hint}</p>}
      <div className="mt-4 space-y-4">{children}</div>
    </section>
  )
}

function Field({
  label, htmlFor, hint, count, children,
}: {
  label: string
  htmlFor: string
  hint?: string
  count?: { value: number; target: number }
  children: React.ReactNode
}) {
  return (
    <div>
      <div className="mb-1.5 flex items-baseline justify-between gap-3">
        <label htmlFor={htmlFor} className="text-[13px] font-semibold text-navy-950">
          {label}
        </label>
        {count && (
          <span
            className={
              count.value > count.target
                ? 'text-[12px] font-medium text-amber-700'
                : 'text-[12px] text-navy-500'
            }
          >
            {count.value}/{count.target}
            {count.value > count.target && ' — may be trimmed in search results'}
          </span>
        )}
      </div>
      {children}
      {hint && <p className="mt-1.5 text-[12.5px] text-navy-500">{hint}</p>}
    </div>
  )
}
