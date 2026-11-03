'use client'

import { useState } from 'react'
import Link from 'next/link'
import { apiUrl, resolveMediaUrl } from '@/lib/api'
import type {
  CreatorPathway,
  CreatorSpaceDetail,
  SpaceSummary,
} from '@/types/platform'
import {
  GENERIC_RESTORE_ERROR,
  PATHWAYS_HREF,
  RESTORED_STATUS,
  actionErrorMessage,
  archivedPathways,
} from '@/lib/pathwayLifecycle'
import {
  LifecycleConfirmDialog,
  PathwayCard,
} from '../PathwaysClient'

/**
 * Creator Studio → Pathways → Archived Pathways.
 *
 * The same gallery, the same card, one status. Archiving a Pathway is
 * always a deliberate creator action — nothing here is derived from
 * dates and no pathway becomes archived by getting old — so this page
 * is one filter on one stored status rather than a lifecycle of its
 * own.
 *
 * Restore is the only thing it can change, and it returns a pathway to
 * **Draft**: the creator decides when it goes back in front of
 * members, so there is nothing to undo and nothing becomes visible by
 * pressing it. The request is the same ``PATCH`` the Settings status
 * dropdown has always used — see ``RESTORED_STATUS``.
 */

export default function PathwayArchiveClient({
  initialPathways,
  activeSpace,
  collectiveDetail,
}: {
  initialPathways: CreatorPathway[]
  activeSpace: SpaceSummary | null
  collectiveDetail: CreatorSpaceDetail | null
}) {
  const [pathways, setPathways] = useState<CreatorPathway[]>(initialPathways)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [confirming, setConfirming] = useState<CreatorPathway | null>(null)

  const collectiveFallback = resolveMediaUrl(
    collectiveDetail?.location?.hero_artwork_url
    ?? collectiveDetail?.location?.thumbnail_artwork_url
    ?? collectiveDetail?.cover_image_url
    ?? undefined,
  )

  const archived = archivedPathways(pathways)

  async function restore(pathway: CreatorPathway) {
    if (!activeSpace || busyId) return
    setBusyId(pathway.id)
    setError(null)
    try {
      const res = await fetch(
        apiUrl(`/api/creator/spaces/${activeSpace.slug}/pathways/${pathway.slug}`),
        {
          method: 'PATCH',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ status: RESTORED_STATUS }),
        },
      )
      if (!res.ok) {
        setError(actionErrorMessage(
          await res.json().catch(() => null), GENERIC_RESTORE_ERROR,
        ))
        return
      }
      // Dropped from local state rather than refetched: it is no
      // longer archived, so it no longer belongs on this page. It is
      // waiting in Building when the creator goes back.
      setPathways((prev) => prev.filter((p) => p.id !== pathway.id))
    } catch {
      setError(GENERIC_RESTORE_ERROR)
    } finally {
      setBusyId(null)
      setConfirming(null)
    }
  }

  if (!activeSpace) {
    return (
      <div className="rounded-2xl border border-dashed border-slate-200 bg-white p-8 text-center">
        <p className="text-[14px] text-black">
          Choose a collective from My World to see its pathways.
        </p>
      </div>
    )
  }

  if (archived.length === 0) {
    return (
      <div
        className="rounded-3xl px-8 py-16 text-center"
        style={{ background: '#FBFAF6' }}
      >
        <p className="mb-2 font-serif text-[22px] leading-snug text-navy-900">
          Nothing archived yet.
        </p>
        <p
          className="mx-auto mb-8 max-w-md text-[14.5px] italic leading-relaxed"
          style={{ color: 'rgba(12, 24, 38, 0.62)', fontFamily: 'Georgia, serif' }}
        >
          Pathways you archive will appear here, with their content and
          history preserved.
        </p>
        <Link
          href={PATHWAYS_HREF}
          className="rounded-full px-4 py-2 text-[13px] font-medium transition-colors"
          style={{
            background: 'var(--fc-accent-soft, rgba(56,160,158,0.10))',
            color: 'var(--fc-accent, #0f766e)',
          }}
        >
          &larr; Back to Pathways
        </Link>
      </div>
    )
  }

  return (
    <>
      {error && (
        <div
          className="mb-6 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-[13px] text-red-700"
          role="alert"
        >
          {error}
        </div>
      )}

      <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
        {archived.map((pathway) => (
          <PathwayCard
            key={pathway.id}
            pathway={pathway}
            collectiveFallback={collectiveFallback}
            busy={busyId === pathway.id}
            onRestore={() => setConfirming(pathway)}
          />
        ))}
      </div>

      <div className="mt-10 flex justify-center">
        <Link
          href={PATHWAYS_HREF}
          className="rounded-full px-4 py-2 text-[13px] font-medium transition-colors"
          style={{
            background: 'var(--fc-accent-soft, rgba(56,160,158,0.10))',
            color: 'var(--fc-accent, #0f766e)',
          }}
        >
          &larr; Back to Pathways
        </Link>
      </div>

      {confirming && (
        <LifecycleConfirmDialog
          pathway={confirming}
          action="restore"
          busy={busyId === confirming.id}
          onCancel={() => setConfirming(null)}
          onConfirm={() => restore(confirming)}
        />
      )}
    </>
  )
}
