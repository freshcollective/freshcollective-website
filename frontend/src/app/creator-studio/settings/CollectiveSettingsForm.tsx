'use client'

import { useRef, useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { apiUrl } from '@/lib/api'
import { COLLECTIVE_THEMES } from '@/lib/themes'
import type { CreatorSpaceDetail } from '@/types/platform'

const ALLOWED_IMAGE_TYPES = ['image/jpeg', 'image/png']
const ALLOWED_IMAGE_EXTS = ['.jpg', '.jpeg', '.png']

const TIMEZONE_OPTIONS = [
  { value: 'Australia/Melbourne', label: 'Melbourne (AEST / AEDT)' },
  { value: 'Australia/Sydney',    label: 'Sydney (AEST / AEDT)' },
  { value: 'Australia/Brisbane',  label: 'Brisbane (AEST)' },
  { value: 'Australia/Adelaide',  label: 'Adelaide (ACST / ACDT)' },
  { value: 'Australia/Perth',     label: 'Perth (AWST)' },
  { value: 'Pacific/Auckland',    label: 'Auckland (NZST / NZDT)' },
  { value: 'Europe/London',       label: 'London (GMT / BST)' },
  { value: 'America/New_York',    label: 'New York (EST / EDT)' },
  { value: 'America/Los_Angeles', label: 'Los Angeles (PST / PDT)' },
  { value: 'UTC',                 label: 'UTC' },
]

// TODO: Connect banner upload to storage once file upload API is available in production.
// Currently uses the local file storage backend (backend/uploads/covers/).

interface Props {
  space: CreatorSpaceDetail
}

export default function CollectiveSettingsForm({ space }: Props) {
  const router = useRouter()
  const fileInputRef = useRef<HTMLInputElement>(null)

  // Text fields
  const [name, setName] = useState(space.name)
  const [slug, setSlug] = useState(space.slug)
  const [slugOrigin, setSlugOrigin] = useState('')
  const [tagline, setTagline] = useState(space.tagline ?? '')
  const [description, setDescription] = useState(space.description ?? '')
  const [timezone, setTimezone] = useState(space.timezone ?? 'Australia/Melbourne')
  const [isPublic, setIsPublic] = useState(space.is_public)
  const [status, setStatus] = useState(space.status)
  const [themes, setThemes] = useState<string[]>(space.themes ?? [])

  useEffect(() => {
    setSlugOrigin(window.location.origin)
  }, [])

  // Banner
  const [bannerFile, setBannerFile] = useState<File | null>(null)
  const [bannerPreview, setBannerPreview] = useState<string | null>(null)
  const [existingBanner, setExistingBanner] = useState<string | null>(space.cover_image_url)
  const [bannerError, setBannerError] = useState<string | null>(null)
  const [bannerUploading, setBannerUploading] = useState(false)
  const [bannerSaved, setBannerSaved] = useState(false)

  // Form state
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)

  function handleFileSelect(e: React.ChangeEvent<HTMLInputElement>) {
    setBannerError(null)
    setBannerSaved(false)
    const file = e.target.files?.[0]
    if (!file) return

    if (!ALLOWED_IMAGE_TYPES.includes(file.type)) {
      setBannerError('Please select a JPG or PNG image.')
      return
    }

    setBannerFile(file)
    const preview = URL.createObjectURL(file)
    setBannerPreview(preview)
  }

  async function uploadBanner() {
    if (!bannerFile) return
    setBannerUploading(true)
    setBannerError(null)
    try {
      const formData = new FormData()
      formData.append('file', bannerFile)
      const res = await fetch(apiUrl(`/api/creator/spaces/${space.slug}/cover`), {
        method: 'POST',
        credentials: 'include',
        body: formData,
      })
      if (!res.ok) {
        const b = await res.json().catch(() => ({}))
        throw new Error(typeof b.detail === 'string' ? b.detail : `Upload failed (${res.status})`)
      }
      const data = await res.json()
      setExistingBanner(data.cover_image_url ?? null)
      setBannerFile(null)
      setBannerPreview(null)
      setBannerSaved(true)
      if (fileInputRef.current) fileInputRef.current.value = ''
    } catch (err) {
      setBannerError(err instanceof Error ? err.message : 'Upload failed. Please try again.')
    } finally {
      setBannerUploading(false)
    }
  }

  const SLUG_RE = /^[a-z0-9]([a-z0-9-]*[a-z0-9])?$/

  function handleSlugChange(e: React.ChangeEvent<HTMLInputElement>) {
    const formatted = e.target.value
      .toLowerCase()
      .replace(/\s+/g, '-')
      .replace(/[^a-z0-9-]/g, '')
      .replace(/-{2,}/g, '-')
    setSlug(formatted)
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!name.trim()) {
      setError('Collective name is required.')
      return
    }
    const trimmedSlug = slug.trim()
    if (!trimmedSlug) {
      setError('Collective URL is required.')
      return
    }
    if (!SLUG_RE.test(trimmedSlug)) {
      setError('Collective URL must use only lowercase letters, numbers, and hyphens, and cannot start or end with a hyphen.')
      return
    }

    setSaving(true)
    setError(null)
    setSaved(false)

    try {
      const res = await fetch(apiUrl(`/api/creator/spaces/${space.slug}`), {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          name: name.trim(),
          slug: trimmedSlug,
          tagline: tagline.trim() || null,
          description: description.trim() || null,
          is_public: isPublic,
          status,
          timezone,
          themes,
        }),
      })

      if (!res.ok) {
        const b = await res.json().catch(() => ({}))
        throw new Error(typeof b.detail === 'string' ? b.detail : `Save failed (${res.status})`)
      }

      const saved = await res.json() as { slug: string }

      if (saved.slug !== space.slug) {
        // Slug changed — update the active-collective cookie then reload settings
        document.cookie = `fc_creator_space=${saved.slug}; path=/; max-age=86400`
        router.push('/creator-studio/settings')
      } else {
        setSaved(true)
        router.refresh()
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong. Please try again.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-5">

      {/* ── Collective identity ── */}
      <div className="rounded-2xl border border-border bg-white p-6">
        <h2 className="mb-1 text-[17px] font-semibold text-navy-900">Collective identity</h2>
        <p className="mb-5 text-[14px] text-slate-500">
          The name, tagline, and description that define your collective.
        </p>

        <div className="space-y-4">
          <div>
            <label htmlFor="s-name" className="mb-1.5 block text-[14px] font-semibold text-navy-900">
              Collective name <span style={{ color: '#38A09E' }} aria-hidden="true">*</span>
            </label>
            <input
              id="s-name"
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={200}
              className="w-full rounded-xl border border-slate-200 bg-slate-50/70 px-4 py-2.5 text-[14px] text-navy-900 placeholder:text-slate-400 transition-colors focus:border-teal-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-teal-400/20"
            />
          </div>

          {/* ── Collective URL (slug) ── */}
          <div>
            <label htmlFor="s-slug" className="mb-1.5 block text-[14px] font-semibold text-navy-900">
              Collective URL
            </label>
            <div className="flex overflow-hidden rounded-xl border border-slate-200 bg-slate-50/70 transition-colors focus-within:border-teal-400 focus-within:bg-white focus-within:ring-2 focus-within:ring-teal-400/20">
              <span
                className="flex shrink-0 items-center border-r border-slate-200 bg-slate-100 px-3 py-2.5 text-[13px] text-slate-400 select-none"
                aria-hidden="true"
              >
                {slugOrigin || 'https://…'}/spaces/
              </span>
              <input
                id="s-slug"
                type="text"
                value={slug}
                onChange={handleSlugChange}
                maxLength={80}
                spellCheck={false}
                autoCapitalize="none"
                autoCorrect="off"
                className="flex-1 bg-transparent px-3 py-2.5 text-[14px] text-navy-900 placeholder:text-slate-400 focus:outline-none"
                placeholder="your-collective-name"
              />
            </div>
            <p className="mt-1.5 text-[12px] text-slate-400">
              This is your collective&apos;s public link. Use lowercase letters, numbers, and hyphens. Changing this will break any existing links.
            </p>
          </div>

          <div>
            <label htmlFor="s-tagline" className="mb-1.5 block text-[14px] font-semibold text-navy-900">
              Short tagline
            </label>
            <input
              id="s-tagline"
              type="text"
              value={tagline}
              onChange={(e) => setTagline(e.target.value)}
              maxLength={300}
              placeholder="A short sentence describing your collective."
              className="w-full rounded-xl border border-slate-200 bg-slate-50/70 px-4 py-2.5 text-[14px] text-navy-900 placeholder:text-slate-400 transition-colors focus:border-teal-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-teal-400/20"
            />
          </div>

          <div>
            <label htmlFor="s-desc" className="mb-1.5 block text-[14px] font-semibold text-navy-900">
              Description
            </label>
            <textarea
              id="s-desc"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={4}
              placeholder="Who is this for? What change does your collective support? What will people experience?"
              className="w-full resize-none rounded-xl border border-slate-200 bg-slate-50/70 px-4 py-2.5 text-[14px] text-navy-900 placeholder:text-slate-400 transition-colors focus:border-teal-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-teal-400/20"
            />
          </div>

          <div>
            <label htmlFor="s-timezone" className="mb-1.5 block text-[14px] font-semibold text-navy-900">
              Timezone
            </label>
            <select
              id="s-timezone"
              value={timezone}
              onChange={(e) => setTimezone(e.target.value)}
              className="w-full rounded-xl border border-slate-200 bg-slate-50/70 px-4 py-2.5 text-[14px] text-navy-900 transition-colors focus:border-teal-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-teal-400/20"
            >
              {TIMEZONE_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
            <p className="mt-1.5 text-[12px] text-slate-400">
              Used to display gathering dates and times for members.
            </p>
          </div>

          {/* ── Collective themes ── */}
          <div>
            <p className="mb-1.5 text-[14px] font-semibold text-navy-900">Collective themes</p>
            <p className="mb-3 text-[13px] text-slate-500">
              Choose the themes that best describe this collective.
            </p>
            <div className="flex flex-wrap gap-2">
              {COLLECTIVE_THEMES.map((theme) => {
                const selected = themes.includes(theme)
                return (
                  <button
                    key={theme}
                    type="button"
                    onClick={() =>
                      setThemes((prev) =>
                        selected ? prev.filter((t) => t !== theme) : [...prev, theme],
                      )
                    }
                    className="rounded-lg border px-3.5 py-1.5 text-[13px] font-medium transition-all"
                    style={
                      selected
                        ? {
                            borderColor: 'rgba(56,160,158,0.50)',
                            background: 'rgba(56,160,158,0.10)',
                            color: '#1E6E6C',
                          }
                        : {
                            borderColor: '#e2e8f0',
                            background: 'transparent',
                            color: '#6B7A8D',
                          }
                    }
                  >
                    {theme}
                  </button>
                )
              })}
            </div>
            {themes.length === 0 && (
              <p className="mt-2 text-[12px]" style={{ color: '#94a3b8' }}>
                Select at least one theme so members can find your collective.
              </p>
            )}
          </div>
        </div>
      </div>

      {/* ── Banner image ── */}
      <div className="rounded-2xl border border-border bg-white p-6">
        <h2 className="mb-1 text-[17px] font-semibold text-navy-900">Banner image</h2>
        <p className="mb-5 text-[14px] text-slate-500">
          Add a banner to give your collective a stronger visual identity.
        </p>

        {/* Current banner indicator */}
        {existingBanner && !bannerPreview && (
          <div
            className="mb-4 flex items-center gap-3 rounded-xl px-4 py-3"
            style={{ background: 'rgba(56,160,158,0.07)', border: '1px solid rgba(56,160,158,0.18)' }}
          >
            <div
              className="h-3 w-3 rounded-full"
              style={{ background: '#38A09E' }}
            />
            <p className="text-[13px] text-slate-600">
              Banner uploaded.{' '}
              <span className="text-slate-400">Upload a new image to replace it.</span>
            </p>
          </div>
        )}

        {/* Preview of selected file */}
        {bannerPreview && (
          <div className="mb-4 overflow-hidden rounded-xl border border-slate-200">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={bannerPreview}
              alt="Banner preview"
              className="h-40 w-full object-cover"
            />
          </div>
        )}

        {/* File input */}
        <div
          className="flex flex-col gap-3 rounded-xl border-2 border-dashed px-5 py-5 transition-colors"
          style={{ borderColor: 'rgba(56,160,158,0.25)' }}
        >
          <p className="text-[13px] text-slate-500">
            {bannerFile ? bannerFile.name : 'No file selected'}
          </p>
          <div className="flex flex-wrap items-center gap-3">
            <label
              htmlFor="banner-upload"
              className="cursor-pointer rounded-xl border border-border bg-white px-4 py-2 text-[13px] font-medium text-slate-600 transition-colors hover:border-teal-200 hover:text-teal-700"
            >
              Choose image
            </label>
            <input
              id="banner-upload"
              ref={fileInputRef}
              type="file"
              accept={ALLOWED_IMAGE_EXTS.join(',')}
              onChange={handleFileSelect}
              className="sr-only"
            />
            {bannerFile && (
              <button
                type="button"
                onClick={uploadBanner}
                disabled={bannerUploading}
                className="rounded-xl px-4 py-2 text-[13px] font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-60"
                style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
              >
                {bannerUploading ? 'Uploading…' : 'Upload banner'}
              </button>
            )}
          </div>
          <p className="text-[12px] text-slate-400">
            Recommended: wide image, JPG or PNG. Max 10 MB.
          </p>
        </div>

        {bannerError && (
          <p className="mt-2 text-[13px]" style={{ color: '#dc2626' }}>{bannerError}</p>
        )}
        {bannerSaved && !bannerError && (
          <p className="mt-2 text-[13px]" style={{ color: '#38A09E' }}>
            Banner saved successfully.
          </p>
        )}
      </div>

      {/* ── Visibility and access ── */}
      <div className="rounded-2xl border border-border bg-white p-6">
        <h2 className="mb-1 text-[17px] font-semibold text-navy-900">Visibility and access</h2>
        <p className="mb-5 text-[14px] text-slate-500">
          Control who can find and join this collective.
        </p>

        <div className="space-y-4">
          {/* Status */}
          <div>
            <p className="mb-2.5 text-[14px] font-semibold text-navy-900">Status</p>
            <div className="grid gap-2 sm:grid-cols-2">
              {([
                { value: 'draft', label: 'Draft', desc: 'Private while you build.' },
                { value: 'active', label: 'Published', desc: 'Open and visible to members.' },
              ] as const).map((opt) => (
                <label
                  key={opt.value}
                  className="flex cursor-pointer items-start gap-3 rounded-xl border p-4 transition-all"
                  style={{
                    borderColor: status === opt.value ? 'rgba(56,160,158,0.40)' : '#e2e8f0',
                    background: status === opt.value ? 'rgba(56,160,158,0.06)' : 'transparent',
                  }}
                >
                  <input
                    type="radio"
                    name="status"
                    value={opt.value}
                    checked={status === opt.value}
                    onChange={() => setStatus(opt.value)}
                    className="mt-0.5 accent-teal-500"
                  />
                  <div>
                    <p className="text-[14px] font-medium text-navy-900">{opt.label}</p>
                    <p className="mt-0.5 text-[13px] text-slate-500">{opt.desc}</p>
                  </div>
                </label>
              ))}
            </div>
          </div>

          {/* Access type */}
          <div>
            <p className="mb-2.5 text-[14px] font-semibold text-navy-900">Access</p>
            <div className="grid gap-2 sm:grid-cols-2">
              {([
                { value: false, label: 'Private', desc: 'Invite only.' },
                { value: true, label: 'Public', desc: 'Anyone can find and join.' },
              ] as const).map((opt) => (
                <label
                  key={String(opt.value)}
                  className="flex cursor-pointer items-start gap-3 rounded-xl border p-4 transition-all"
                  style={{
                    borderColor: isPublic === opt.value ? 'rgba(56,160,158,0.40)' : '#e2e8f0',
                    background: isPublic === opt.value ? 'rgba(56,160,158,0.06)' : 'transparent',
                  }}
                >
                  <input
                    type="radio"
                    name="access"
                    checked={isPublic === opt.value}
                    onChange={() => setIsPublic(opt.value)}
                    className="mt-0.5 accent-teal-500"
                  />
                  <div>
                    <p className="text-[14px] font-medium text-navy-900">{opt.label}</p>
                    <p className="mt-0.5 text-[13px] text-slate-500">{opt.desc}</p>
                  </div>
                </label>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* ── Creator profile ── */}
      <div className="rounded-2xl border border-border bg-white p-6">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="mb-1 text-[17px] font-semibold text-navy-900">Creator profile</h2>
            <p className="text-[14px] text-slate-500">
              Your public profile is visible to members. Keep it current.
            </p>
          </div>
          <a
            href="/settings/profile"
            className="shrink-0 text-[13px] font-medium text-teal-600 transition-colors hover:text-teal-700"
          >
            Edit profile →
          </a>
        </div>
      </div>

      {/* Error */}
      {error && (
        <div
          className="rounded-xl px-4 py-3 text-[13px]"
          style={{
            background: 'rgba(239,68,68,0.06)',
            color: '#dc2626',
            border: '1px solid rgba(239,68,68,0.18)',
          }}
        >
          {error}
        </div>
      )}

      {/* Save */}
      <div className="flex items-center gap-5">
        <button
          type="submit"
          disabled={saving}
          className="inline-flex items-center rounded-xl px-7 py-2.5 text-[15px] font-semibold text-white transition-all hover:-translate-y-px hover:opacity-90 disabled:translate-y-0 disabled:opacity-60"
          style={{
            background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)',
            boxShadow: '0 3px 18px rgba(56,160,158,0.32)',
          }}
        >
          {saving ? 'Saving…' : 'Save changes'}
        </button>
        {saved && !error && (
          <p className="text-[13px] font-medium" style={{ color: '#38A09E' }}>
            Saved.
          </p>
        )}
      </div>

    </form>
  )
}
