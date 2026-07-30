'use client'

import { useCallback, useRef, useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { apiUrl, resolveMediaUrl } from '@/lib/api'
import type {
  PhysicalLocationDetail,
  PhysicalLocationStatus,
} from '@/lib/physicalLocations/types'

interface Props {
  initialLocation: PhysicalLocationDetail
}

const STATUS_LABEL: Record<PhysicalLocationStatus, string> = {
  draft:    'Draft',
  active:   'Active',
  hidden:   'Hidden',
  archived: 'Archived',
}

/**
 * Editor for one Physical Location.
 *
 * Six sections:
 *
 *   1. Identity      — name, slug, region, country, status
 *   2. Blurb         — editorial copy for Discover Places
 *   3. Artwork       — upload + focal point + alt text
 *   4. Admin note    — internal only, never surfaced
 *   5. Usage         — Collectives that live here (read-only)
 *   6. Metadata      — coordinates / timezone / provider id
 *
 * Every mutation goes through the same PATCH endpoint, one section
 * at a time. Artwork upload / clear are separate endpoints. Creators
 * cannot reach this surface — it's administrator-only.
 */
export default function PhysicalLocationClient({ initialLocation }: Props) {
  const router = useRouter()
  const [loc, setLoc] = useState<PhysicalLocationDetail>(initialLocation)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [savedFlash, setSavedFlash] = useState(false)
  const [dragActive, setDragActive] = useState(false)
  const artworkInputRef = useRef<HTMLInputElement | null>(null)

  // Section-local unsaved edits
  const [name, setName] = useState(loc.name)
  const [slug, setSlug] = useState(loc.slug)
  const [region, setRegion] = useState(loc.region ?? '')
  const [country, setCountry] = useState(loc.country_code)
  const [blurb, setBlurb] = useState(loc.blurb ?? '')
  const [adminNote, setAdminNote] = useState(loc.admin_note ?? '')
  const [altText, setAltText] = useState(loc.artwork_alt_text ?? '')

  const identityDirty =
    name !== loc.name
    || slug !== loc.slug
    || (region || null) !== loc.region
    || country !== loc.country_code
  const blurbDirty = (blurb || null) !== loc.blurb
  const adminNoteDirty = (adminNote || null) !== loc.admin_note
  const altTextDirty = (altText || null) !== loc.artwork_alt_text

  const flashSaved = () => {
    setSavedFlash(true)
    setTimeout(() => setSavedFlash(false), 1400)
  }

  const patch = useCallback(async (body: Record<string, unknown>, verb: string) => {
    setBusy(verb)
    setError(null)
    try {
      const res = await fetch(
        apiUrl(`/api/admin/physical-locations/${loc.slug}`),
        {
          method: 'PATCH',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        },
      )
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(typeof data.detail === 'string' ? data.detail : 'Save failed.')
      }
      const updated = (await res.json()) as PhysicalLocationDetail
      const slugChanged = updated.slug !== loc.slug
      setLoc(updated)
      setName(updated.name)
      setSlug(updated.slug)
      setRegion(updated.region ?? '')
      setCountry(updated.country_code)
      setBlurb(updated.blurb ?? '')
      setAdminNote(updated.admin_note ?? '')
      setAltText(updated.artwork_alt_text ?? '')
      flashSaved()
      if (slugChanged) {
        // Slug is the URL key — reflect it so the browser bar and
        // future PATCHes point at the new resource path.
        router.replace(`/admin/physical-locations/${updated.slug}`)
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Save failed.')
    } finally {
      setBusy(null)
    }
  }, [loc.slug, router])

  const saveIdentity = useCallback(() => {
    patch({
      name: name.trim(),
      slug: slug.trim(),
      region: region.trim() || null,
      country_code: country.trim(),
    }, 'identity')
  }, [patch, name, slug, region, country])

  const saveBlurb = useCallback(() => {
    patch({ blurb: blurb.trim() || null }, 'blurb')
  }, [patch, blurb])

  const saveAdminNote = useCallback(() => {
    patch({ admin_note: adminNote.trim() || null }, 'admin-note')
  }, [patch, adminNote])

  const saveAltText = useCallback(() => {
    patch({ artwork_alt_text: altText.trim() || null }, 'alt-text')
  }, [patch, altText])

  const setStatus = useCallback((status: PhysicalLocationStatus) => {
    patch({ status }, 'status')
  }, [patch])

  const setFocalPoint = useCallback((x: number, y: number) => {
    patch({ artwork_focal_x: x, artwork_focal_y: y }, 'focal')
  }, [patch])

  const uploadArtwork = useCallback(async (file: File) => {
    setBusy('artwork')
    setError(null)
    try {
      const body = new FormData()
      body.append('file', file)
      const res = await fetch(
        apiUrl(`/api/admin/physical-locations/${loc.slug}/artwork`),
        { method: 'POST', credentials: 'include', body },
      )
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(typeof data.detail === 'string' ? data.detail : 'Upload failed.')
      }
      const updated = (await res.json()) as PhysicalLocationDetail
      setLoc(updated)
      setAltText(updated.artwork_alt_text ?? '')
      flashSaved()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Upload failed.')
    } finally {
      setBusy(null)
    }
  }, [loc.slug])

  const handleDroppedFile = useCallback((file: File | null | undefined) => {
    if (!file) return
    const okType = /^image\/(jpeg|png|webp)$/i.test(file.type)
      || /\.(jpe?g|png|webp)$/i.test(file.name)
    if (!okType) {
      setError('Only JPG, PNG, and WebP images are allowed.')
      return
    }
    uploadArtwork(file)
  }, [uploadArtwork])

  const deleteLocation = useCallback(async () => {
    if (loc.collectives.length > 0) {
      setError(
        `${loc.collectives.length} Collective(s) are still linked to this Physical Location. Move or remove those links first.`,
      )
      return
    }
    if (!confirm(`Delete the Physical Location "${loc.name}"? This cannot be undone.`)) return
    setBusy('delete')
    setError(null)
    try {
      const res = await fetch(
        apiUrl(`/api/admin/physical-locations/${loc.slug}`),
        { method: 'DELETE', credentials: 'include' },
      )
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(typeof data.detail === 'string' ? data.detail : 'Could not delete.')
      }
      router.push('/admin/physical-locations')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not delete.')
      setBusy(null)
    }
  }, [loc.collectives.length, loc.name, loc.slug, router])

  const clearArtwork = useCallback(async () => {
    if (!confirm('Remove the artwork for this Physical Location? The deterministic atmosphere fallback will render on Discover Places until new artwork is uploaded.')) return
    setBusy('clear-artwork')
    setError(null)
    try {
      const res = await fetch(
        apiUrl(`/api/admin/physical-locations/${loc.slug}/artwork`),
        { method: 'DELETE', credentials: 'include' },
      )
      if (!res.ok) throw new Error('Could not remove artwork.')
      const updated = (await res.json()) as PhysicalLocationDetail
      setLoc(updated)
      setAltText('')
      flashSaved()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not remove artwork.')
    } finally {
      setBusy(null)
    }
  }, [loc.slug])

  const artworkResolved = resolveMediaUrl(loc.hero_artwork_url)
  const activeCollectiveCount = loc.collectives.filter((c) => c.status === 'active').length

  return (
    <div className="mx-auto max-w-[1000px] px-6 py-10 md:px-10">
      <Link
        href="/admin/physical-locations"
        className="mb-6 inline-flex items-center text-[13px] font-medium transition-opacity hover:opacity-70"
        style={{ color: 'rgba(12, 24, 38, 0.62)' }}
      >
        ← Physical Locations
      </Link>

      <header className="mb-10 flex flex-wrap items-end justify-between gap-6">
        <div>
          <p
            className="mb-3 text-[11px] font-semibold uppercase tracking-[0.28em]"
            style={{ color: '#38A09E' }}
          >
            Physical Location
          </p>
          <h1 className="font-serif text-[32px] leading-tight md:text-[40px]" style={{ color: '#0C1826' }}>
            {loc.name}
          </h1>
          <p className="mt-1.5 text-[13.5px]" style={{ color: 'rgba(12,24,38,0.55)' }}>
            {[loc.region, loc.country_code].filter(Boolean).join(' · ')}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {(['draft', 'active', 'hidden', 'archived'] as const).map((s) => {
            const on = loc.status === s
            return (
              <button
                key={s}
                type="button"
                disabled={busy !== null || on}
                onClick={() => setStatus(s)}
                className="rounded-full px-3.5 py-1.5 text-[11.5px] font-semibold uppercase tracking-wide transition-all disabled:cursor-default"
                style={{
                  background: on ? 'rgba(56,160,158,0.10)' : '#FFFFFF',
                  border: on ? '1px solid rgba(56,160,158,0.55)' : '1px solid rgba(12,24,38,0.12)',
                  color: on ? '#38A09E' : 'rgba(12,24,38,0.55)',
                }}
              >
                {STATUS_LABEL[s]}
              </button>
            )
          })}
        </div>
      </header>

      {savedFlash && (
        <p className="mb-6 text-[13px] italic" style={{ color: '#38A09E', fontFamily: 'Georgia, serif' }}>
          Saved.
        </p>
      )}
      {error && (
        <p className="mb-6 text-[13px]" style={{ color: '#A64526' }}>
          {error}
        </p>
      )}

      {loc.status === 'archived' && activeCollectiveCount > 0 && (
        <div
          className="mb-6 rounded-2xl px-5 py-4"
          style={{
            background: 'rgba(166,69,38,0.06)',
            border: '1px solid rgba(166,69,38,0.25)',
            color: '#7A3220',
          }}
        >
          <p className="text-[13.5px] leading-relaxed" style={{ fontFamily: 'Georgia, serif' }}>
            This Physical Location is archived, but {activeCollectiveCount === 1
              ? '1 active Collective is'
              : `${activeCollectiveCount} active Collectives are`} still associated with it. They will not lose their association, but Discover Places will stop offering the Location as a way in.
          </p>
        </div>
      )}

      {/* ─── 1. Identity ─────────────────────────────────────────── */}
      <Section title="Identity" eyebrow="One">
        <p className="mb-4 text-[13.5px] italic" style={{ color: 'rgba(12,24,38,0.62)', fontFamily: 'Georgia, serif' }}>
          The name and geographic anchor. Slug is the URL key on Discover Places.
        </p>
        <div
          className="mb-5 rounded-xl px-4 py-3"
          style={{
            background: 'rgba(56,160,158,0.06)',
            border: '1px solid rgba(56,160,158,0.24)',
          }}
        >
          <p
            className="text-[13px] leading-relaxed"
            style={{ color: 'rgba(12, 24, 38, 0.72)', fontFamily: 'Georgia, serif' }}
          >
            Use a broad location members will naturally recognise
            and search for, such as Melbourne, Hobart or the Blue
            Mountains. Store suburbs and venue addresses on the
            Collective or Gathering.
          </p>
        </div>
        <div className="grid gap-5">
          <Field label="Name">
            <TextInput value={name} onChange={setName} maxLength={200} />
          </Field>
          <Field label="URL slug">
            <TextInput value={slug} onChange={setSlug} maxLength={100} />
          </Field>
          <div className="grid gap-5 md:grid-cols-[1.6fr_1fr]">
            <Field label="State / region">
              <TextInput
                value={region}
                onChange={setRegion}
                maxLength={100}
                placeholder="Northern Rivers"
              />
            </Field>
            <Field label="Country (ISO)">
              <TextInput
                value={country}
                onChange={(v) => setCountry(v.toUpperCase().slice(0, 2))}
                maxLength={2}
              />
            </Field>
          </div>
          <div>
            <PrimaryButton onClick={saveIdentity} disabled={!identityDirty || busy !== null}>
              {busy === 'identity' ? 'Saving…' : 'Save identity'}
            </PrimaryButton>
          </div>
        </div>
      </Section>

      {/* ─── 2. Blurb ─────────────────────────────────────────────── */}
      <Section title="Editorial blurb" eyebrow="Two">
        <p className="mb-5 text-[13.5px] italic" style={{ color: 'rgba(12,24,38,0.62)', fontFamily: 'Georgia, serif' }}>
          Member-facing description for Discover Places. A few paragraphs about what Fresh Collective looks like here.
        </p>
        <TextArea
          value={blurb}
          onChange={setBlurb}
          maxLength={4000}
          rows={8}
          placeholder="What draws people to gather here?"
        />
        <div className="mt-5">
          <PrimaryButton onClick={saveBlurb} disabled={!blurbDirty || busy !== null}>
            {busy === 'blurb' ? 'Saving…' : 'Save blurb'}
          </PrimaryButton>
        </div>
      </Section>

      {/* ─── 3. Artwork ──────────────────────────────────────────── */}
      <Section title="Artwork" eyebrow="Three">
        <p className="mb-5 text-[13.5px] italic" style={{ color: 'rgba(12,24,38,0.62)', fontFamily: 'Georgia, serif' }}>
          Curated hero image for Discover Places. Used only for the
          geographic surface — never for Collective cards, Atlas
          Islands, or Creator Studio identity. When present,
          overrides the deterministic atmospheric fallback.
        </p>
        <div
          onDragOver={(e) => { e.preventDefault(); setDragActive(true) }}
          onDragEnter={(e) => { e.preventDefault(); setDragActive(true) }}
          onDragLeave={(e) => { if (e.currentTarget === e.target) setDragActive(false) }}
          onDrop={(e) => {
            e.preventDefault()
            setDragActive(false)
            handleDroppedFile(e.dataTransfer.files?.[0])
          }}
          className="relative mb-6 overflow-hidden rounded-2xl bg-white transition-all"
          style={{
            aspectRatio: '3 / 2',
            border: dragActive
              ? '1px dashed rgba(56, 160, 158, 0.65)'
              : '1px solid rgba(12, 24, 38, 0.08)',
            boxShadow: dragActive
              ? '0 0 0 6px rgba(56, 160, 158, 0.12), 0 12px 32px rgba(12, 24, 38, 0.08)'
              : '0 12px 32px rgba(12, 24, 38, 0.08)',
          }}
        >
          {artworkResolved ? (
            <>
              <img
                src={artworkResolved}
                alt={loc.artwork_alt_text ?? ''}
                className="h-full w-full object-cover"
                style={{
                  objectPosition: `${loc.artwork_focal_x * 100}% ${loc.artwork_focal_y * 100}%`,
                }}
              />
              {/* Focal-point picker overlay. Click to set the CSS
                   ``object-position`` used across every cropped
                   rendering. */}
              <FocalOverlay
                x={loc.artwork_focal_x}
                y={loc.artwork_focal_y}
                onPick={(x, y) => setFocalPoint(x, y)}
                disabled={busy !== null}
              />
            </>
          ) : (
            <div
              className="flex h-full w-full items-center justify-center"
              style={{
                background: 'linear-gradient(135deg, rgba(56,160,158,0.10) 0%, rgba(85,184,182,0.04) 100%)',
              }}
            >
              <p
                className="max-w-sm px-6 text-center text-[13.5px] italic leading-relaxed"
                style={{ color: 'rgba(12,24,38,0.55)', fontFamily: 'Georgia, serif' }}
              >
                No artwork yet. Discover Places will render the
                deterministic atmosphere gradient for this slug.
              </p>
            </div>
          )}
        </div>
        <p
          className="mb-4 text-[12.5px] italic"
          style={{ color: 'rgba(12, 24, 38, 0.55)', fontFamily: 'Georgia, serif' }}
        >
          Drag &amp; drop a JPG, PNG or WebP onto the preview — or use the buttons below. {artworkResolved && 'Click anywhere on the preview to set the focal point.'}
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <input
            ref={artworkInputRef}
            type="file"
            accept="image/jpeg,image/png,image/webp"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0]
              if (f) uploadArtwork(f)
              e.target.value = ''
            }}
          />
          <PrimaryButton onClick={() => artworkInputRef.current?.click()} disabled={busy !== null}>
            {busy === 'artwork'
              ? 'Uploading…'
              : artworkResolved ? 'Replace artwork' : 'Upload artwork'}
          </PrimaryButton>
          {artworkResolved && (
            <SecondaryButton onClick={clearArtwork} disabled={busy !== null}>
              {busy === 'clear-artwork' ? 'Removing…' : 'Remove'}
            </SecondaryButton>
          )}
          {artworkResolved && (
            <span className="ml-1 text-[12px]" style={{ color: 'rgba(12,24,38,0.50)' }}>
              Focal point: {Math.round(loc.artwork_focal_x * 100)}% × {Math.round(loc.artwork_focal_y * 100)}%
            </span>
          )}
        </div>
        {artworkResolved && (
          <div className="mt-6">
            <Field label="Alt text">
              <TextArea
                value={altText}
                onChange={setAltText}
                maxLength={500}
                rows={2}
                placeholder="Describe the artwork for members using screen readers."
              />
            </Field>
            <div className="mt-3">
              <PrimaryButton onClick={saveAltText} disabled={!altTextDirty || busy !== null}>
                {busy === 'alt-text' ? 'Saving…' : 'Save alt text'}
              </PrimaryButton>
            </div>
          </div>
        )}
      </Section>

      {/* ─── 4. Admin note ────────────────────────────────────────── */}
      <Section title="Admin note" eyebrow="Four">
        <p className="mb-5 text-[13.5px] italic" style={{ color: 'rgba(12,24,38,0.62)', fontFamily: 'Georgia, serif' }}>
          Internal note. Never surfaced to members or Creators — the equivalent of a Post-it stuck to this record.
        </p>
        <TextArea
          value={adminNote}
          onChange={setAdminNote}
          maxLength={4000}
          rows={5}
          placeholder="Notes for future administrators. Commissioned artist, editorial decisions, unresolved questions…"
        />
        <div className="mt-5">
          <PrimaryButton onClick={saveAdminNote} disabled={!adminNoteDirty || busy !== null}>
            {busy === 'admin-note' ? 'Saving…' : 'Save admin note'}
          </PrimaryButton>
        </div>
      </Section>

      {/* ─── 5. Usage ────────────────────────────────────────────── */}
      <Section title="Collectives here" eyebrow="Five">
        {loc.collectives.length === 0 ? (
          <p className="text-[14.5px] italic" style={{ color: 'rgba(12,24,38,0.60)', fontFamily: 'Georgia, serif' }}>
            No Collectives are associated with this Physical Location yet.
          </p>
        ) : (
          <ul className="divide-y" style={{ borderColor: 'rgba(12,24,38,0.06)' }}>
            {loc.collectives.map((c) => (
              <li key={c.id} className="flex items-center justify-between gap-3 py-3">
                <div>
                  <p className="text-[14.5px] font-semibold" style={{ color: '#0C1826' }}>{c.name}</p>
                  <p className="text-[12px]" style={{ color: 'rgba(12,24,38,0.55)' }}>{c.slug}</p>
                </div>
                <span
                  className="rounded-full px-2.5 py-0.5 text-[10.5px] font-semibold uppercase tracking-wide"
                  style={{ background: 'rgba(12,24,38,0.05)', color: 'rgba(12,24,38,0.62)' }}
                >
                  {c.status}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Section>

      {/* ─── 6. Metadata ─────────────────────────────────────────── */}
      <Section title="Coordinates & provider" eyebrow="Six">
        <p className="mb-5 text-[13.5px] italic" style={{ color: 'rgba(12,24,38,0.62)', fontFamily: 'Georgia, serif' }}>
          Filled from the location autocomplete picker when Places are created through the picker. Read-only here — edit the picker payload upstream, not the row.
        </p>
        <dl className="grid gap-3 text-[13.5px] md:grid-cols-2" style={{ color: '#0C1826' }}>
          <MetaRow label="Latitude" value={loc.latitude?.toString() ?? '—'} />
          <MetaRow label="Longitude" value={loc.longitude?.toString() ?? '—'} />
          <MetaRow label="Timezone" value={loc.timezone ?? '—'} />
          <MetaRow label="Provider id" value={loc.provider_place_id ?? '—'} />
          <MetaRow label="Created" value={new Date(loc.created_at).toLocaleString()} />
          <MetaRow label="Updated" value={new Date(loc.updated_at).toLocaleString()} />
        </dl>
      </Section>

      {/* ─── Delete ──────────────────────────────────────────────── */}
      <section
        className="mb-6 rounded-2xl px-6 py-6 md:px-10 md:py-8"
        style={{
          background: '#FFFFFF',
          border: '1px solid rgba(166,69,38,0.20)',
        }}
      >
        <div className="mb-4 flex items-baseline gap-3">
          <p
            className="text-[11px] font-semibold uppercase tracking-[0.28em]"
            style={{ color: '#A64526' }}
          >
            Delete
          </p>
          <h2
            className="font-serif text-[20px]"
            style={{ color: '#0C1826' }}
          >
            Remove this Physical Location
          </h2>
        </div>
        <p
          className="mb-5 text-[13.5px] italic leading-relaxed"
          style={{ color: 'rgba(12,24,38,0.65)', fontFamily: 'Georgia, serif' }}
        >
          Physical Locations are curated discovery records — an unused
          one should simply not exist. Deletion is permanent and
          available only when no Collectives are still linked here.
          {loc.collectives.length > 0
            ? ' Move or remove those links first.'
            : ' Any member with this as their home place will have that personal preference cleanly cleared.'}
        </p>
        <button
          type="button"
          onClick={deleteLocation}
          disabled={busy !== null || loc.collectives.length > 0}
          className="rounded-full px-5 py-2.5 text-[13px] font-semibold transition-opacity hover:opacity-90 disabled:opacity-40 disabled:cursor-not-allowed"
          style={{
            background: loc.collectives.length > 0 ? '#FFFFFF' : '#A64526',
            border: '1px solid rgba(166,69,38,0.55)',
            color: loc.collectives.length > 0 ? '#A64526' : '#FFFFFF',
            letterSpacing: '0.06em',
          }}
        >
          {busy === 'delete'
            ? 'Deleting…'
            : loc.collectives.length > 0
            ? `Blocked — ${loc.collectives.length} Collective${loc.collectives.length === 1 ? '' : 's'} linked`
            : 'Delete this Physical Location'}
        </button>
      </section>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Focal point overlay
// ---------------------------------------------------------------------------

function FocalOverlay({
  x, y, onPick, disabled,
}: {
  x: number; y: number
  onPick: (x: number, y: number) => void
  disabled: boolean
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={(e) => {
        const rect = e.currentTarget.getBoundingClientRect()
        const px = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width))
        const py = Math.max(0, Math.min(1, (e.clientY - rect.top) / rect.height))
        onPick(Number(px.toFixed(3)), Number(py.toFixed(3)))
      }}
      className="absolute inset-0 h-full w-full cursor-crosshair disabled:cursor-progress"
      aria-label="Set focal point"
    >
      <span
        aria-hidden
        className="absolute h-6 w-6 -translate-x-1/2 -translate-y-1/2 rounded-full"
        style={{
          left: `${x * 100}%`,
          top: `${y * 100}%`,
          background: 'rgba(255,255,255,0.85)',
          border: '2px solid rgba(56,160,158,0.9)',
          boxShadow: '0 0 0 3px rgba(56,160,158,0.25)',
        }}
      />
    </button>
  )
}

// ---------------------------------------------------------------------------
// Composition helpers
// ---------------------------------------------------------------------------

function Section({ title, eyebrow, children }: {
  title: string; eyebrow: string; children: React.ReactNode
}) {
  return (
    <section
      className="mb-6 rounded-2xl bg-white px-6 py-8 md:px-10 md:py-10"
      style={{
        border: '1px solid rgba(12, 24, 38, 0.06)',
        boxShadow: '0 1px 3px rgba(12, 24, 38, 0.03)',
      }}
    >
      <div className="mb-6 flex items-baseline gap-3">
        <p
          className="text-[11px] font-semibold uppercase tracking-[0.28em]"
          style={{ color: '#38A09E' }}
        >
          {eyebrow}
        </p>
        <h2
          className="font-serif text-[22px]"
          style={{ color: '#0C1826' }}
        >
          {title}
        </h2>
      </div>
      {children}
    </section>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label
        className="mb-2 block text-[11px] font-semibold uppercase tracking-[0.20em]"
        style={{ color: 'rgba(12, 24, 38, 0.62)' }}
      >
        {label}
      </label>
      {children}
    </div>
  )
}

function MetaRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-black/5 py-1.5">
      <dt
        className="text-[11px] font-semibold uppercase tracking-[0.20em]"
        style={{ color: 'rgba(12,24,38,0.55)' }}
      >
        {label}
      </dt>
      <dd className="truncate text-[13.5px]" style={{ color: '#0C1826' }}>
        {value}
      </dd>
    </div>
  )
}

function TextInput({
  value, onChange, maxLength, placeholder,
}: { value: string; onChange: (v: string) => void; maxLength?: number; placeholder?: string }) {
  return (
    <input
      type="text"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      maxLength={maxLength}
      placeholder={placeholder}
      className="w-full rounded-xl px-4 py-3 text-[15px] focus:outline-none"
      style={{
        background: '#FFFFFF',
        border: '1px solid rgba(12, 24, 38, 0.12)',
        color: '#0C1826',
      }}
      onFocus={(e) => {
        e.currentTarget.style.border = '1px solid rgba(56, 160, 158, 0.55)'
        e.currentTarget.style.boxShadow = '0 0 0 4px rgba(56, 160, 158, 0.10)'
      }}
      onBlur={(e) => {
        e.currentTarget.style.border = '1px solid rgba(12, 24, 38, 0.12)'
        e.currentTarget.style.boxShadow = 'none'
      }}
    />
  )
}

function TextArea({
  value, onChange, maxLength, rows = 4, placeholder,
}: { value: string; onChange: (v: string) => void; maxLength?: number; rows?: number; placeholder?: string }) {
  return (
    <textarea
      value={value}
      onChange={(e) => onChange(e.target.value)}
      maxLength={maxLength}
      rows={rows}
      placeholder={placeholder}
      className="w-full resize-none rounded-xl px-5 py-4 text-[15.5px] leading-[1.7] focus:outline-none"
      style={{
        background: '#FFFFFF',
        border: '1px solid rgba(12, 24, 38, 0.12)',
        color: '#0C1826',
        fontFamily: 'Georgia, serif',
      }}
      onFocus={(e) => {
        e.currentTarget.style.border = '1px solid rgba(56, 160, 158, 0.55)'
        e.currentTarget.style.boxShadow = '0 0 0 4px rgba(56, 160, 158, 0.10)'
      }}
      onBlur={(e) => {
        e.currentTarget.style.border = '1px solid rgba(12, 24, 38, 0.12)'
        e.currentTarget.style.boxShadow = 'none'
      }}
    />
  )
}

function PrimaryButton({ children, onClick, disabled }: {
  children: React.ReactNode; onClick: () => void; disabled?: boolean
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="rounded-full px-6 py-2.5 text-[13px] font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-40"
      style={{
        background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)',
        letterSpacing: '0.06em',
      }}
    >
      {children}
    </button>
  )
}

function SecondaryButton({ children, onClick, disabled }: {
  children: React.ReactNode; onClick: () => void; disabled?: boolean
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="rounded-full px-4 py-2.5 text-[13px] font-medium transition-colors hover:bg-black/[4%] disabled:opacity-40"
      style={{
        background: '#FFFFFF',
        border: '1px solid rgba(12,24,38,0.14)',
        color: '#0C1826',
      }}
    >
      {children}
    </button>
  )
}
