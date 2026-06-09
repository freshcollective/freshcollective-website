import { notFound } from 'next/navigation'
import Link from 'next/link'
import { getPublicProfile, getSpaceMembers } from '@/lib/serverApi'
import Avatar from '@/components/ui/Avatar'
import type { PublicProfile, MemberProfile } from '@/types/platform'

interface Props {
  params: Promise<{ slug: string; memberId: string }>
}

function roleBadge(role: string): { label: string; bg: string; color: string } {
  if (role === 'creator')   return { label: 'Creator',   bg: 'rgba(56,160,158,0.10)',  color: '#0f766e' }
  if (role === 'moderator') return { label: 'Moderator', bg: 'rgba(51,65,85,0.08)',    color: '#334155' }
  return                           { label: 'Member',    bg: 'rgba(148,163,184,0.10)', color: '#64748b' }
}

function formatDate(iso: string, opts: Intl.DateTimeFormatOptions = { month: 'long', year: 'numeric' }): string {
  return new Date(iso).toLocaleDateString('en-AU', opts)
}

export default async function MemberProfilePage({ params }: Props) {
  const { slug, memberId } = await params

  const [profile, allMembers] = await Promise.all([
    getPublicProfile(memberId) as Promise<PublicProfile | null>,
    getSpaceMembers(slug) as Promise<MemberProfile[]>,
  ])

  if (!profile) notFound()

  const spaceMember = allMembers.find((m) => m.id === memberId)
  const spaceRole   = spaceMember?.space_role ?? 'learner'
  const joinedSpace = spaceMember?.joined_at
  const badge       = roleBadge(spaceRole)
  const tagline     = profile.profile_tagline?.trim() || null

  return (
    <div className="max-w-4xl">

      {/* Back link */}
      <div className="mb-6">
        <Link
          href={`/spaces/${slug}/members`}
          className="text-sm text-slate-400 transition-colors hover:text-teal-600"
        >
          ← Back to members
        </Link>
      </div>

      {/* ── Two-column layout ── */}
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_260px] lg:items-start">

        {/* ── Left: profile content ── */}
        <div className="flex flex-col gap-5">

          {/* Profile hero card */}
          <div
            className="overflow-hidden rounded-2xl px-7 py-8"
            style={{
              background: '#071824',
              border: '1px solid rgba(66,199,198,0.10)',
              boxShadow: '0 4px 24px rgba(7,24,36,0.18), 0 1px 4px rgba(0,0,0,0.10)',
            }}
          >
            <div className="flex flex-col items-center text-center sm:flex-row sm:items-start sm:text-left gap-5">
              <div className="shrink-0">
                <Avatar name={profile.display_name} avatarUrl={profile.avatar_url} size="xl" />
              </div>
              <div className="min-w-0">
                <div className="mb-1 flex flex-wrap items-center justify-center gap-2 sm:justify-start">
                  <h1
                    className="text-2xl font-semibold leading-snug"
                    style={{
                      background: 'linear-gradient(90deg, #55D7D2 0%, #D9FFFD 50%, #FFFFFF 100%)',
                      WebkitBackgroundClip: 'text',
                      WebkitTextFillColor: 'transparent',
                      backgroundClip: 'text',
                    }}
                  >
                    {profile.display_name}
                  </h1>
                  <span
                    className="inline-block rounded-full px-3 py-0.5 text-[11px] font-semibold uppercase tracking-wide"
                    style={{ background: badge.bg, color: badge.color }}
                  >
                    {badge.label}
                  </span>
                </div>

                {tagline && (
                  <p className="mb-2 text-[14px] italic" style={{ color: 'rgba(255,255,255,0.55)' }}>
                    {tagline}
                  </p>
                )}

                <p className="text-[13px]" style={{ color: 'rgba(255,255,255,0.40)' }}>
                  Member since {formatDate(profile.joined_platform)}
                </p>
              </div>
            </div>
          </div>

          {/* About */}
          <div className="overflow-hidden rounded-2xl border border-border bg-white">
            <div className="border-b border-border px-5 py-3">
              <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-400">About</p>
            </div>
            <div className="px-5 py-4">
              {profile.bio ? (
                <p className="text-[15px] leading-[1.8] text-slate-600">{profile.bio}</p>
              ) : (
                <p className="text-[14px] text-slate-400">No bio yet.</p>
              )}
            </div>
          </div>

          {/* Inside this collective */}
          <div className="overflow-hidden rounded-2xl border border-border bg-white">
            <div className="border-b border-border px-5 py-3">
              <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-400">
                Inside this collective
              </p>
            </div>
            <div className="divide-y divide-border">
              <div className="flex items-start gap-4 px-5 py-3">
                <span className="w-24 shrink-0 text-[12px] font-medium text-slate-400">Role</span>
                <span
                  className="rounded-full px-2.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide"
                  style={{ background: badge.bg, color: badge.color }}
                >
                  {badge.label}
                </span>
              </div>
              {joinedSpace && (
                <div className="flex items-start gap-4 px-5 py-3">
                  <span className="w-24 shrink-0 text-[12px] font-medium text-slate-400">Joined</span>
                  <span className="text-[14px] text-navy-900">{formatDate(joinedSpace)}</span>
                </div>
              )}
              <div className="flex items-start gap-4 px-5 py-3">
                <span className="w-24 shrink-0 text-[12px] font-medium text-slate-400">Pathways</span>
                {/* TODO: show pathway progress once per-member pathway access data is available */}
                <span className="text-[14px] text-slate-400">Coming soon.</span>
              </div>
            </div>
          </div>

          {/* Collectives led — creator only */}
          {profile.is_creator && profile.spaces_led.length > 0 && (
            <div className="overflow-hidden rounded-2xl border border-border bg-white">
              <div className="border-b border-border px-5 py-3">
                <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-400">
                  Collectives led
                </p>
              </div>
              <div className="divide-y divide-border">
                {profile.spaces_led.map((name) => (
                  <div key={name} className="px-5 py-3 text-[14px] text-navy-900">{name}</div>
                ))}
              </div>
            </div>
          )}

          {/* Recent contributions placeholder */}
          <div className="overflow-hidden rounded-2xl border border-border bg-white">
            <div className="border-b border-border px-5 py-3">
              <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-400">
                Recent contributions
              </p>
            </div>
            <div className="px-5 py-4">
              {/* TODO: show real contribution history once data is available */}
              <p className="text-[14px] text-slate-400">Contributions coming soon.</p>
            </div>
          </div>

        </div>

        {/* ── Right: sidebar panel ── */}
        {/* TODO: Member profile sidebar content can be expanded later. */}
        <div className="lg:sticky lg:top-6">
          <div
            className="overflow-hidden rounded-2xl border bg-white p-5"
            style={{ borderColor: 'rgba(0,0,0,0.07)', boxShadow: '0 1px 4px rgba(0,0,0,0.04)' }}
          >
            <div
              className="mb-4 h-[2px] w-5 rounded-full"
              style={{ background: 'linear-gradient(90deg, #BF9830 0%, transparent 100%)' }}
            />
            <p className="mb-4 text-[13px] font-semibold uppercase tracking-[0.12em] text-slate-400">
              Member profile
            </p>

            <div className="space-y-4">
              <div>
                <p className="mb-1 text-[14px] font-semibold text-navy-900">Connect</p>
                <p className="text-[13px] leading-relaxed text-slate-500">
                  Messaging and member connection tools can live here later.
                </p>
              </div>
              <div className="h-px" style={{ background: 'rgba(0,0,0,0.06)' }} />
              <div>
                <p className="mb-1 text-[14px] font-semibold text-navy-900">Activity</p>
                <p className="text-[13px] leading-relaxed text-slate-500">
                  Contribution history and participation will appear here.
                </p>
              </div>
              <div className="h-px" style={{ background: 'rgba(0,0,0,0.06)' }} />
              <div>
                <p className="mb-1 text-[14px] font-semibold text-navy-900">Shared spaces</p>
                <p className="text-[13px] leading-relaxed text-slate-500">
                  Collectives and pathways in common can appear here.
                </p>
              </div>
            </div>
          </div>
        </div>

      </div>
    </div>
  )
}
