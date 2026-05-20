import { notFound } from 'next/navigation'
import { getPublicProfile } from '@/lib/serverApi'
import Avatar from '@/components/ui/Avatar'
import type { PublicProfile } from '@/types/platform'

interface Props {
  params: Promise<{ userId: string }>
}

function formatJoined(isoString: string): string {
  const d = new Date(isoString)
  return d.toLocaleDateString('en-GB', { month: 'long', year: 'numeric' })
}

export default async function PublicProfilePage({ params }: Props) {
  const { userId } = await params
  const profile: PublicProfile | null = await getPublicProfile(userId)

  if (!profile) notFound()

  return (
    <div className="mx-auto max-w-xl py-12 px-4">
      <div className="flex flex-col items-center text-center">
        <Avatar name={profile.display_name} avatarUrl={profile.avatar_url} size="xl" />

        <div className="mt-5">
          <div className="flex items-center justify-center gap-2">
            <h1 className="font-serif text-2xl text-navy-900">{profile.display_name}</h1>
            {profile.is_creator && (
              <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-teal-100 text-teal-700">
                Creator
              </span>
            )}
          </div>
          <p className="mt-1 text-xs text-slate-400">Member since {formatJoined(profile.joined_platform)}</p>
        </div>

        {profile.bio && (
          <p className="mt-5 max-w-sm text-sm leading-relaxed text-slate-600">{profile.bio}</p>
        )}

        {profile.spaces_led.length > 0 && (
          <div className="mt-8 w-full text-left">
            <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-slate-400">
              Collectives Led
            </h2>
            <div className="flex flex-col gap-2">
              {profile.spaces_led.map((name) => (
                <div
                  key={name}
                  className="rounded-lg border border-border bg-surface px-4 py-3 text-sm text-navy-800"
                >
                  {name}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
