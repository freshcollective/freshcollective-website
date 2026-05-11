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
      <div className="mb-8">
        <h1 className="mb-2 font-serif text-2xl text-navy-900">Members</h1>
        <p className="text-sm text-slate-500">
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
          <div className="rounded-xl border border-border bg-surface px-6 py-8 text-center">
            <p className="text-sm text-slate-400">No members yet — be the first to join.</p>
          </div>
        )}
      </section>
    </div>
  )
}
