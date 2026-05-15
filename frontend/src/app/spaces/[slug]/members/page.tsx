import { getSpaceMembers } from '@/lib/serverApi'
import MemberCard from '@/components/spaces/MemberCard'
import type { MemberProfile } from '@/types/platform'

interface Props {
  params: Promise<{ slug: string }>
}

export default async function SpaceMembersPage({ params }: Props) {
  const { slug } = await params
  const members: MemberProfile[] = await getSpaceMembers(slug)

  const leaders = members.filter((m) => m.space_role === 'creator' || m.space_role === 'moderator')
  const learners = members.filter((m) => m.space_role === 'learner')

  return (
    <div className="max-w-2xl">
      <div
        className="mb-8 overflow-hidden rounded-2xl px-7 py-7"
        style={{
          background:
            'radial-gradient(circle at 85% 15%, rgba(56,160,158,0.18), transparent 50%), ' +
            'radial-gradient(rgba(56,160,158,0.06) 1px, transparent 1px), ' +
            'linear-gradient(135deg, #EAF8F7 0%, #F0FBFA 60%, #FAFAF8 100%)',
          backgroundSize: 'auto, 20px 20px, auto',
          border: '1px solid rgba(56,160,158,0.14)',
        }}
      >
        <div className="mb-2 h-[2px] w-8 rounded-full" style={{ background: 'linear-gradient(90deg, #E7C65A 0%, transparent 100%)' }} />
        <h1 className="mb-1.5 font-serif text-2xl text-navy-900">Members</h1>
        <p className="text-[14px] text-slate-500">
          The people in this space — here to learn, reflect, and grow together.
        </p>
      </div>

      {leaders.length > 0 && (
        <section className="mb-10">
          <h2 className="mb-4 text-xs font-semibold uppercase tracking-wider text-slate-400">
            Creators & Moderators
          </h2>
          <div className="flex flex-col gap-3">
            {leaders.map((m) => (
              <MemberCard key={m.id} member={m} />
            ))}
          </div>
        </section>
      )}

      <section>
        <h2 className="mb-4 text-xs font-semibold uppercase tracking-wider text-slate-400">
          {learners.length > 0 ? `${learners.length} Member${learners.length === 1 ? '' : 's'}` : 'Members'}
        </h2>
        {learners.length > 0 ? (
          <div className="flex flex-col gap-3">
            {learners.map((m) => (
              <MemberCard key={m.id} member={m} />
            ))}
          </div>
        ) : (
          <div className="rounded-2xl border border-teal-100 bg-white px-6 py-8 text-center">
            <p className="text-sm text-slate-400">No members yet — be the first to join.</p>
          </div>
        )}
      </section>
    </div>
  )
}
