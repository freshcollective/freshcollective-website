import { getMe } from '@/lib/serverApi'
import ProfileForm from '@/components/settings/ProfileForm'
import type { UserProfile } from '@/types/platform'

export default async function SettingsProfilePage() {
  const profile: UserProfile | null = await getMe()

  return (
    <div>
      <div className="mb-8">
        <h2 className="mb-1 font-serif text-xl text-navy-900">Profile</h2>
        <p className="text-sm text-slate-500">
          How you appear to others in the community.
        </p>
      </div>

      {profile ? (
        <ProfileForm profile={profile} />
      ) : (
        <p className="text-sm text-slate-400">Unable to load profile.</p>
      )}
    </div>
  )
}
