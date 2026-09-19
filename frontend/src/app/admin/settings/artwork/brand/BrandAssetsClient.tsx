'use client'

import { useCallback, useMemo, useRef, useState } from 'react'

import { apiUrl, resolveMediaUrl } from '@/lib/api'
import {
  acceptAttribute,
  attributionLine,
  missingCount,
  previewAspect,
  previewSurface,
  sourceLabel,
  sourceTone,
  type BrandAsset,
  type BrandAssetGroup,
} from '@/lib/brandAssets'

const NAVY = '#0C1826'
const TEAL = '#38A09E'
const AMBER = '#9A7A18'

interface Props {
  initialGroups: BrandAssetGroup[]
}

/**
 * The Fresh Collective brand, as a set of jobs rather than a folder of
 * files. Each row says what the artwork is for, what shape it should
 * be, where the current one came from, and — where nothing has been
 * approved yet — what is still outstanding and why.
 *
 * Storage keys and filenames are deliberately absent. An administrator
 * replaces "the logo on a dark background"; where those bytes live is
 * ours to know.
 */
export default function BrandAssetsClient({ initialGroups }: Props) {
  const [groups, setGroups] = useState<BrandAssetGroup[]>(initialGroups)

  const replaceAsset = useCallback((next: BrandAsset) => {
    setGroups((prev) => prev.map((g) => ({
      ...g,
      assets: g.assets.map((a) => (a.role === next.role ? next : a)),
    })))
  }, [])

  const missing = useMemo(() => missingCount(groups), [groups])

  return (
    <>
      <header className="mb-10 mt-4">
        <h1
          className="font-serif text-[32px] leading-tight md:text-[40px]"
          style={{ color: NAVY }}
        >
          Fresh Collective Brand
        </h1>
        <p
          className="mt-3 max-w-[620px] text-[15px] italic leading-relaxed"
          style={{ color: 'rgba(12, 24, 38, 0.65)', fontFamily: 'Georgia, serif' }}
        >
          The dragonfly and the wordmark, and every job they do — on a
          page, in a browser tab, at the top of an email. Replace one
          here and everything that uses it follows.
        </p>
        {missing > 0 && (
          <div
            className="mt-6 rounded-xl px-5 py-4"
            style={{ background: 'rgba(231, 198, 90, 0.10)', border: '1px solid rgba(231, 198, 90, 0.35)' }}
          >
            <p className="text-[13.5px] leading-relaxed" style={{ color: AMBER }}>
              <strong>
                {missing} {missing === 1 ? 'role is' : 'roles are'} still
                awaiting approved artwork.
              </strong>{' '}
              Nothing stands in for them, and nothing should: the nearest
              existing file is the wrong artwork, not a smaller version
              of the right one. Each row below says what is outstanding
              and why. Those places keep their current appearance until
              approved artwork is supplied here.
            </p>
          </div>
        )}
      </header>

      <div className="space-y-14">
        {groups.map((group) => (
          <section key={group.group}>
            <div className="mb-5">
              <h2 className="font-serif text-[22px]" style={{ color: NAVY }}>
                {group.label}
              </h2>
              <p
                className="mt-2 max-w-[560px] text-[13.5px] italic leading-relaxed"
                style={{ color: 'rgba(12, 24, 38, 0.62)', fontFamily: 'Georgia, serif' }}
              >
                {group.description}
              </p>
            </div>
            <div className="space-y-6">
              {group.assets.map((asset) => (
                <BrandAssetRow
                  key={asset.role}
                  asset={asset}
                  onChange={replaceAsset}
                />
              ))}
            </div>
          </section>
        ))}
      </div>
    </>
  )
}

// ---------------------------------------------------------------------------
// One role
// ---------------------------------------------------------------------------

function SourceBadge({ asset }: { asset: BrandAsset }) {
  const tone = sourceTone(asset.source)
  const styles = {
    teal: { background: 'rgba(56,160,158,0.10)', color: TEAL },
    neutral: { background: 'rgba(100,116,139,0.10)', color: '#64748B' },
    amber: { background: 'rgba(231,198,90,0.16)', color: AMBER },
  }[tone]
  return (
    <span
      className="inline-flex shrink-0 items-center rounded-full px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.12em]"
      style={styles}
    >
      {sourceLabel(asset.source)}
    </span>
  )
}

function Preview({ asset }: { asset: BrandAsset }) {
  const url = resolveMediaUrl(asset.image_url ?? undefined)
  const surface = previewSurface(asset.role)
  const background =
    surface === 'dark' ? NAVY
      : surface === 'light' ? '#FFFFFF'
        : 'repeating-conic-gradient(rgba(12,24,38,0.05) 0% 25%, transparent 0% 50%) 50% / 16px 16px'

  return (
    <div
      className="flex w-full shrink-0 items-center justify-center overflow-hidden rounded-xl md:w-[180px]"
      style={{
        aspectRatio: previewAspect(asset.role),
        background,
        border: '1px solid rgba(12, 24, 38, 0.08)',
      }}
    >
      {url ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={url}
          alt={asset.title}
          className="max-h-full max-w-full object-contain p-3"
        />
      ) : (
        <span
          className="px-4 text-center text-[11px] font-semibold uppercase tracking-[0.14em]"
          style={{ color: 'rgba(12, 24, 38, 0.30)' }}
        >
          No artwork
        </span>
      )}
    </div>
  )
}

