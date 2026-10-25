'use client'

/**
 * The Collectives band on Account Settings → Membership.
 *
 * A client component only so a card can carry the Leave action and
 * disappear when it succeeds. The card markup is unchanged from the
 * server-rendered version it replaced — same rounded-2xl shell, same
 * shadow, same name/joined/role composition — because consistency with
 * the rest of the page is the requirement, and a departure is not an
 * occasion for a different-looking card.
 *
 * After a successful departure it does two things, deliberately both:
 * drops the card from local state so the page answers immediately, and
 * calls ``router.refresh()`` so what remains is the server's list rather
 * than this component's memory of it. If the refresh disagrees, the
 * server wins.
 */

import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useCallback, useState } from 'react'
import type { SpaceMembership } from '@/types/platform'
import { canOfferLeave } from '@/lib/leaveCollective'
import LeaveCollective from './LeaveCollective'

function formatDate(isoString: string): string {
  return new Date(isoString).toLocaleDateString('en-AU', {
    month: 'long', year: 'numeric',
  })
}

function RolePill({ role }: { role: string }) {
  const styles: Record<string, string> = {
    creator:   'bg-teal-50 text-teal-700 border border-teal-200',
    moderator: 'bg-slate-100 text-navy-700 border border-slate-200',
    learner:   'bg-slate-50 text-slate-500 border border-slate-200',
  }
  const labels: Record<string, string> = {
    creator: 'Creator', moderator: 'Moderator', learner: 'Member',
  }
  return (
    <span className={`text-[11px] font-semibold px-2.5 py-0.5 rounded-full ${styles[role] ?? styles.learner}`}>
      {labels[role] ?? role}
    </span>
  )
}

export default function CollectivesList({
  memberships,
}: {
  memberships: SpaceMembership[]
}) {
  const router = useRouter()
  const [rows, setRows] = useState<SpaceMembership[]>(memberships)

  const handleLeft = useCallback((spaceSlug: string) => {
    setRows((prev) => prev.filter((m) => m.space_slug !== spaceSlug))
    router.refresh()
  }, [router])

  if (rows.length === 0) {
    return (
      <div
        className="overflow-hidden rounded-2xl border border-border bg-white px-6 py-10 text-center"
        style={{ boxShadow: '0 1px 4px rgba(0,0,0,0.04)' }}
      >
        <p className="text-[14px] font-medium text-navy-800">Your memberships</p>
        <p className="mt-1 text-[13px] text-black">
          Collectives and membership details will appear here.
        </p>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-3">
      {rows.map((m) => (
        <div
          key={m.space_id}
          className="flex items-center justify-between overflow-hidden rounded-2xl border border-border bg-white px-6 py-4 transition-shadow hover:shadow-sm"
          style={{ boxShadow: '0 1px 4px rgba(0,0,0,0.04)' }}
        >
          <div>
            <Link
              href={`/spaces/${m.space_slug}`}
              className="text-[14px] font-medium text-navy-800 hover:text-teal-700 transition-colors"
            >
              {m.space_name}
            </Link>
            <p className="mt-0.5 text-[12px] text-black">Joined {formatDate(m.joined_at)}</p>
          </div>
          <div className="flex items-center gap-4">
            {canOfferLeave(m.role) && (
              <LeaveCollective
                spaceSlug={m.space_slug}
                spaceName={m.space_name}
                onLeft={handleLeft}
              />
            )}
            <RolePill role={m.role} />
          </div>
        </div>
      ))}
    </div>
  )
}
