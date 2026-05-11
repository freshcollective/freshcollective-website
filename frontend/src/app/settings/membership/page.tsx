import { getMe, getMyMemberships } from '@/lib/serverApi'
import type { UserProfile, SpaceMembership } from '@/types/platform'

function formatDate(isoString: string): string {
  const d = new Date(isoString)
  return d.toLocaleDateString('en-GB', { month: 'long', year: 'numeric' })
}

function RolePill({ role }: { role: string }) {
  const map: Record<string, string> = {
    creator: 'bg-teal-100 text-teal-700',
    moderator: 'bg-navy-100 text-navy-700',
    learner: 'bg-slate-100 text-slate-500',
  }
  const label: Record<string, string> = {
    creator: 'Creator',
    moderator: 'Moderator',
    learner: 'Member',
  }
  return (
    <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full ${map[role] ?? 'bg-slate-100 text-slate-500'}`}>
      {label[role] ?? role}
    </span>
  )
}

export default async function SettingsMembershipPage() {
  const [profile, memberships]: [UserProfile | null, SpaceMembership[]] = await Promise.all([
    getMe(),
    getMyMemberships(),
  ])

  return (
    <div>
      <div className="mb-8">
        <h2 className="mb-1 font-serif text-xl text-navy-900">Membership</h2>
        <p className="text-sm text-slate-500">
          Your access and spaces on Fresh Collective.
        </p>
      </div>

      {/* Account status */}
      <section className="mb-8">
        <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-slate-400">
          Account
        </h3>
        <div className="rounded-xl border border-border bg-surface px-6 py-5">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-navy-800">{profile?.email}</p>
              <p className="mt-0.5 text-xs text-slate-400 capitalize">{profile?.role} account</p>
            </div>
            <span className="text-xs font-semibold px-2.5 py-1 rounded-full bg-teal-50 text-teal-700 border border-teal-200">
              Active
            </span>
          </div>
        </div>
      </section>

      {/* Spaces */}
      <section className="mb-8">
        <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-slate-400">
          Spaces
        </h3>
        {memberships.length > 0 ? (
          <div className="flex flex-col gap-3">
            {memberships.map((m) => (
              <div
                key={m.space_id}
                className="flex items-center justify-between rounded-xl border border-border bg-surface px-6 py-4"
              >
                <div>
                  <p className="text-sm font-medium text-navy-800">{m.space_name}</p>
                  <p className="mt-0.5 text-xs text-slate-400">Joined {formatDate(m.joined_at)}</p>
                </div>
                <RolePill role={m.role} />
              </div>
            ))}
          </div>
        ) : (
          <div className="rounded-xl border border-border bg-surface px-6 py-8 text-center">
            <p className="text-sm text-slate-400">You are not a member of any spaces yet.</p>
          </div>
        )}
      </section>

      {/* Stripe placeholder */}
      <section>
        <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-slate-400">
          Subscription
        </h3>
        <div className="rounded-xl border border-dashed border-border bg-surface px-6 py-6 text-center">
          <p className="text-sm text-slate-400">
            Subscription management is coming soon.
          </p>
          <p className="mt-1 text-xs text-slate-300">
            Billing and plan details will appear here once Stripe is connected.
          </p>
        </div>
      </section>
    </div>
  )
}
