import Link from 'next/link'
import Avatar from '@/components/ui/Avatar'
import type { MemberProfile } from '@/types/platform'

function roleLabel(role: string): string {
  if (role === 'creator') return 'Creator'
  if (role === 'moderator') return 'Moderator'
  return 'Member'
}

function roleBadgeClass(role: string): string {
  if (role === 'creator') return 'bg-[color:var(--fc-accent-soft,rgba(56,160,158,0.10))] text-[color:var(--fc-accent,#0f766e)]'
  if (role === 'moderator') return 'bg-navy-100 text-navy-700'
  return 'bg-slate-100 text-slate-500'
}

function formatJoined(isoString: string): string {
  const d = new Date(isoString)
  return d.toLocaleDateString('en-AU', { month: 'short', year: 'numeric' })
}

interface MemberCardProps {
  member: MemberProfile
  spaceSlug: string
}

export default function MemberCard({ member, spaceSlug }: MemberCardProps) {
  const tagline = member.profile_tagline?.trim() || null
  return (
    <Link
      href={`/spaces/${spaceSlug}/members/${member.id}`}
      className="group block rounded-2xl border border-border bg-white px-5 py-5 transition-all hover:-translate-y-0.5 hover:border-[color:var(--fc-accent-line,rgba(56,160,158,0.30))] hover:shadow-sm"
    >
      <div className="flex items-start gap-4">
        <Avatar name={member.display_name} avatarUrl={member.avatar_url} size="md" />
        <div className="flex-1 min-w-0">
          <div className="mb-0.5 flex flex-wrap items-center gap-2">
            <span className="text-sm font-medium text-navy-800 group-hover:text-[color:var(--fc-accent,#0f766e)] transition-colors">
              {member.display_name}
            </span>
            {member.space_role !== 'learner' && (
              <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full ${roleBadgeClass(member.space_role)}`}>
                {roleLabel(member.space_role)}
              </span>
            )}
          </div>
          {tagline && (
            <p className="mb-1 text-[12px] text-black italic">{tagline}</p>
          )}
          {member.bio && (
            <p className="mb-1 text-xs leading-relaxed text-black line-clamp-2">{member.bio}</p>
          )}
          <p className="text-[11px] text-black">Joined {formatJoined(member.joined_at)}</p>
        </div>
      </div>
    </Link>
  )
}
