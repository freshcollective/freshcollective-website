import { getMe, getMyMemberships } from '@/lib/serverApi'
import Link from 'next/link'
import type { UserProfile, SpaceMembership } from '@/types/platform'

function formatDate(isoString: string): string {
  return new Date(isoString).toLocaleDateString('en-AU', { month: 'long', year: 'numeric' })
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

export default async function SettingsMembershipPage() {
  const [profile, memberships]: [UserProfile | null, SpaceMembership[]] = await Promise.all([
    getMe(),
    getMyMemberships(),
  ])

  return (
    <div>
      <div className="mb-8">
        <h2 className="mb-1 text-lg font-semibold text-navy-900">Membership</h2>
        <p className="text-sm text-black">Your access and collectives on Fresh Collective.</p>
      </div>

      {/* Account status */}
      <section className="mb-8">
        <p className="mb-3 text-[11px] font-semibold uppercase tracking-[0.12em] text-black">
          Account
        </p>
        <div
          className="overflow-hidden rounded-2xl border border-border bg-white px-6 py-5"
          style={{ boxShadow: '0 1px 4px rgba(0,0,0,0.04)' }}
        >
          <div className="flex items-center justify-between">
            <div>
              <p className="text-[14px] font-medium text-navy-800">{profile?.email}</p>
              <p className="mt-0.5 text-[12px] text-black capitalize">{profile?.role} account</p>
            </div>
            <span className="text-[11px] font-semibold px-2.5 py-1 rounded-full bg-teal-50 text-teal-700 border border-teal-200">
              Active
            </span>
          </div>
        </div>
      </section>

      {/* Collectives */}
      <section className="mb-8">
        <p className="mb-3 text-[11px] font-semibold uppercase tracking-[0.12em] text-black">
          Collectives
        </p>
        {memberships.length > 0 ? (
          <div className="flex flex-col gap-3">
            {memberships.map((m) => (
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
                <RolePill role={m.role} />
              </div>
            ))}
          </div>
        ) : (
          <div
            className="overflow-hidden rounded-2xl border border-border bg-white px-6 py-10 text-center"
            style={{ boxShadow: '0 1px 4px rgba(0,0,0,0.04)' }}
          >
            <p className="text-[14px] font-medium text-navy-800">Your memberships</p>
            <p className="mt-1 text-[13px] text-black">
              Collectives and membership details will appear here.
            </p>
          </div>
        )}
      </section>

      {/* Subscription placeholder */}
      <section>
        <p className="mb-3 text-[11px] font-semibold uppercase tracking-[0.12em] text-black">
          Subscription
        </p>
        <div className="overflow-hidden rounded-2xl border border-dashed border-border bg-white px-6 py-8 text-center">
          <p className="text-[14px] text-black">
            Subscription management coming soon.
          </p>
          <p className="mt-1 text-[12px] text-black">
            Billing and plan details will appear here once Stripe is connected.
          </p>
        </div>
      </section>
    </div>
  )
}
