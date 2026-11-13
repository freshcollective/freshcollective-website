'use client'

import Link from 'next/link'
import { useRef, useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { apiUrl, resolveMediaUrl } from '@/lib/api'
import {
  type HeaderImagePreference,
  normalisePreference,
} from '@/lib/collectiveHeaderImage'
import { COLLECTIVE_THEMES } from '@/lib/themes'
import type { CreatorSpaceDetail, PricingType } from '@/types/platform'
import AboutRichTextEditor from '@/components/ui/AboutRichTextEditor'

const ALLOWED_IMAGE_TYPES = ['image/jpeg', 'image/png']
const ALLOWED_IMAGE_EXTS = ['.jpg', '.jpeg', '.png']

/** The limit the copy beside the picker states. */
const MAX_IMAGE_BYTES = 10 * 1024 * 1024

export type CollectiveSettingsTab = 'details' | 'visibility' | 'pricing' | 'about'

interface Props {
  space: CreatorSpaceDetail
  /** Which grouping of fields to render. */
  tab?: CollectiveSettingsTab
  /** Whether the resolved creator plan unlocks paid offers. When false
   *  (Community), the paid pricing types are shown but unselectable
   *  with an upgrade affordance, rather than inviting the creator to
   *  configure pricing the backend will refuse on Save. */
  paidOffersEnabled?: boolean
}

export default function CollectiveSettingsForm({ space, tab = 'details', paidOffersEnabled = false }: Props) {
  const router = useRouter()
  const fileInputRef = useRef<HTMLInputElement>(null)

  // Auto-managed collectives (World Builders) have their access and
  // pricing controlled by Fresh Collective. The corresponding sections
  // are hidden from the form entirely and stripped from the PATCH body —
  // the API still refuses any change to protected fields as a safety net.
  const isAutoManaged = !!space.auto_grant_role

  // Text fields
  const [name, setName] = useState(space.name)
  const [slug, setSlug] = useState(space.slug)
  const [slugOrigin, setSlugOrigin] = useState('')
  const [tagline, setTagline] = useState(space.tagline ?? '')
  const [description, setDescription] = useState(space.description ?? '')
  const [aboutContent, setAboutContent] = useState(space.about_content ?? '')
  const [isPublic, setIsPublic] = useState(space.is_public)
  const [status, setStatus] = useState(space.status)
  const [themes, setThemes] = useState<string[]>(space.themes ?? [])

  // Pricing
  const [pricingType, setPricingType] = useState<PricingType>(space.pricing_type ?? 'free')
  const [pricingAmountDisplay, setPricingAmountDisplay] = useState<string>(
    space.pricing_amount_cents ? String(Math.round(space.pricing_amount_cents / 100)) : ''
  )
  const [pricingNote, setPricingNote] = useState(space.pricing_note ?? '')
  const [hasPaidInternalContent, setHasPaidInternalContent] = useState(space.has_paid_internal_content ?? false)
  const [includedAccessSummary, setIncludedAccessSummary] = useState(space.included_access_summary ?? '')
  const [paidContentSummary, setPaidContentSummary] = useState(space.paid_content_summary ?? '')
  const derivedHasPaidContent = space.derived_has_paid_internal_content ?? false

  useEffect(() => {
    setSlugOrigin(window.location.origin)
  }, [])

  // Banner
  const [bannerFile, setBannerFile] = useState<File | null>(null)
  const [bannerPreview, setBannerPreview] = useState<string | null>(null)
  const [existingBanner, setExistingBanner] = useState<string | null>(space.cover_image_url)
  // The creator's choice. Absent reads as 'location', which is what
  // every Collective showed before the choice existed.
  const [headerPreference, setHeaderPreference] = useState<HeaderImagePreference>(
    normalisePreference(space.header_image_preference),
  )
  const [preferenceSaving, setPreferenceSaving] = useState(false)
  const [preferenceError, setPreferenceError] = useState<string | null>(null)
  // Read for the side-by-side preview only. Never written — World
  // Artwork and the Atlas Location assignment are not touched here.
  const locationArtwork = resolveMediaUrl(
    space.location?.hero_artwork_url
      ?? space.location?.thumbnail_artwork_url
      ?? undefined,
  ) ?? null
  const [bannerError, setBannerError] = useState<string | null>(null)
  const [bannerUploading, setBannerUploading] = useState(false)
  const [bannerSaved, setBannerSaved] = useState(false)

  // Optional Collective Logo — the "hosted by" mark. Kept subtle and
  // deliberately smaller than the banner controls so no one mistakes it
  // for the primary visual identity.
  const logoInputRef = useRef<HTMLInputElement>(null)
  const [existingLogo, setExistingLogo] = useState<string | null>(space.logo_url ?? null)
  const [logoUploading, setLogoUploading] = useState(false)
  const [logoError, setLogoError] = useState<string | null>(null)
  const [logoSaved, setLogoSaved] = useState(false)

  // Form state
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)

  /**
 * The Pricing tab's options, and which require a commercial plan.
 *
 * "commercial" mirrors the backend guard exactly:
 * ``plan_guards.guard_paid_offers_enabled`` early-returns only for
 * ``pricing_type == 'free'`` and otherwise requires
 * ``paid_offers_enabled``. So every value except ``free`` — including
 * ``invite_only`` and ``coming_soon`` — is refused on Community today.
 * This table is deliberately that same shape rather than a prettier
 * guess, so the UI never offers something Save would reject.
 */
const PRICING_TYPE_OPTIONS: {
  value: string
  label: string
  commercial: boolean
  retired?: boolean
}[] = [
  { value: 'free',          label: 'Free',                 commercial: false },
  { value: 'paid_one_time', label: 'Paid — one time',      commercial: true },
  { value: 'paid_monthly',  label: 'Paid — monthly',       commercial: true },
  { value: 'paid_annual',   label: 'Paid — annual',        commercial: true },
  { value: 'invite_only',   label: 'Invite only',          commercial: true },
  // Stage 5A.0 — retired. It advertised "paid, eventually" while there
  // was no way to charge for membership; Stage 5A builds that, so the
  // holding state has nothing left to say. Kept in this list rather
  // than deleted so a Collective that still holds the value renders
  // its own state truthfully — see `retired` below.
  { value: 'coming_soon',   label: 'Paid — coming soon',   commercial: true, retired: true },
]

function isPaidType(type: PricingType): boolean {
    return type === 'paid_one_time' || type === 'paid_monthly' || type === 'paid_annual'
  }

  /**
   * Choosing a banner uploads it, the way choosing a logo does.
   *
   * It used to only stage the file: the creator pressed "Choose
   * image", saw a preview of their own local file, and then had to
   * find a second "Upload banner" button. Pressing the form's Save
   * button instead — the obvious thing, at the foot of the page —
   * saved every other setting and reported success while the banner
   * had never been sent. The preview kept showing their image, so
   * nothing looked wrong until they refreshed. That is the difference
   * between this and the logo, which has always uploaded on select.
   */
  function handleFileSelect(e: React.ChangeEvent<HTMLInputElement>) {
    setBannerError(null)
    setBannerSaved(false)
    const file = e.target.files?.[0]
    if (!file) return

    // Type by MIME *or* by name. Some browsers and operating systems
    // hand over an empty ``type`` for a perfectly good JPG, and a
    // MIME-only check rejected it — the logo has always accepted
    // either.
    const okType = ALLOWED_IMAGE_TYPES.includes(file.type)
      || /\.(jpe?g|png)$/i.test(file.name)
    if (!okType) {
      setBannerError('Please select a JPG or PNG image.')
      return
    }
    // The limit the copy states. It was never enforced, so an
    // oversized file travelled all the way to the server to fail.
    if (file.size > MAX_IMAGE_BYTES) {
      setBannerError('That image is larger than 10 MB. Please choose a smaller one.')
      return
    }

    setBannerFile(file)
    const preview = URL.createObjectURL(file)
    setBannerPreview(preview)
    void uploadBanner(file)
  }

  async function uploadBanner(file?: File) {
    const chosen = file ?? bannerFile
    if (!chosen || bannerUploading) return
    setBannerUploading(true)
    setBannerError(null)
    try {
      const formData = new FormData()
      formData.append('file', chosen)
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
      // The server selects the banner on upload — a creator who has
      // just chosen an image wants to see it. Read back rather than
      // assumed, so the two cannot disagree.
      setHeaderPreference(normalisePreference(data.header_image_preference))
      setBannerFile(null)
      setBannerPreview(null)
      setBannerSaved(true)
      if (fileInputRef.current) fileInputRef.current.value = ''
      // The header above this form, and every other server-rendered
      // surface showing the Collective, holds the old value in the
      // router cache. Without this the new image appears only after a
      // manual reload, which reads as "it did not save".
      router.refresh()
    } catch (err) {
      setBannerError(err instanceof Error ? err.message : 'Upload failed. Please try again.')
    } finally {
      setBannerUploading(false)
    }
  }

  /**
   * Switch between the two image sources, without re-uploading.
   *
   * The banner file stays stored whichever is selected, so a creator
   * can go back and forth — and a Collective that chose Location
   * artwork has not thrown its banner away.
   */
  async function selectPreference(next: HeaderImagePreference) {
    if (next === headerPreference || preferenceSaving) return
    setPreferenceError(null)
    setPreferenceSaving(true)
    const previous = headerPreference
    setHeaderPreference(next)
    try {
      const res = await fetch(apiUrl(`/api/creator/spaces/${space.slug}`), {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ header_image_preference: next }),
      })
      if (!res.ok) {
        const b = await res.json().catch(() => ({}))
        setHeaderPreference(previous)
        setPreferenceError(
          typeof b.detail === 'string' ? b.detail : `Could not save (${res.status})`,
        )
        return
      }
      router.refresh()
    } catch {
      setHeaderPreference(previous)
      setPreferenceError('Could not save that choice. Please try again.')
    } finally {
      setPreferenceSaving(false)
    }
  }

  /**
   * Remove the uploaded banner.
   *
   * The server clears the file and returns the Collective to its
   * Location artwork — there is nothing else left to show, so leaving
   * the preference pointing at a banner that no longer exists would be
   * a stored contradiction. The Location itself, and the logo, are
   * untouched.
   */
  async function removeBanner() {
    if (!existingBanner || bannerUploading) return
    setBannerError(null)
    setBannerSaved(false)
    setBannerUploading(true)
    try {
      const res = await fetch(apiUrl(`/api/creator/spaces/${space.slug}/cover`), {
        method: 'DELETE',
        credentials: 'include',
      })
      if (!res.ok) {
        const b = await res.json().catch(() => ({}))
        throw new Error(
          typeof b.detail === 'string' ? b.detail : `Remove failed (${res.status})`,
        )
      }
      const data = await res.json()
      setExistingBanner(data.cover_image_url ?? null)
      setHeaderPreference(normalisePreference(data.header_image_preference))
      setBannerPreview(null)
      setBannerFile(null)
      if (fileInputRef.current) fileInputRef.current.value = ''
      router.refresh()
    } catch (err) {
      setBannerError(
        err instanceof Error ? err.message : 'Remove failed. Please try again.',
      )
    } finally {
      setBannerUploading(false)
    }
  }

  async function uploadLogo(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    setLogoError(null)
    setLogoSaved(false)
    const okType = /^image\/(jpeg|png|webp)$/i.test(file.type)
      || /\.(jpe?g|png|webp)$/i.test(file.name)
    if (!okType) {
      setLogoError('Please select a JPG, PNG, or WebP image.')
      return
    }
    setLogoUploading(true)
    try {
      const formData = new FormData()
      formData.append('file', file)
      const res = await fetch(apiUrl(`/api/creator/spaces/${space.slug}/logo`), {
        method: 'POST',
        credentials: 'include',
        body: formData,
      })
      if (!res.ok) {
        const b = await res.json().catch(() => ({}))
        throw new Error(typeof b.detail === 'string' ? b.detail : `Upload failed (${res.status})`)
      }
      const data = await res.json()
      setExistingLogo(data.logo_url ?? null)
      setLogoSaved(true)
      router.refresh()
    } catch (err) {
      setLogoError(err instanceof Error ? err.message : 'Upload failed. Please try again.')
    } finally {
      setLogoUploading(false)
      if (logoInputRef.current) logoInputRef.current.value = ''
    }
  }

  async function removeLogo() {
    if (!existingLogo) return
    setLogoError(null)
    setLogoSaved(false)
    setLogoUploading(true)
    try {
      const res = await fetch(apiUrl(`/api/creator/spaces/${space.slug}/logo`), {
        method: 'DELETE',
        credentials: 'include',
      })
      if (!res.ok) throw new Error(`Remove failed (${res.status})`)
      const data = await res.json()
      setExistingLogo(data.logo_url ?? null)
      setLogoSaved(true)
    } catch (err) {
      setLogoError(err instanceof Error ? err.message : 'Remove failed. Please try again.')
    } finally {
      setLogoUploading(false)
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
          about_content: aboutContent.trim() || null,
          themes,
          // Access + pricing fields are only sent for creator-managed
          // collectives. For auto-managed collectives (World Builders),
          // Fresh Collective owns these values and the backend refuses
          // to change them.
          ...(isAutoManaged
            ? {}
            : {
                is_public: isPublic,
                status,
                pricing_type: pricingType,
                pricing_amount_cents: isPaidType(pricingType) && pricingAmountDisplay
                  ? Math.round(parseFloat(pricingAmountDisplay) * 100) || null
                  : null,
                pricing_currency: 'AUD',
                pricing_note: pricingNote.trim() || null,
                has_paid_internal_content: hasPaidInternalContent,
                included_access_summary: includedAccessSummary.trim() || null,
                paid_content_summary: paidContentSummary.trim() || null,
              }),
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
        // Refresh to invalidate the router cache so the layout picks
        // up the new active-collective cookie server-side.
        router.refresh()
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

  // Tab visibility — Details/Visibility/Pricing/About share this single
  // form so in-flight field state survives tab switches. Each section
  // below is wrapped in a `showXxx` conditional. The Save button saves
  // everything regardless of tab, matching the existing single-submit
  // behaviour. Banner + Logo live on Details (direct identity assets);
  // the Creator profile section has been removed and now lives under
  // the creator-level /creator-studio/account page.
  const showIdentity   = tab === 'details' // (name/URL/tagline/description/timezone/themes)
  const showAbout      = tab === 'about'
  const showArtwork    = tab === 'details' // Banner + Logo now sit on Details
  const showVisibility = tab === 'visibility'
  const showPricing    = tab === 'pricing'

  return (
    <form onSubmit={handleSubmit} className="space-y-5">

      {/* ── Collective identity ── */}
      {showIdentity && (
      <div className="rounded-2xl border border-border bg-white p-6">
        <h2 className="mb-1 text-[17px] font-semibold text-navy-900">Collective identity</h2>
        <p className="mb-5 text-[14px] text-black">
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
                className="flex shrink-0 items-center border-r border-slate-200 bg-slate-100 px-3 py-2.5 text-[13px] text-black select-none"
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
            <p className="mt-1.5 text-[12px] text-black">
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
              Short description
            </label>
            <textarea
              id="s-desc"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={3}
              maxLength={500}
              placeholder="A short summary shown on cards, explore pages, and previews."
              className="w-full resize-none rounded-xl border border-slate-200 bg-slate-50/70 px-4 py-2.5 text-[14px] text-navy-900 placeholder:text-slate-400 transition-colors focus:border-teal-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-teal-400/20"
            />
            <p className="mt-1.5 text-[12px] text-black">
              Shown on cards and explore pages — keep it to 1–2 sentences.
            </p>
          </div>

          {/* Timezone lives on OperatingDetailsForm ("Where does this
              Collective operate?") — a coherent grouping of the
              practical operational settings. */}

          {/* ── Themes ── */}
          <div>
            <p id="themes-label" className="mb-1.5 text-[14px] font-semibold text-navy-900">Themes</p>
            <p className="mb-3 text-[13px] text-black">
              Choose the themes your collective explores. These help members discover your community and contribute to the living identity of the places where it grows.
            </p>
            <div
              role="group"
              aria-labelledby="themes-label"
              className="flex flex-wrap gap-2"
            >
              {COLLECTIVE_THEMES.map((theme) => {
                const selected = themes.includes(theme)
                return (
                  <button
                    key={theme}
                    type="button"
                    aria-pressed={selected}
                    onClick={() =>
                      setThemes((prev) =>
                        selected ? prev.filter((t) => t !== theme) : [...prev, theme],
                      )
                    }
                    className={
                      'rounded-lg border px-3.5 py-1.5 text-[13px] transition-colors ' +
                      'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#38A09E]/40 focus-visible:ring-offset-2 ' +
                      (selected
                        ? 'border-[#38A09E]/60 bg-[#38A09E]/10 text-[#1E6E6C] font-semibold hover:bg-[#38A09E]/15'
                        : 'border-slate-200 text-slate-500 font-medium hover:border-slate-300 hover:bg-slate-50 hover:text-navy-900')
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
      )}

      {/* ── About page ── (About tab) */}
      {showAbout && (
      <div className="rounded-2xl border border-border bg-white p-6">
        <h2 className="mb-1 text-[17px] font-semibold text-navy-900">About page</h2>
        <p className="mb-5 text-[14px] text-black">
          Full rich content shown on your public About page. Use headings, bold text, bullets, and links.
        </p>
        <AboutRichTextEditor
          id="s-about"
          value={aboutContent}
          onChange={setAboutContent}
        />
      </div>
      )}

      {/* ── Banner image + Collective logo ── (Artwork tab) */}
      {showArtwork && (
      <>
      <div className="rounded-2xl border border-border bg-white p-6">
        <h2 className="mb-1 text-[17px] font-semibold text-navy-900">
          Collective header image
        </h2>
        <p className="mb-5 text-[14px] text-black">
          Choose the image that welcomes people into your Collective.
        </p>

        {/* Two sources, one choice.
            A Collective has two visual identities — the creator's own
            brand and its home in the Fresh Collective world — and they
            are not rivals. Both previews are shown together so the
            creator can compare them before deciding, which is what the
            old "Banner uploaded." line could not do: it reported a
            file existed and never showed it. */}
        <div
          className="grid gap-4 sm:grid-cols-2"
          role="radiogroup"
          aria-label="Collective header image"
        >
          <HeaderImageOption
            selected={headerPreference === 'location'}
            disabled={!locationArtwork}
            busy={preferenceSaving}
            title="Use my Location artwork"
            body="Display the beautiful imagery from your chosen Fresh Collective location."
            imageUrl={locationArtwork}
            emptyLabel="No Location artwork yet"
            onSelect={() => selectPreference('location')}
          />
          <HeaderImageOption
            selected={headerPreference === 'banner'}
            disabled={!existingBanner && !bannerPreview}
            busy={preferenceSaving}
            title="Use my own banner"
            body="Upload an image that reflects your Collective's unique identity."
            imageUrl={bannerPreview ?? existingBanner}
            emptyLabel="No banner uploaded yet"
            onSelect={() => selectPreference('banner')}
          />
        </div>

        {preferenceError && (
          <p className="mt-3 text-[13px]" style={{ color: '#dc2626' }} role="alert">
            {preferenceError}
          </p>
        )}

        {/* Banner actions. Upload when there is none, Replace and
            Remove when there is — the three the brief asks for, and
            nothing in between to press by mistake. */}
        <div
          className="mt-4 flex flex-col gap-3 rounded-xl border-2 border-dashed px-5 py-5 transition-colors"
          style={{ borderColor: 'rgba(56,160,158,0.25)' }}
        >
          <div className="flex flex-wrap items-center gap-3">
            <label
              htmlFor="banner-upload"
              className="cursor-pointer rounded-xl border border-border bg-white px-4 py-2 text-[13px] font-medium text-black transition-colors hover:border-teal-200 hover:text-teal-700"
            >
              {existingBanner ? 'Replace image' : 'Upload banner'}
            </label>
            <input
              id="banner-upload"
              ref={fileInputRef}
              type="file"
              accept={ALLOWED_IMAGE_EXTS.join(',')}
              onChange={handleFileSelect}
              className="sr-only"
            />
            {existingBanner && !bannerUploading && (
              <button
                type="button"
                onClick={removeBanner}
                className="rounded-xl px-4 py-2 text-[13px] font-medium text-black transition-colors hover:text-red-600"
              >
                Remove banner
              </button>
            )}
            {bannerUploading && (
              <span className="text-[13px] font-medium text-teal-700">
                Uploading&hellip;
              </span>
            )}
            {/* A retry, not the upload step. Choosing an image uploads
                it; this appears only when that failed. */}
            {bannerFile && bannerError && !bannerUploading && (
              <button
                type="button"
                onClick={() => { void uploadBanner() }}
                className="rounded-xl px-4 py-2 text-[13px] font-semibold text-white transition-opacity hover:opacity-90"
                style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
              >
                Try again
              </button>
            )}
          </div>
          <p className="text-[12px] text-black">
            Recommended: wide image, JPG or PNG. Max 10 MB.
          </p>
        </div>

        {bannerError && (
          <p className="mt-2 text-[13px]" style={{ color: '#dc2626' }} role="alert">
            {bannerError}
          </p>
        )}
        {bannerSaved && !bannerError && (
          <p className="mt-2 text-[13px]" style={{ color: '#38A09E' }}>
            Banner saved successfully.
          </p>
        )}
      </div>

      {/* ── Collective logo (optional) ─────────────────────────────────
          A subtle "hosted by" mark shown beside the collective name in
          the header. The Location artwork is the primary visual identity
          — this is intentionally small and easy to leave blank. */}
      <div className="rounded-2xl border border-border bg-white p-6">
        <h2 className="mb-1 text-[17px] font-semibold text-navy-900">Collective logo</h2>
        <p className="mb-5 text-[14px] text-black">
          Optional. A small mark shown beside your collective name — think &ldquo;hosted by&rdquo;. The Location artwork remains your collective&apos;s primary visual identity.
        </p>

        <div className="flex flex-wrap items-center gap-4">
          <div
            className="flex h-16 w-16 shrink-0 items-center justify-center overflow-hidden rounded-xl"
            style={{ background: 'rgba(12,24,38,0.04)', border: '1px solid rgba(12,24,38,0.08)' }}
          >
            {existingLogo ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={existingLogo}
                alt="Collective logo"
                className="h-full w-full object-contain"
              />
            ) : (
              <span className="text-[11px] italic" style={{ color: 'rgba(12,24,38,0.45)' }}>
                None
              </span>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <label
              htmlFor="logo-upload"
              className="cursor-pointer rounded-xl border border-border bg-white px-4 py-2 text-[13px] font-medium text-black transition-colors hover:border-teal-200 hover:text-teal-700"
            >
              {logoUploading ? 'Uploading…' : existingLogo ? 'Replace logo' : 'Upload logo'}
            </label>
            <input
              id="logo-upload"
              ref={logoInputRef}
              type="file"
              accept="image/jpeg,image/png,image/webp"
              onChange={uploadLogo}
              disabled={logoUploading}
              className="sr-only"
            />
            {existingLogo && (
              <button
                type="button"
                onClick={removeLogo}
                disabled={logoUploading}
                className="rounded-xl border border-slate-200 bg-white px-4 py-2 text-[13px] font-medium text-black transition-colors hover:border-slate-300 disabled:opacity-60"
              >
                Remove
              </button>
            )}
          </div>
        </div>

        <p className="mt-3 text-[12px] text-black">
          Recommended: a small square image on a transparent background. JPG, PNG, or WebP.
        </p>
        {logoError && (
          <p className="mt-2 text-[13px]" style={{ color: '#dc2626' }}>{logoError}</p>
        )}
        {logoSaved && !logoError && (
          <p className="mt-2 text-[13px]" style={{ color: '#38A09E' }}>
            Logo saved.
          </p>
        )}
      </div>
      </>
      )}

      {/* ── Visibility and access ── (Visibility tab; hidden for auto-managed collectives) */}
      {showVisibility && !isAutoManaged && (
      <div className="rounded-2xl border border-border bg-white p-6">
        <h2 className="mb-1 text-[17px] font-semibold text-navy-900">Visibility and access</h2>
        <p className="mb-5 text-[14px] text-black">
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
                    <p className="mt-0.5 text-[13px] text-black">{opt.desc}</p>
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
                    <p className="mt-0.5 text-[13px] text-black">{opt.desc}</p>
                  </div>
                </label>
              ))}
            </div>
          </div>
        </div>
      </div>

      )}

      {/* ── Public pricing ── (Pricing tab; hidden for auto-managed collectives) */}
      {showPricing && !isAutoManaged && (
      <div className="rounded-2xl border border-border bg-white p-6">
        <h2 className="mb-1 text-[17px] font-semibold text-navy-900">Public pricing</h2>
        <p className="mb-5 text-[14px] text-black">
          Shown publicly so people understand the cost before joining. Payment processing will be connected separately.
        </p>

        <div className="space-y-4">
          {/* Pricing type */}
          <div>
            <label htmlFor="pricing-type" className="mb-1.5 block text-[14px] font-semibold text-navy-900">
              Pricing type
            </label>
            <select
              id="pricing-type"
              value={pricingType}
              onChange={(e) => setPricingType(e.target.value as PricingType)}
              className="w-full rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 text-[14px] text-navy-900 shadow-sm outline-none transition-colors focus:border-teal-400"
            >
              {PRICING_TYPE_OPTIONS
                // Stage 5A.0 — a retired type is hidden unless this
                // Collective actually holds it. Dropping it outright
                // would leave such a Collective's select with no
                // matching option, so the browser would show the first
                // one — Free — and the next save would silently convert
                // a paid-intent Collective to free. Shown and disabled
                // is the honest state: here is what you have, choose
                // something else to change it.
                .filter(({ value, retired }) => !retired || value === space.pricing_type)
                .map(({ value, label, commercial, retired }) => (
                <option
                  key={value}
                  value={value}
                  // Keep the currently-saved value selectable even when
                  // the plan no longer permits it — otherwise a
                  // Collective that holds a paid type from an earlier
                  // plan would render a select that misreports its own
                  // state, with no way to move back to Free.
                  disabled={
                    retired
                    || (commercial && !paidOffersEnabled && value !== space.pricing_type)
                  }
                >
                  {label}
                </option>
              ))}
            </select>
            {space.pricing_type === 'coming_soon' && (
              <p className="mt-2 text-[12.5px] leading-relaxed" style={{ color: 'rgba(12,24,38,0.62)' }}>
                &ldquo;Paid — coming soon&rdquo; is no longer offered. Your
                Collective keeps it until you choose something else — paid
                membership is being built now.
              </p>
            )}
            {!paidOffersEnabled && (
              <p className="mt-2 text-[12.5px] leading-relaxed" style={{ color: 'rgba(12,24,38,0.62)' }}>
                Paid pricing is available on Creator plans.{' '}
                <Link href="/creator-studio/billing" className="font-semibold text-teal-700 hover:underline">
                  Upgrade →
                </Link>
              </p>
            )}
          </div>

          {/* Amount — only shown for paid types */}
          {isPaidType(pricingType) && (
            <div>
              <label htmlFor="pricing-amount" className="mb-1.5 block text-[14px] font-semibold text-navy-900">
                Amount (AUD)
              </label>
              <div className="flex items-center gap-2">
                <span className="text-[15px] text-black">$</span>
                <input
                  id="pricing-amount"
                  type="number"
                  min="0"
                  step="1"
                  placeholder="e.g. 49"
                  value={pricingAmountDisplay}
                  onChange={(e) => setPricingAmountDisplay(e.target.value)}
                  className="w-36 rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 text-[14px] text-navy-900 shadow-sm outline-none transition-colors focus:border-teal-400"
                />
                <span className="text-[14px] text-black">
                  AUD{pricingType === 'paid_monthly' ? ' / month' : pricingType === 'paid_annual' ? ' / year' : ''}
                </span>
              </div>
            </div>
          )}

          {/* Optional note */}
          <div>
            <label htmlFor="pricing-note" className="mb-1.5 block text-[14px] font-semibold text-navy-900">
              Pricing note <span className="font-normal text-black">(optional)</span>
            </label>
            <input
              id="pricing-note"
              type="text"
              value={pricingNote}
              onChange={(e) => setPricingNote(e.target.value)}
              maxLength={300}
              placeholder="e.g. Founding member rate — limited spots"
              className="w-full rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 text-[14px] text-navy-900 placeholder-slate-400 shadow-sm outline-none transition-colors focus:border-teal-400"
            />
          </div>

          {/* Paid internal content toggle */}
          <div>
            <div
              className="flex cursor-pointer items-start gap-4 rounded-xl border p-4 transition-all"
              style={{
                borderColor: (hasPaidInternalContent || derivedHasPaidContent) ? 'rgba(56,160,158,0.40)' : '#e2e8f0',
                background: (hasPaidInternalContent || derivedHasPaidContent) ? 'rgba(56,160,158,0.06)' : 'transparent',
              }}
              onClick={() => setHasPaidInternalContent((v) => !v)}
            >
              <input
                type="checkbox"
                id="has-paid-internal"
                checked={hasPaidInternalContent}
                onChange={(e) => setHasPaidInternalContent(e.target.checked)}
                onClick={(e) => e.stopPropagation()}
                className="mt-0.5 h-4 w-4 accent-teal-500"
              />
              <div>
                <label htmlFor="has-paid-internal" className="cursor-pointer text-[14px] font-medium text-navy-900">
                  Contains paid content inside this collective
                </label>
                <p className="mt-0.5 text-[13px] text-black">
                  Turn this on if some pathways, gatherings, or resources require separate payment after someone joins.
                  This is also detected automatically when you publish a paid pathway.
                </p>
              </div>
            </div>
            {derivedHasPaidContent && (
              <div
                className="mt-2 flex items-center gap-2 rounded-xl px-4 py-2.5"
                style={{ background: 'rgba(56,160,158,0.08)', border: '1px solid rgba(56,160,158,0.20)' }}
              >
                <div className="h-2 w-2 rounded-full" style={{ background: '#38A09E' }} />
                <p className="text-[13px]" style={{ color: '#1E6E6C' }}>
                  Paid content detected from your published pathways.
                </p>
              </div>
            )}
          </div>

          {/* What's included / paid separately — shown when manual toggle or auto-detected */}
          {(hasPaidInternalContent || derivedHasPaidContent) && (
            <>
              <div>
                <label htmlFor="included-summary" className="mb-1.5 block text-[14px] font-semibold text-navy-900">
                  What&apos;s included?
                </label>
                <input
                  id="included-summary"
                  type="text"
                  value={includedAccessSummary}
                  onChange={(e) => setIncludedAccessSummary(e.target.value)}
                  maxLength={300}
                  placeholder="Conversations, gatherings, and member updates"
                  className="w-full rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 text-[14px] text-navy-900 placeholder-slate-400 shadow-sm outline-none transition-colors focus:border-teal-400"
                />
              </div>

              <div>
                <label htmlFor="paid-summary" className="mb-1.5 block text-[14px] font-semibold text-navy-900">
                  Paid separately
                </label>
                <input
                  id="paid-summary"
                  type="text"
                  value={paidContentSummary}
                  onChange={(e) => setPaidContentSummary(e.target.value)}
                  maxLength={300}
                  placeholder="Paid pathways available separately"
                  className="w-full rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 text-[14px] text-navy-900 placeholder-slate-400 shadow-sm outline-none transition-colors focus:border-teal-400"
                />
                <p className="mt-1.5 text-[12px] text-black">
                  Explain what people access for free and what may require separate payment.
                </p>
              </div>
            </>
          )}
        </div>
      </div>
      )}

      {/* Creator profile has moved to the creator-level Account area
          (/creator-studio/account) — it belongs to the creator across
          all their collectives, not to any single collective. */}

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

// ---------------------------------------------------------------------------
// Header image option
// ---------------------------------------------------------------------------

/**
 * One of the two header-image sources, with its image shown.
 *
 * A wide 16:5 plate, matching the Collective header's own proportions,
 * so what a creator sees here is what members will see. The previous
 * experience said only "Banner uploaded." — a sentence about a file,
 * which could not answer the question a creator was actually asking.
 *
 * A radio rather than a button pair: these are two values of one
 * setting, and a screen reader should hear them that way.
 */
function HeaderImageOption({
  selected, disabled, busy, title, body, imageUrl, emptyLabel, onSelect,
}: {
  selected: boolean
  disabled?: boolean
  busy?: boolean
  title: string
  body: string
  imageUrl: string | null
  emptyLabel: string
  onSelect: () => void
}) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      aria-label={title}
      disabled={disabled || busy}
      onClick={onSelect}
      className={`group flex flex-col overflow-hidden rounded-xl border-2 text-left transition-all disabled:cursor-not-allowed disabled:opacity-60 ${
        selected
          ? 'border-teal-500 shadow-sm'
          : 'border-slate-200 hover:border-teal-300'
      }`}
    >
      {/* 16:5 — the Collective header's plate. */}
      <div className="relative w-full" style={{ aspectRatio: '16 / 5' }}>
        {imageUrl ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={imageUrl}
            alt=""
            // ``object-cover`` so a tall or narrow upload is cropped to
            // the header's shape rather than squashed into it.
            className="absolute inset-0 h-full w-full object-cover"
          />
        ) : (
          <div
            className="absolute inset-0 flex items-center justify-center"
            style={{
              background:
                'linear-gradient(135deg, rgba(56,160,158,0.14) 0%, rgba(85,184,182,0.08) 100%)',
            }}
          >
            <span className="text-[12px] font-medium" style={{ color: '#0f766e' }}>
              {emptyLabel}
            </span>
          </div>
        )}
        {selected && (
          <span
            className="absolute right-2 top-2 inline-flex items-center rounded-full px-2 py-0.5 text-[10.5px] font-semibold uppercase tracking-wider text-white"
            style={{ background: 'rgba(15,118,110,0.92)' }}
          >
            In use
          </span>
        )}
      </div>
      <div className="flex-1 px-4 py-3">
        <p className="text-[13.5px] font-semibold text-navy-900">{title}</p>
        <p className="mt-0.5 text-[12.5px] leading-relaxed text-black">{body}</p>
      </div>
    </button>
  )
}
