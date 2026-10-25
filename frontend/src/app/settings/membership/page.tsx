import {
  getMe, getMyMemberships, getRetainedReservations,
} from '@/lib/serverApi'
import CollectivesList from './CollectivesList'
import RetainedReservations from './RetainedReservations'
import type {
  UserProfile, SpaceMembership, RetainedReservation,
} from '@/types/platform'

export default async function SettingsMembershipPage() {
  const [profile, memberships, reservations]: [
    UserProfile | null,
    SpaceMembership[],
    RetainedReservation[],
  ] = await Promise.all([
    getMe(),
    getMyMemberships(),
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
