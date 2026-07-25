import { redirect } from 'next/navigation'
import { getMe, getCreatorBilling } from '@/lib/serverApi'
import type { CreatorBillingResponse } from '@/types/platform'
import AccountTabbedShell from './AccountTabbedShell'

/**
 * Account — the creator's own home in Creator Studio.
 *
 * A creator may tend multiple collectives, but they have one Fresh
 * Collective account. Anything that belongs to the person (not to
 * whichever collective they happen to be tending right now) lives
 * here: their public profile, subscription plan, billing history,
 * and account-level security settings.
 */

interface Profile { id: string; email: string; name: string | null; role: string }

export default async function AccountPage() {
  const [profile, billing]: [Profile | null, CreatorBillingResponse | null] = await Promise.all([
    getMe() as Promise<Profile | null>,
    getCreatorBilling(),
  ])

  if (!profile) {
    redirect('/login?next=/creator-studio/account')
  }

  return (
    <div className="w-full max-w-[1180px] px-8 py-8 md:px-10 md:py-10">

      {/* Page header — this belongs to the creator, not to a
          collective, so no collective-name eyebrow. */}
      <div className="mb-8">
        <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500">
          Account
        </p>
        <h1 className="font-serif text-2xl text-navy-900 md:text-3xl">
          {profile.name ?? profile.email}
        </h1>
        <p
          className="mt-2 max-w-xl text-[14.5px] leading-relaxed italic"
          style={{ color: 'rgba(12, 24, 38, 0.65)', fontFamily: 'Georgia, serif' }}
        >
          Your Fresh Collective profile, subscription, and account settings — the pieces of Creator Studio that belong to you across every collective you tend.
        </p>
      </div>

      <AccountTabbedShell user={profile} billing={billing} />

    </div>
  )
}
