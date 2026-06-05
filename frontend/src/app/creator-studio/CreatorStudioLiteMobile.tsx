'use client'

import Link from 'next/link'
import { useState } from 'react'
import type { SpaceSummary } from '@/types/platform'

// ---------------------------------------------------------------------------
// Shared types (exported for layout.tsx)
// ---------------------------------------------------------------------------

export interface LiteGathering {
  id: string
  title: string
  starts_at: string
  booked_count: number
  capacity: number | null
}

export interface LiteData {
  pathwayCounts: { published: number; comingSoon: number; drafts: number; archived: number }
  upcomingGatherings: LiteGathering[]
  memberCount: number
  leaderCount: number
  pendingInvites: number
  pendingRequests: number
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatGatheringDate(iso: string) {
  const d = new Date(iso)
  const datePart = d.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' })
  const timePart = d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
  return `${datePart} · ${timePart}`
}

function CopyLinkButton({ slug }: { slug: string }) {
  const [copied, setCopied] = useState(false)

  function handleCopy() {
    const url = `${window.location.origin}/spaces/${slug}`
    navigator.clipboard.writeText(url).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2200)
    })
  }

  return (
    <button
      onClick={handleCopy}
      className="flex-1 rounded-xl border border-slate-200 px-4 py-2.5 text-[13px] font-semibold text-slate-600 transition-colors hover:border-teal-200 hover:text-teal-700"
    >
      {copied ? '✓ Copied!' : 'Copy public link'}
    </button>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

interface Props {
  user: { name: string | null; email: string }
  activeSpace: SpaceSummary | null
  liteData: LiteData
}

export default function CreatorStudioLiteMobile({ user, activeSpace, liteData }: Props) {
  const { pathwayCounts, upcomingGatherings, memberCount, leaderCount, pendingInvites, pendingRequests } = liteData
  const totalPending = pendingInvites + pendingRequests
  const totalPathways = pathwayCounts.published + pathwayCounts.comingSoon + pathwayCounts.drafts + pathwayCounts.archived

  return (
    <div className="min-h-screen" style={{ background: '#F7F8FA' }}>

      {/* ── Header ── */}
      <div
        style={{
          background: 'linear-gradient(180deg, #073B3A 0%, #062F35 100%)',
          borderBottom: '1px solid rgba(255,255,255,0.08)',
        }}
      >
        <div className="px-4 pt-4 pb-4">
          {/* Branding */}
          <div className="mb-3">
            <p className="font-serif text-[17px] leading-tight text-white">Creator Studio</p>
            <p
              className="text-[11px] font-bold uppercase tracking-[0.18em]"
              style={{ color: 'rgba(255,255,255,0.40)' }}
            >
              Fresh Collective
            </p>
          </div>

          {/* Current collective */}
          {activeSpace && (
            <div
              className="mb-3 rounded-xl px-3 py-2.5"
              style={{
                background: 'rgba(255,255,255,0.07)',
                border: '1px solid rgba(255,255,255,0.10)',
              }}
            >
              <p
                className="text-[11px] font-semibold uppercase tracking-wide"
                style={{ color: '#42C7C6' }}
              >
                Current collective
              </p>
              <p className="mt-0.5 text-[14px] font-semibold leading-snug text-white">
                {activeSpace.name}
              </p>
              <p className="mt-0.5 text-[11px]" style={{ color: 'rgba(255,255,255,0.50)' }}>
                {activeSpace.is_public ? 'Public' : 'Private'} ·{' '}
                {activeSpace.status === 'active' ? 'Active' : 'Draft'}
              </p>
            </div>
          )}

          {/* Nav links */}
          <div className="flex items-center gap-4">
            <Link
              href="/dashboard"
              className="text-[12px] font-medium transition-opacity hover:opacity-80"
              style={{ color: 'rgba(255,255,255,0.55)' }}
            >
              ← Back to platform
            </Link>
            {activeSpace && (
              <Link
                href={`/spaces/${activeSpace.slug}`}
                className="ml-auto text-[12px] font-semibold transition-opacity hover:opacity-80"
                style={{ color: '#8DE8E6' }}
              >
                View public page →
              </Link>
            )}
          </div>
        </div>
      </div>

      {/* ── Cards ── */}
      <div className="space-y-4 px-4 py-5 pb-10">

        {/* Notice + primary actions */}
        <div
          className="rounded-2xl bg-white px-5 py-5"
          style={{ border: '1px solid rgba(0,0,0,0.07)', boxShadow: '0 1px 4px rgba(0,0,0,0.04)' }}
        >
          <p className="mb-1.5 text-[15px] font-semibold" style={{ color: '#152236' }}>
            Creator Studio is easier on a larger screen.
          </p>
          <p className="text-[13px] leading-relaxed text-slate-500">
            Pathways, settings, resources, bookings, and content editing work best on desktop or tablet.
            From mobile, you can still check your collective, copy your public link, and see what members see.
          </p>
          {activeSpace && (
            <div className="mt-4 flex gap-2.5">
              <Link
                href={`/spaces/${activeSpace.slug}`}
                className="flex-1 rounded-xl px-4 py-2.5 text-center text-[13px] font-semibold text-white transition-opacity hover:opacity-90"
                style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
              >
                View public collective
              </Link>
              <CopyLinkButton slug={activeSpace.slug} />
            </div>
          )}
        </div>

        {/* Collective overview */}
        {activeSpace && (
          <div
            className="rounded-2xl bg-white px-5 py-4"
            style={{
              border: '1px solid rgba(56,160,158,0.18)',
              borderTop: '2px solid rgba(56,160,158,0.55)',
              boxShadow: '0 1px 4px rgba(0,0,0,0.04)',
            }}
          >
            <p
              className="mb-3 text-[11px] font-bold uppercase tracking-[0.14em]"
              style={{ color: '#38A09E' }}
            >
              Your collective
            </p>
            <p className="text-[16px] font-semibold leading-snug" style={{ color: '#152236' }}>
              {activeSpace.name}
            </p>
            {activeSpace.tagline && (
              <p className="mt-1 text-[13px] leading-relaxed text-slate-500">{activeSpace.tagline}</p>
            )}
            <div className="mt-3 flex flex-wrap gap-2">
              <span
                className="rounded-full px-2.5 py-0.5 text-[11px] font-semibold"
                style={{
                  background: activeSpace.status === 'active' ? 'rgba(56,160,158,0.10)' : 'rgba(0,0,0,0.06)',
                  color: activeSpace.status === 'active' ? '#38A09E' : '#64748b',
                }}
              >
                {activeSpace.status === 'active' ? 'Active' : 'Draft'}
              </span>
              <span
                className="rounded-full px-2.5 py-0.5 text-[11px] font-semibold"
                style={{ background: 'rgba(0,0,0,0.05)', color: '#64748b' }}
              >
                {activeSpace.is_public ? 'Public' : 'Private'}
              </span>
            </div>
          </div>
        )}

        {/* People stats */}
        {(memberCount > 0 || leaderCount > 0 || totalPending > 0) && (
          <div
            className="rounded-2xl bg-white px-5 py-4"
            style={{ border: '1px solid rgba(0,0,0,0.07)', boxShadow: '0 1px 4px rgba(0,0,0,0.04)' }}
          >
            <p className="mb-3 text-[11px] font-bold uppercase tracking-[0.14em] text-slate-400">
              People
            </p>
            <div className="flex gap-6">
              {memberCount > 0 && (
                <div>
                  <p className="text-[22px] font-semibold leading-none" style={{ color: '#152236' }}>
                    {memberCount}
                  </p>
                  <p className="mt-0.5 text-[11px] text-slate-400">
                    {memberCount === 1 ? 'member' : 'members'}
                  </p>
                </div>
              )}
              {leaderCount > 0 && (
                <div>
                  <p className="text-[22px] font-semibold leading-none" style={{ color: '#152236' }}>
                    {leaderCount}
                  </p>
                  <p className="mt-0.5 text-[11px] text-slate-400">
                    {leaderCount === 1 ? 'leader' : 'leaders'}
                  </p>
                </div>
              )}
              {totalPending > 0 && (
                <div>
                  <p className="text-[22px] font-semibold leading-none" style={{ color: '#b08d2a' }}>
                    {totalPending}
                  </p>
                  <p className="mt-0.5 text-[11px] text-slate-400">pending</p>
                </div>
              )}
            </div>
            {totalPending > 0 && (
              <p className="mt-3 text-[12px] text-slate-400">
                Manage invitations and access requests on desktop.
              </p>
            )}
          </div>
        )}

        {/* Upcoming gatherings */}
        {upcomingGatherings.length > 0 && (
          <div
            className="overflow-hidden rounded-2xl bg-white"
            style={{ border: '1px solid rgba(0,0,0,0.07)', boxShadow: '0 1px 4px rgba(0,0,0,0.04)' }}
          >
            <div className="border-b border-border px-5 py-3.5">
              <p className="text-[11px] font-bold uppercase tracking-[0.14em] text-slate-400">
                Upcoming gatherings
              </p>
            </div>
            <div className="divide-y divide-border">
              {upcomingGatherings.map((g) => (
                <div key={g.id} className="px-5 py-3.5">
                  <p className="text-[13px] font-semibold leading-snug" style={{ color: '#152236' }}>
                    {g.title}
                  </p>
                  <p className="mt-0.5 text-[12px] text-slate-400">{formatGatheringDate(g.starts_at)}</p>
                  {g.booked_count > 0 && (
                    <p className="mt-0.5 text-[11px]" style={{ color: '#38A09E' }}>
                      {g.booked_count} booked{g.capacity != null ? ` / ${g.capacity}` : ''}
                    </p>
                  )}
                </div>
              ))}
            </div>
            <div className="border-t border-border px-5 py-3">
              <p className="text-[12px] text-slate-400">
                Manage bookings and edit gatherings on desktop.
              </p>
            </div>
          </div>
        )}

        {/* Pathways overview */}
        <div
          className="rounded-2xl bg-white px-5 py-4"
          style={{ border: '1px solid rgba(0,0,0,0.07)', boxShadow: '0 1px 4px rgba(0,0,0,0.04)' }}
        >
          <p className="mb-3 text-[11px] font-bold uppercase tracking-[0.14em] text-slate-400">
            Pathways
          </p>
          {totalPathways === 0 ? (
            <p className="text-[13px] text-slate-400">No pathways yet.</p>
          ) : (
            <div className="flex flex-wrap gap-x-6 gap-y-3">
              {pathwayCounts.published > 0 && (
                <div>
                  <p className="text-[20px] font-semibold leading-none" style={{ color: '#152236' }}>
                    {pathwayCounts.published}
                  </p>
                  <p className="mt-0.5 text-[11px] text-slate-400">published</p>
                </div>
              )}
              {pathwayCounts.comingSoon > 0 && (
                <div>
                  <p className="text-[20px] font-semibold leading-none" style={{ color: '#152236' }}>
                    {pathwayCounts.comingSoon}
                  </p>
                  <p className="mt-0.5 text-[11px] text-slate-400">coming soon</p>
                </div>
              )}
              {pathwayCounts.drafts > 0 && (
                <div>
                  <p className="text-[20px] font-semibold leading-none" style={{ color: '#152236' }}>
                    {pathwayCounts.drafts}
                  </p>
                  <p className="mt-0.5 text-[11px] text-slate-400">
                    {pathwayCounts.drafts === 1 ? 'draft' : 'drafts'}
                  </p>
                </div>
              )}
              {pathwayCounts.archived > 0 && (
                <div>
                  <p className="text-[20px] font-semibold leading-none text-slate-400">
                    {pathwayCounts.archived}
                  </p>
                  <p className="mt-0.5 text-[11px] text-slate-400">archived</p>
                </div>
              )}
            </div>
          )}
          <p className="mt-3 text-[12px] text-slate-400">Edit and create pathways on desktop.</p>
        </div>

        {/* Resources note */}
        <div
          className="rounded-2xl bg-white px-5 py-4"
          style={{ border: '1px solid rgba(0,0,0,0.07)', boxShadow: '0 1px 4px rgba(0,0,0,0.04)' }}
        >
          <p className="mb-1.5 text-[11px] font-bold uppercase tracking-[0.14em] text-slate-400">
            Resources
          </p>
          <p className="text-[13px] leading-relaxed text-slate-500">
            Resource editing and uploads work best on desktop or tablet.
          </p>
        </div>

        {/* Signed in as */}
        <p className="text-center text-[11px] text-slate-400">
          Signed in as {user.name ?? user.email}
        </p>

      </div>
    </div>
  )
}
