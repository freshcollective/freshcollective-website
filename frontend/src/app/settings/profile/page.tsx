import Link from 'next/link'
import { getMe } from '@/lib/serverApi'
import ProfileForm from '@/components/settings/ProfileForm'
import type { UserProfile } from '@/types/platform'

export default async function SettingsProfilePage() {
  const profile: UserProfile | null = await getMe()

  return (
    <div>
      <div className="mb-8">
        <h2 className="mb-1 text-lg font-semibold text-navy-900">Profile</h2>
        <p className="text-sm text-black">How you appear to others in the community.</p>
      </div>

      {profile ? (
        <ProfileForm profile={profile} />
      ) : (
        <p className="text-sm text-black">Unable to load profile.</p>
      )}

      {profile && (
        <section
          className="mt-12 border-t pt-10"
          style={{ borderColor: 'rgba(12, 24, 38, 0.08)' }}
        >
          <h3 className="text-base font-semibold text-navy-900">
            Introduction to Fresh Collective
          </h3>
          <p className="mt-1 max-w-[520px] text-sm leading-relaxed text-black">
            The short introduction stays available if you&rsquo;d ever like
            a refresher on how Fresh Collective works.
          </p>
          <Link
            href="/onboarding?revisit=1"
            className="mt-5 inline-flex items-center gap-1.5 rounded-full border px-5 py-2.5 text-[13px] font-medium text-navy-800 transition-colors hover:border-teal-300 hover:text-teal-700"
            style={{ borderColor: 'rgba(12, 24, 38, 0.14)' }}
          >
            Revisit the Introduction
            <span aria-hidden="true">→</span>
          </Link>
        </section>
      )}
    </div>
  )
}
