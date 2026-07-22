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
    </div>
  )
}
