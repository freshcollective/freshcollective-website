'use client'

import { useCallback, useRef, useState } from 'react'
import Link from 'next/link'
import { apiUrl } from '@/lib/api'
import type { LocationDetail } from '@/lib/atlas/types'
import LocationArtwork from '@/components/admin/atlas/LocationArtwork'

interface Props {
  initialLocation: LocationDetail
}

/**
 * Detail editor for one Location in The Atlas.
 *
 * The page reads like writing an entry in an illustrated atlas, not
 * editing a database record. Four sections:
 *
 *   1. Overview      — name + short description
 *   2. Artwork       — the curated visual identity
 *   3. Atlas Entry   — long-form story of the Location
 *   4. Collectives   — who lives here
 *
 * Classification, biome, archipelago, and recommendation metadata are
 * no longer part of the Atlas surface. See Atlas Volume I, v1.1.
 */
export default function LocationDetailClient({ initialLocation }: Props) {
  const [loc, setLoc] = useState<LocationDetail>(initialLocation)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [savedFlash, setSavedFlash] = useState(false)
  const [dragActive, setDragActive] = useState(false)
  const artworkInputRef = useRef<HTMLInputElement | null>(null)

  // Section-local unsaved edits
  const [name, setName] = useState(loc.name)
  const [description, setDescription] = useState(loc.description ?? '')
  const [atlasEntry, setAtlasEntry] = useState(loc.atlas_entry ?? '')

  const overviewDirty = name !== loc.name || (description || null) !== loc.description
  const entryDirty = (atlasEntry || null) !== loc.atlas_entry

  const flashSaved = () => {
    setSavedFlash(true)
    setTimeout(() => setSavedFlash(false), 1400)
  }

  const patch = useCallback(async (body: Record<string, unknown>, verb: string) => {
    setBusy(verb)
    setError(null)
    try {
      const res = await fetch(apiUrl(`/api/admin/atlas/locations/${loc.key}`), {
        method: 'PATCH',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(typeof data.detail === 'string' ? data.detail : 'Save failed.')
      }
      const updated = await res.json() as LocationDetail
      setLoc(updated)
      flashSaved()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Save failed.')
    } finally {
      setBusy(null)
    }
  }, [loc.key])

  const saveOverview = useCallback(() => {
    patch({
      name: name.trim(),
      description: description.trim() || null,
    }, 'overview')
  }, [patch, name, description])

  const saveEntry = useCallback(() => {
    patch({ atlas_entry: atlasEntry.trim() || null }, 'entry')
  }, [patch, atlasEntry])

  const setStatus = useCallback((status: 'active' | 'hidden') => {
    patch({ status }, 'status')
  }, [patch])

  const setLocationType = useCallback((location_type: 'ATLAS' | 'COMMUNITY' | 'CORNERSTONE') => {
    patch({ location_type }, 'type')
  }, [patch])

  const uploadArtwork = useCallback(async (file: File) => {
    setBusy('artwork')
    setError(null)
    try {
      const body = new FormData()
      body.append('file', file)
      const res = await fetch(
        apiUrl(`/api/admin/atlas/locations/${loc.key}/artwork`),
        { method: 'POST', credentials: 'include', body },
      )
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(typeof data.detail === 'string' ? data.detail : 'Upload failed.')
      }
      const updated = await res.json() as LocationDetail
      setLoc(updated)
      flashSaved()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Upload failed.')
    } finally {
      setBusy(null)
    }
  }, [loc.key])

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

  const clearArtwork = useCallback(async () => {
    if (!confirm('Remove the artwork for this Location?')) return
    setBusy('clear-artwork')
    setError(null)
    try {
      const res = await fetch(
        apiUrl(`/api/admin/atlas/locations/${loc.key}/artwork`),
        { method: 'DELETE', credentials: 'include' },
      )
      if (!res.ok) throw new Error('Could not remove artwork.')
      const updated = await res.json() as LocationDetail
      setLoc(updated)
      flashSaved()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not remove artwork.')
    } finally {
      setBusy(null)
    }
  }, [loc.key])

  return (
    <div className="mx-auto max-w-[1000px] px-6 py-10 md:px-10">
      {/* Back link */}
      <Link
        href="/admin/atlas"
        className="mb-6 inline-flex items-center text-[13px] font-medium transition-opacity hover:opacity-70"
        style={{ color: 'rgba(12, 24, 38, 0.62)' }}
      >
        ← The Atlas
      </Link>

      {/* Header */}
      <header className="mb-10 flex flex-wrap items-end justify-between gap-6">
        <div>
          <p
            className="mb-3 text-[11px] font-semibold uppercase tracking-[0.28em]"
            style={{ color: '#38A09E' }}
          >
            {loc.location_type === 'CORNERSTONE'
              ? 'A Cornerstone'
              : loc.location_type === 'COMMUNITY'
              ? 'A Community Location'
              : 'A Location in the Atlas'}
          </p>
          <h1 className="font-serif text-[32px] leading-tight md:text-[40px]" style={{ color: '#0C1826' }}>
            {loc.name}
          </h1>
        </div>
        <div className="flex items-center gap-3">
          {loc.location_type === 'CORNERSTONE' && (
            <span
              className="rounded-full px-2.5 py-1 text-[10.5px] font-semibold uppercase tracking-wide"
              style={{ background: 'rgba(212,176,72,0.15)', color: '#B08D2A' }}
            >
              Cornerstone
            </span>
          )}
          {loc.location_type === 'COMMUNITY' && (
            <span
              className="rounded-full px-2.5 py-1 text-[10.5px] font-semibold uppercase tracking-wide"
              style={{ background: 'rgba(56,160,158,0.12)', color: '#2E8583' }}
            >
              Community
            </span>
          )}
          {loc.status === 'hidden' && (
            <span
              className="rounded-full px-2.5 py-1 text-[10.5px] font-semibold uppercase tracking-wide"
              style={{ background: 'rgba(12,24,38,0.06)', color: 'rgba(12,24,38,0.55)' }}
            >
              Hidden
            </span>
          )}
          <button
            type="button"
            disabled={busy !== null}
            onClick={() => setStatus(loc.status === 'active' ? 'hidden' : 'active')}
            className="text-[12.5px] font-medium transition-opacity hover:opacity-70"
            style={{ color: 'rgba(12,24,38,0.62)' }}
          >
            {loc.status === 'active' ? 'Hide from creators' : 'Make active'}
          </button>
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

      {/* ─── 1. Overview ──────────────────────────────────────────── */}
      <Section title="Overview" eyebrow="One">
        <p className="mb-5 text-[13.5px] italic" style={{ color: 'rgba(12,24,38,0.62)', fontFamily: 'Georgia, serif' }}>
          Used throughout the platform wherever a concise summary is needed.
        </p>
        <div className="grid gap-5">
          <Field label="Location name">
            <TextInput value={name} onChange={setName} maxLength={200} />
          </Field>
          <Field label="Short description">
            <TextArea
              value={description}
              onChange={setDescription}
              maxLength={2000}
              rows={3}
              placeholder="Ancient forest. Conversations unfolding beneath towering trees."
            />
          </Field>
          <Field label="Type">
            <div className="flex flex-wrap gap-2">
              {(['ATLAS', 'COMMUNITY', 'CORNERSTONE'] as const).map((t) => {
                const on = loc.location_type === t
                return (
                  <button
                    key={t}
                    type="button"
                    onClick={() => setLocationType(t)}
                    disabled={busy !== null || on}
                    className="rounded-full px-4 py-2 text-[12.5px] font-medium transition-all disabled:cursor-default"
                    style={{
                      background: on ? 'rgba(56,160,158,0.10)' : '#FFFFFF',
                      border: on ? '1px solid rgba(56,160,158,0.55)' : '1px solid rgba(12,24,38,0.12)',
                      color: on ? '#38A09E' : '#0C1826',
                      opacity: !on && busy === 'type' ? 0.5 : 1,
                    }}
                  >
                    {t === 'ATLAS' ? 'Atlas Location' : t === 'COMMUNITY' ? 'Community Location' : 'Cornerstone'}
                  </button>
                )
              })}
            </div>
            <p
              className="mt-2 text-[12.5px] italic"
              style={{ color: 'rgba(12,24,38,0.55)', fontFamily: 'Georgia, serif' }}
            >
              {loc.location_type === 'CORNERSTONE'
                ? 'Reserved for Fresh Collective experiences. Not shown to creators.'
                : loc.location_type === 'COMMUNITY'
                ? 'A simple place where a new community begins. Offered to Community (Free) collectives.'
                : 'A premium world available to Creator and Pro collectives.'}
            </p>
          </Field>
          <div>
            <PrimaryButton onClick={saveOverview} disabled={!overviewDirty || busy !== null}>
              {busy === 'overview' ? 'Saving…' : 'Save overview'}
            </PrimaryButton>
          </div>
        </div>
      </Section>

      {/* ─── 2. Artwork ───────────────────────────────────────────── */}
      <Section title="Artwork" eyebrow="Two">
        <p className="mb-5 text-[13.5px] italic" style={{ color: 'rgba(12,24,38,0.62)', fontFamily: 'Georgia, serif' }}>
          The curated visual identity of this Location. A card-sized thumbnail is generated automatically from the hero image and used across the platform wherever this Location appears.
        </p>
        <div
          onDragOver={(e) => { e.preventDefault(); setDragActive(true) }}
          onDragEnter={(e) => { e.preventDefault(); setDragActive(true) }}
          onDragLeave={(e) => {
            // Only reset when leaving the wrapper itself, not moving over a child.
            if (e.currentTarget === e.target) setDragActive(false)
          }}
          onDrop={(e) => {
            e.preventDefault()
            setDragActive(false)
            handleDroppedFile(e.dataTransfer.files?.[0])
          }}
          className="mb-6 overflow-hidden rounded-2xl bg-white transition-all"
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
          <LocationArtwork
            url={loc.hero_artwork_url}
            label={loc.name}
            fit="contain"
            className="h-full w-full"
          />
        </div>
        <p
          className="mb-4 text-[12.5px] italic"
          style={{ color: 'rgba(12, 24, 38, 0.55)', fontFamily: 'Georgia, serif' }}
        >
          Drag &amp; drop a JPG, PNG or WebP onto the preview — or use the buttons below.
        </p>
        <div className="flex flex-wrap gap-2">
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
              : loc.hero_artwork_url ? 'Replace artwork' : 'Upload artwork'}
          </PrimaryButton>
          {loc.hero_artwork_url && (
            <SecondaryButton onClick={clearArtwork} disabled={busy !== null}>
              {busy === 'clear-artwork' ? 'Removing…' : 'Remove'}
            </SecondaryButton>
          )}
        </div>
      </Section>

      {/* ─── 3. Atlas Entry ───────────────────────────────────────── */}
      <Section title="Atlas Entry" eyebrow="Three">
        <p className="mb-5 text-[13.5px] italic" style={{ color: 'rgba(12,24,38,0.62)', fontFamily: 'Georgia, serif' }}>
          The story of the Location — a page in an explorer&apos;s journal. Multiple paragraphs are welcome.
        </p>
        <TextArea
          value={atlasEntry}
          onChange={setAtlasEntry}
          maxLength={20000}
          rows={14}
          placeholder="Begin here. Describe the shape of the land, the quality of the light, the feeling of arriving for the first time…"
        />
        <div className="mt-5">
          <PrimaryButton onClick={saveEntry} disabled={!entryDirty || busy !== null}>
            {busy === 'entry' ? 'Saving…' : 'Save entry'}
          </PrimaryButton>
        </div>
      </Section>

      {/* ─── 4. Collectives ───────────────────────────────────────── */}
      <Section title="Collectives" eyebrow="Four">
        {loc.collectives.length === 0 ? (
          <p className="text-[14.5px] italic" style={{ color: 'rgba(12,24,38,0.60)', fontFamily: 'Georgia, serif' }}>
            There are currently no collectives living here.
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
    </div>
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
        <h2 className="font-serif text-[22px]" style={{ color: '#0C1826' }}>
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
