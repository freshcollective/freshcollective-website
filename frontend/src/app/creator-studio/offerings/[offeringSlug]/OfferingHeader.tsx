'use client'

import React, { useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { apiUrl } from '@/lib/api'
import CollectiveArtworkHeader from '@/components/creator/CollectiveArtworkHeader'
import type { CreatorOffering, OfferingReadiness } from '@/types/platform'

export type OfferingTab = 'details' | 'about' | 'files' | 'pricing'

interface Location {
  name: string
  hero_artwork_url?: string | null
  thumbnail_artwork_url?: string | null
}

interface Props {
  active: OfferingTab
  spaceSlug: string
  spaceName: string
  offering: CreatorOffering
  readiness: OfferingReadiness | null
  location?: Location | null
  coverImageUrl?: string | null
}

/**
 * Shared header for every Offering sub-page.
 *
 * Same anatomy as ``PathwayHeader``: the Collective artwork header for
 * identity, then a tab bar. A creator moving between a Pathway and an
 * Offering meets the same furniture in the same place.
 *
 * Two things differ, and both are the approved design:
 *
 *   * The four tabs are **route-based** and carry the approved emoji
 *     (Details / About / Files / Pricing), so a tab is a URL a creator
 *     can bookmark or reload into, and a half-finished Offering is
 *     never lost to a client-side tab index.
 *   * **Preview and Publish are header actions**, not buttons buried in
 *     a tab. Publishing is the one irreversible-feeling step, so it sits
 *     where it can be seen from every tab, with the readiness count
 *     beside it rather than discovered on failure.
 */
export default function OfferingHeader({
  active, spaceSlug, spaceName, offering, readiness,
  location = null, coverImageUrl = null,
}: Props) {
  const router = useRouter()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showUnmet, setShowUnmet] = useState(false)

  const base = `/creator-studio/offerings/${offering.slug}`
  const tabs: { key: OfferingTab; label: string; href: string }[] = [
    { key: 'details', label: '🌸 Details', href: base },
    { key: 'about', label: '✨ About', href: `${base}/about` },
    { key: 'files', label: '📦 Files', href: `${base}/files` },
    { key: 'pricing', label: '💛 Pricing', href: `${base}/pricing` },
  ]

  const unmet = (readiness?.requirements ?? []).filter((r) => !r.met)
  const ready = readiness?.ready ?? false
  const isPublished = offering.status === 'published'
  const isRetired = offering.status === 'retired'

  const statusWord =
    isPublished ? 'Published' : isRetired ? 'Retired' : 'Draft'
  const metaParts = [statusWord]
  if (offering.file_count > 0) {
    metaParts.push(
      `${offering.file_count} file${offering.file_count === 1 ? '' : 's'}`,
    )
  }

  async function act(path: string, successMessage?: string) {
    setBusy(true)
    setError(null)
    try {
      const res = await fetch(
        apiUrl(`/api/creator/spaces/${spaceSlug}/offerings/${offering.slug}/${path}`),
        { method: 'POST', credentials: 'include' },
      )
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        const detail = body?.detail
        // Publish returns a structured 409 listing what is unmet. Show
        // the sentence, and open the checklist rather than making the
        // creator hunt for which requirement failed.
        if (detail && typeof detail === 'object' && detail.message) {
          setError(detail.message)
          setShowUnmet(true)
        } else {
          setError(
            typeof detail === 'string' ? detail : `That didn't work (${res.status}).`,
          )
        }
        return
      }
      if (successMessage) setError(null)
      router.refresh()
    } catch {
      setError("That didn't work. Please try again.")
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mb-6">
      <CollectiveArtworkHeader
        collectiveName={spaceName}
        sectionTitle={offering.title}
        meta={metaParts.join(' · ')}
        location={location}
        coverImageUrl={coverImageUrl}
        backLink={{ href: '/creator-studio/offerings', label: 'Back to Offerings' }}
      />

      <div className="mt-2 flex flex-wrap items-center gap-2">
        <div className="flex flex-wrap gap-1.5">
          {tabs.map((tab) => {
            const isActive = tab.key === active
            return (
              <Link
                key={tab.key}
                href={tab.href}
                aria-current={isActive ? 'page' : undefined}
                className="rounded-full px-4 py-1.5 text-[13px] font-medium transition-colors"
                style={
                  isActive
                    ? {
                        background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)',
                        color: '#ffffff',
                        border: '1px solid rgba(56,160,158,0.35)',
                      }
                    : {
                        background: 'white',
                        color: '#0f766e',
                        border: '1px solid rgba(56,160,158,0.20)',
                      }
                }
              >
                {tab.label}
              </Link>
            )
          })}
        </div>

        <div className="ml-auto flex flex-wrap items-center gap-2">
          <a
            href={`${base}/preview`}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 rounded-full border border-border bg-white px-4 py-1.5 text-[13px] font-medium text-black transition-colors hover:border-teal-200 hover:text-teal-700"
          >
            Preview <span aria-hidden="true">↗</span>
          </a>

          {!isRetired && !isPublished && (
            <button
              type="button"
              onClick={() => act('publish')}
              disabled={busy || !ready}
              title={
                ready
                  ? 'Make this available to members'
                  : 'A few things still need attention first'
              }
              className="inline-flex items-center rounded-full px-4 py-1.5 text-[13px] font-semibold text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
              style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
            >
              {busy ? 'Publishing…' : 'Publish'}
            </button>
          )}

          {isPublished && (
            <button
              type="button"
              onClick={() => {
                if (
                  confirm(
                    'Retire this Offering?\n\nIt stops being available to new '
                    + 'members. Everyone who already has it keeps their files.',
                  )
                ) act('retire')
              }}
              disabled={busy}
              className="inline-flex items-center rounded-full border border-slate-200 bg-white px-4 py-1.5 text-[13px] font-medium text-black transition-colors hover:border-slate-300 disabled:opacity-40"
            >
              {busy ? 'Retiring…' : 'Retire'}
            </button>
          )}
        </div>
      </div>

      {/* Readiness — shown only while there is something to do, and only
          before publishing. A published Offering with a later problem is
          surfaced on the Files tab, which is where it can be fixed. */}
      {!isPublished && !isRetired && unmet.length > 0 && (
        <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50/70 px-4 py-3">
          <button
            type="button"
            onClick={() => setShowUnmet((v) => !v)}
            aria-expanded={showUnmet}
            className="flex w-full items-center justify-between text-left"
          >
            <span className="text-[13px] font-semibold text-[#7A5A00]">
              {unmet.length} thing{unmet.length === 1 ? '' : 's'} to finish
              before publishing
            </span>
            <span aria-hidden="true" className="text-[#7A5A00]">
              {showUnmet ? '−' : '+'}
            </span>
          </button>
          {showUnmet && (
            <ul className="mt-2 space-y-1.5">
              {unmet.map((r) => (
                <li key={r.id} className="text-[13px] leading-relaxed text-[#6B4F00]">
                  • {r.message}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {isRetired && (
        <p className="mt-3 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-[13px] text-black">
          This Offering has been retired. It is no longer available to new
          members, and everyone who already has it keeps their files.
        </p>
      )}

      {error && (
        <p className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-[13px] text-red-700">
          {error}
        </p>
      )}
    </div>
  )
}