function BrandAssetRow({
  asset, onChange,
}: {
  asset: BrandAsset
  onChange: (next: BrandAsset) => void
}) {
  const [busy, setBusy] = useState<'replace' | 'reset' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement | null>(null)

  const replace = useCallback(async (file: File) => {
    setBusy('replace')
    setError(null)
    try {
      const body = new FormData()
      body.append('file', file)
      const res = await fetch(apiUrl(`/api/admin/brand-assets/${asset.role}`), {
        method: 'POST', credentials: 'include', body,
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        // The backend's validation messages are written for a person —
        // they name the role, the actual dimensions and what is wrong.
        // Surface them verbatim rather than replacing them with
        // "Upload failed".
        throw new Error(
          typeof data.detail === 'string' ? data.detail : 'Upload failed.',
        )
      }
      onChange(data as BrandAsset)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Upload failed.')
    } finally {
      setBusy(null)
    }
  }, [asset.role, onChange])

  const reset = useCallback(async () => {
    if (!confirm(
      `Reset “${asset.title}” to the approved Fresh Collective artwork?`,
    )) return
    setBusy('reset')
    setError(null)
    try {
      const res = await fetch(apiUrl(`/api/admin/brand-assets/${asset.role}`), {
        method: 'DELETE', credentials: 'include',
      })
      if (!res.ok) throw new Error('Could not reset this artwork.')
      onChange(await res.json() as BrandAsset)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not reset this artwork.')
    } finally {
      setBusy(null)
    }
  }, [asset.role, asset.title, onChange])

  const attribution = attributionLine(asset)

  return (
    <section
      className="rounded-2xl bg-white px-6 py-6 md:px-8 md:py-7"
      style={{
        border: '1px solid rgba(12, 24, 38, 0.06)',
        boxShadow: '0 1px 3px rgba(12, 24, 38, 0.03)',
      }}
    >
      <div className="flex flex-col gap-6 md:flex-row">
        <Preview asset={asset} />

        <div className="min-w-0 flex-1">
          <div className="mb-2 flex flex-wrap items-center gap-3">
            <h3 className="text-[15px] font-semibold" style={{ color: NAVY }}>
              {asset.title}
            </h3>
            <SourceBadge asset={asset} />
          </div>

          <p
            className="text-[13.5px] leading-relaxed"
            style={{ color: 'rgba(12, 24, 38, 0.70)' }}
          >
            {asset.intended_use}
          </p>

          <p
            className="mt-3 text-[12.5px] leading-relaxed"
            style={{ color: 'rgba(12, 24, 38, 0.50)' }}
          >
            {asset.recommended}
          </p>

          {asset.source === 'missing' && asset.missing_note && (
            <p
              className="mt-3 rounded-lg px-3 py-2.5 text-[12.5px] leading-relaxed"
              style={{ background: 'rgba(231, 198, 90, 0.10)', color: AMBER }}
            >
              {asset.missing_note}
            </p>
          )}

          {attribution && (
            <p
              className="mt-3 text-[12px]"
              style={{ color: 'rgba(12, 24, 38, 0.45)' }}
            >
              {attribution}
            </p>
          )}

          {error && (
            <p
              className="mt-3 rounded-lg px-3 py-2.5 text-[12.5px] leading-relaxed"
              style={{ background: 'rgba(190, 60, 60, 0.08)', color: '#A33A3A' }}
            >
              {error}
            </p>
          )}

          <div className="mt-5 flex flex-wrap items-center gap-3">
            <input
              ref={inputRef}
              type="file"
              accept={acceptAttribute(asset.accepted_formats)}
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0]
                e.target.value = ''
                if (file) replace(file)
              }}
            />
            <button
              type="button"
              disabled={busy !== null}
              onClick={() => inputRef.current?.click()}
              className="rounded-full px-4 py-2 text-[13px] font-semibold text-white transition-opacity disabled:opacity-50"
              style={{ background: TEAL }}
            >
              {busy === 'replace' ? 'Uploading…' : 'Replace'}
            </button>

            {asset.can_reset && asset.source === 'custom' && (
              <button
                type="button"
                disabled={busy !== null}
                onClick={reset}
                className="rounded-full px-4 py-2 text-[13px] font-semibold transition-opacity disabled:opacity-50"
                style={{
                  border: '1px solid rgba(12, 24, 38, 0.14)',
                  color: 'rgba(12, 24, 38, 0.70)',
                }}
              >
                {busy === 'reset' ? 'Resetting…' : 'Reset to approved default'}
              </button>
            )}

            <span
              className="text-[12px]"
              style={{ color: 'rgba(12, 24, 38, 0.40)' }}
            >
              {asset.accepted_formats.join(' · ')}
            </span>
          </div>
        </div>
      </div>
    </section>
  )
}
