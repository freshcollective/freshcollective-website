import Link from 'next/link'
import Avatar from '@/components/ui/Avatar'
import type { MemberProfile } from '@/types/platform'

function roleLabel(role: string): string {
  if (role === 'creator') return 'Creator'
  if (role === 'moderator') return 'Moderator'
  return 'Member'
}

function roleBadgeClass(role: string): string {
  if (role === 'creator') return 'bg-teal-100 text-teal-700'
  if (role === 'moderator') return 'bg-navy-100 text-navy-700'
  return 'bg-slate-100 text-slate-500'
}

function formatJoined(isoString: string): string {
  const d = new Date(isoString)
  return d.toLocaleDateString('en-GB', { month: 'short', year: 'numeric' })
}

interface MemberCardProps {
  member: MemberProfile
}

export default function MemberCard({ member }: MemberCardProps) {
  return (
    <Link
      href={`/profile/${member.id}`}
      className="group block rounded-xl border border-border bg-surface px-5 py-5 transition-shadow hover:shadow-[var(--fc-shadow-card)]"
    >
      <div className="flex items-start gap-4">
        <Avatar name={member.display_name} avatarUrl={member.avatar_url} size="md" />
        <div className="flex-1 min-w-0">
          <div className="mb-1 flex flex-wrap items-center gap-2">
            <span className="text-sm font-medium text-navy-800 group-hover:text-teal-700 transition-colors">
              {member.display_name}
            </span>
            {member.space_role !== 'learner' && (
              <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full ${roleBadgeClass(member.space_role)}`}>
                {roleLabel(member.space_role)}
              </span>
            )}
          </div>
          {member.bio && (
            <p className="mb-1 text-xs leading-relaxed text-slate-500 line-clamp-2">{member.bio}</p>
          )}
          <p className="text-[11px] text-slate-400">Joined {formatJoined(member.joined_at)}</p>
        </div>
      </div>
    </Link>
  )
}
