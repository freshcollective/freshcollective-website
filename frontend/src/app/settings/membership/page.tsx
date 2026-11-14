import {
  getMe, getMyMemberships, getMyMembershipSubscriptions,
  getRetainedReservations,
} from '@/lib/serverApi'
import CollectivesList from './CollectivesList'
import MembershipSubscriptions from './MembershipSubscriptions'
import RetainedReservations from './RetainedReservations'
import type {
  UserProfile, SpaceMembership, RetainedReservation, MembershipState,
} from '@/types/platform'

export default async function SettingsMembershipPage() {
  const [profile, memberships, subscriptions, reservations]: [
    UserProfile | null,
    SpaceMembership[],
    MembershipState[],
    RetainedReservation[],
  ] = await Promise.all([
    getMe(),
    getMyMemberships(),
    getMyMembershipSubscriptions(),
    getRetainedReservations(),
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
        <CollectivesList memberships={memberships} />
      </section>

      {/* Paid reservations kept after leaving. Renders nothing when
          there are none, which is the usual case. */}
      <RetainedReservations reservations={reservations} />

      {/* Paid memberships. Rendered only when there are any — a
          member of nothing but free Collectives should not be shown
          an empty billing section they will never use. */}
      {subscriptions.length > 0 && (
        <section>
          <p className="mb-3 text-[11px] font-semibold uppercase tracking-[0.12em] text-black">
            Paid memberships
          </p>
          <MembershipSubscriptions rows={subscriptions} />
        </section>
      )}
    </div>
  )
}
