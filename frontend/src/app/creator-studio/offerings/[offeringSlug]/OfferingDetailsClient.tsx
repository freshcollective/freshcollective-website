'use client'

import React, { useCallback, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import { apiUrl, resolveMediaUrl } from '@/lib/api'
import { useAutosave } from '@/lib/useAutosave'
import type { CreatorOffering, OfferingCover } from '@/types/platform'

interface Props {
  spaceSlug: string
  offering: CreatorOffering
  covers: OfferingCover[]
}

interface DetailsPayload {
  title?: string
  summary?: string | null
}

/**
 * 🌸 Details — title, short description, cover.
 *
 * Autosaves through the shared ``useAutosave`` hook, the same one the
 * Pathway settings and Series editors use, so the debounce, the status
 * word and the flush-on-unmount behaviour are identical across Creator
 * Studio. A creator who types a title and immediately clicks the Files
 * tab does not lose it.
 */
export default function OfferingDetailsClient({
  spaceSlug, offering, covers,
}: Props) {
  const router = useRouter()
  const [title, setTitle] = useState(offering.title)
  const [summary, setSummary] = useState(offering.summary ?? '')
  // Three pieces of cover state, because there are three things to
  // know: what is shown, whether the creator uploaded it, and which
  // shared category is selected. Collapsing them would make "remove my
  // upload and fall back to the category" unexpressible.
  const [cover, setCover] = useState(offering.cover_image_url)
  const [customCover, setCustomCover] = useState(offering.custom_cover_url)
  const [categoryKey, setCategoryKey] = useState(offering.default_cover_key)
  const [saveError, setSaveError] = useState<string | null>(null)

  const base = apiUrl(`/api/creator/spaces/${spaceSlug}/offerings/${offering.slug}`)

  const save = useCallback(async (payload: DetailsPayload) => {
    const res = await fetch(base, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(payload),
    })
    if (!res.ok) {
      const body = await res.json().catch(() => ({}))
      throw new Error(
        typeof body.detail === 'string' ? body.detail : `Save failed (${res.status}).`,
      )
    }
    setSaveError(null)
  }, [base])

  const { status, schedule } = useAutosave<DetailsPayload>({
    save,
    // Surfaced rather than swallowed — a silent autosave failure is the
    // worst kind, because the creator keeps typing into nothing. (The
    // Creator Studio backlog has the same note for the other editors.)
    onError: (err) => setSaveError(
      err instanceof Error ? err.message : 'That change could not be saved.',
    ),
    onSaved: () => router.refresh(),
  })

  async function chooseCategory(key: string, previewUrl: string | null) {
    // Optimistic: the category is selected immediately and the preview
    // follows. A custom upload still wins, so the shown cover only
    // changes when there isn't one.
    setCategoryKey(key)
    if (!customCover) setCover(previewUrl)
    setSaveError(null)
    try {
      const res = await fetch(base, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        // The **key**, not a URL. The image is World Artwork's, and an
        // administrator replacing it updates this Offering with nothing
        // stored here to go stale.
        body: JSON.stringify({ default_cover_key: key }),
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        setSaveError(
          typeof body.detail === 'string'
            ? body.detail
            : "That cover couldn't be saved.",
        )
        setCover(offering.cover_image_url)
        return
      }
      router.refresh()
    } catch {
      setSaveError("That cover couldn't be saved.")
      setCover(offering.cover_image_url)
    }
  }

  return (
    <div className="max-w-[760px]">
      <div className="mb-6 flex items-baseline justify-between gap-4">
        <div>
          <h2 className="text-[18px] font-semibold text-navy-900">Details</h2>
          <p className="mt-1 text-[14px] text-black">
            What this Offering is called, and how it appears on a card.
          </p>
        </div>
        <SaveStatus status={status} />
      </div>

      {saveError && (
        <p className="mb-4 rounded-lg bg-red-50 px-3 py-2 text-[13px] text-red-700">
          {saveError}
        </p>
      )}

      {/* ── Title + summary ─────────────────────────────────────────── */}
      <div className="rounded-2xl border border-slate-200 bg-white p-6">
        <label htmlFor="offering-title" className="block text-[14px] font-semibold text-navy-900">
          Title
        </label>
        <input
          id="offering-title"
          value={title}
          maxLength={200}
          onChange={(e) => {
            setTitle(e.target.value)
            if (e.target.value.trim()) schedule({ title: e.target.value.trim() })
          }}
          className="mt-2 w-full rounded-xl border border-slate-200 px-4 py-2.5 text-[15px] text-navy-900 outline-none focus:border-teal-400"
        />

        <label
          htmlFor="offering-summary"
          className="mt-6 block text-[14px] font-semibold text-navy-900"
        >
          Short description
        </label>
        <p className="mt-1 text-[13px] text-black">
          One or two lines. This is what people read on cards and listings.
        </p>
        <textarea
          id="offering-summary"
          value={summary}
          rows={3}
          maxLength={2000}
          onChange={(e) => {
            setSummary(e.target.value)
            schedule({ summary: e.target.value.trim() || null })
          }}
          className="mt-2 w-full resize-y rounded-xl border border-slate-200 px-4 py-2.5 text-[15px] leading-relaxed text-navy-900 outline-none focus:border-teal-400"
        />
      </div>

      {/* ── Cover ───────────────────────────────────────────────────── */}
      <CoverPicker
        spaceSlug={spaceSlug}
        offeringSlug={offering.slug}
        covers={covers}
        shown={cover}
        customCover={customCover}
        categoryKey={categoryKey}
        onChoose={chooseCategory}
        onUploaded={(url) => {
          setCustomCover(url)
          setCover(url)
          router.refresh()
        }}
        onError={setSaveError}
      />
    </div>
  )
}

function SaveStatus({ status }: { status: string }) {
  const text =
    status === 'saving' ? 'Saving…'
    : status === 'saved' ? 'Saved'
    : status === 'dirty' ? 'Unsaved changes'
    : status === 'error' ? 'Not saved'
    : ''
  if (!text) return null
  return (
    <span
      className="shrink-0 text-[12.5px]"
      style={{ color: status === 'error' ? '#b91c1c' : 'rgba(12,24,38,0.5)' }}
      aria-live="polite"
    >
      {text}
    </span>
  )
}

/**
 * The cover selector.
 *
 * Five shared categories plus "upload your own".
 *
 * Choosing a category stores its **key**. The image it shows is managed
 * by an administrator in World Settings → World Artwork, so one object
 * serves every Offering in that category and replacing it reaches all
 * of them — nothing is copied into a creator's storage and nothing on
 * the Offering goes stale.
 *
 * A category whose artwork has not been uploaded yet is still
 * selectable, and says so. The choice is the creator's to make; whether
 * the shared image exists is an administrator's, and a creator must not
 * be blocked on something they cannot see or do.
 */
function CoverPicker({
  spaceSlug, offeringSlug, covers, shown, customCover, categoryKey,
  onChoose, onUploaded, onError,
}: {
  spaceSlug: string
  offeringSlug: string
  covers: OfferingCover[]
  /** The cover currently displayed, whatever its source. */
  shown: string | null
  /** The creator's own upload, if any — it wins over the category. */
  customCover: string | null
  /** The shared category selected, if any. */
  categoryKey: string | null
  onChoose: (key: string, previewUrl: string | null) => void
  onUploaded: (url: string) => void
  onError: (msg: string | null) => void
}) {
  const fileInput = useRef<HTMLInputElement | null>(null)
  const [uploading, setUploading] = useState(false)

  // Read from the field rather than inferred by comparing URLs, which
  // is how this used to work and could not survive the shared image
  // being replaced.
  const isCustom = Boolean(customCover)

  async function upload(file: File) {
    setUploading(true)
    onError(null)
    try {
      const form = new FormData()
      form.append('file', file)
      const res = await fetch(
        apiUrl(`/api/creator/spaces/${spaceSlug}/offerings/${offeringSlug}/cover`),
        { method: 'POST', credentials: 'include', body: form },
      )
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        const detail = body?.detail
        onError(
          detail?.message ?? (typeof detail === 'string' ? detail : "That image couldn't be uploaded."),
        )
        return
      }
      const data = await res.json()
      onUploaded(data.cover_image_url)
    } catch {
      onError("That image couldn't be uploaded.")
    } finally {
      setUploading(false)
      if (fileInput.current) fileInput.current.value = ''
    }
  }

  return (
    <div className="mt-6 rounded-2xl border border-slate-200 bg-white p-6">
      <h3 className="text-[14px] font-semibold text-navy-900">Cover image</h3>
      <p className="mt-1 text-[13px] text-black">
        Choose one of ours, or upload your own.
      </p>

      <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3">
        {covers.map((c) => {
          const selected = categoryKey === c.key
          const preview = c.thumbnail_url ?? c.image_url
          return (
            <button
              key={c.key}
              type="button"
              onClick={() => onChoose(c.key, c.image_url)}
              aria-pressed={selected}
              className="group overflow-hidden rounded-xl text-left transition-shadow hover:shadow-md"
              style={{
                border: selected
                  ? '2px solid #38A09E'
                  : '1px solid rgba(12,24,38,0.10)',
                outline: 'none',
              }}
            >
              <div style={{ aspectRatio: '3 / 2', background: '#F4F7F6' }}>
                {preview ? (
                  /* eslint-disable-next-line @next/next/no-img-element */
                  <img
                    src={resolveMediaUrl(preview) ?? preview}
                    alt=""
                    loading="lazy"
                    className="h-full w-full object-cover"
                  />
                ) : (
                  /* No shared artwork uploaded yet. The same gradient an
                     Offering itself shows, so the picker previews the
                     real outcome rather than an empty box. */
                  <div
                    className="flex h-full w-full items-end p-2"
                    style={{ background: 'linear-gradient(135deg, rgba(56,160,158,0.16) 0%, rgba(85,184,182,0.08) 100%)' }}
                  >
                    <span
                      className="text-[10.5px] leading-tight"
                      style={{ color: 'rgba(12,24,38,0.52)' }}
                    >
                      No shared image yet
                    </span>
                  </div>
                )}
              </div>
              <div className="px-3 py-2">
                <p className="text-[12.5px] font-semibold text-navy-900">
                  {c.label}
                  {selected && (
                    <span className="ml-1 text-teal-700" aria-hidden="true">✓</span>
                  )}
                </p>
                <p className="mt-0.5 text-[11.5px] leading-snug" style={{ color: 'rgba(12,24,38,0.55)' }}>
                  {c.description}
                </p>
              </div>
              {selected && <span className="sr-only">Selected</span>}
            </button>
          )
        })}

        {/* Upload-your-own tile, in the same grid so the two routes to a
            cover sit side by side rather than one being an afterthought. */}
        <button
          type="button"
          onClick={() => fileInput.current?.click()}
          disabled={uploading}
          className="flex flex-col items-center justify-center rounded-xl border border-dashed p-4 text-center transition-colors hover:border-teal-300 disabled:opacity-50"
          style={{
            borderColor: isCustom ? '#38A09E' : 'rgba(12,24,38,0.18)',
            borderWidth: isCustom ? 2 : 1,
            minHeight: 140,
          }}
        >
          {isCustom && shown ? (
            <>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={resolveMediaUrl(shown) ?? shown}
                alt=""
                className="mb-2 h-16 w-full rounded object-cover"
              />
              <span className="text-[12.5px] font-semibold text-navy-900">
                Your image <span className="text-teal-700" aria-hidden="true">✓</span>
              </span>
              <span className="mt-0.5 text-[11.5px]" style={{ color: 'rgba(12,24,38,0.55)' }}>
                {uploading ? 'Uploading…' : 'Choose a different one'}
              </span>
            </>
          ) : (
            <>
              <span className="text-[13px] font-semibold text-navy-900">
                {uploading ? 'Uploading…' : 'Upload your own'}
              </span>
              <span className="mt-1 text-[11.5px] leading-snug" style={{ color: 'rgba(12,24,38,0.55)' }}>
                JPG, PNG or WebP, up to 5 MB
              </span>
            </>
          )}
        </button>
      </div>

      <input
        ref={fileInput}
        type="file"
        accept="image/jpeg,image/png,image/webp"
        className="hidden"
        onChange={(e) => {
          const f = e.target.files?.[0]
          if (f) void upload(f)
        }}
      />
    </div>
  )
}
