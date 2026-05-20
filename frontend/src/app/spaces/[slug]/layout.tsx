import { notFound } from 'next/navigation'
import Link from 'next/link'
import SpaceNav from '@/components/spaces/SpaceNav'
import CollectiveSwitcher from '@/components/spaces/CollectiveSwitcher'
import { getSpace, getMe, getMyMemberships } from '@/lib/serverApi'
import { resolveMediaUrl } from '@/lib/api'
import type { SpaceMembership, UserProfile } from '@/types/platform'

interface Props {
  children: React.ReactNode
  params: Promise<{ slug: string }>
}

export default async function SpaceLayout({ children, params }: Props) {
  const { slug } = await params

  const [space, user, memberships]: [
    Awaited<ReturnType<typeof getSpace>>,
    UserProfile | null,
    SpaceMembership[],
  ] = await Promise.all([getSpace(slug), getMe(), getMyMemberships()])

  if (!space) notFound()

  const spaceCoverUrl = resolveMediaUrl(space.cover_image_url)
  const isMember = memberships.some((m) => m.space_slug === slug)

  return (
    <div className="flex min-h-screen flex-col" style={{ background: '#FAFAF8' }}>

      {/* ── Top navigation bar ── */}
      <header className="border-b border-border bg-surface py-3.5" style={{ borderTop: '2px solid #38A09E' }}>
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 md:px-10">
          <CollectiveSwitcher
            memberships={memberships}
            currentSlug={slug}
            currentName={space.name}
            userRole={user?.role ?? 'learner'}
          />
          <div className="flex items-center gap-4">
            <Link href="/settings" className="text-sm text-slate-500 transition-colors hover:text-navy-700">
              Settings
            </Link>
            <Link href="/dashboard" className="text-sm text-slate-500 transition-colors hover:text-navy-700">
              ← Dashboard
            </Link>
          </div>
        </div>
      </header>

      {/* ── Collective identity band ── */}
      <div
        className="relative overflow-hidden px-6 py-10 md:px-10 md:py-14"
        style={{
          background:
            'radial-gradient(rgba(66,199,198,0.07) 1px, transparent 1px), ' +
            'radial-gradient(ellipse at 78% 20%, rgba(66,199,198,0.38), transparent 48%), ' +
            'radial-gradient(ellipse at 10% 80%, rgba(56,160,158,0.22), transparent 42%), ' +
            'linear-gradient(135deg, #071824 0%, #092030 40%, #073B3A 100%)',
          backgroundSize: '22px 22px, auto, auto, auto',
          boxShadow: '0 8px 40px rgba(7,24,36,0.28)',
        }}
      >
        {/* Uploaded banner image */}
        {spaceCoverUrl && (
          <>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={spaceCoverUrl}
              alt=""
              aria-hidden="true"
              className="absolute inset-0 h-full w-full object-cover"
            />
            {/* Scrim — slightly deeper on left so text is always readable */}
            <div
              className="absolute inset-0"
              style={{
                background:
                  'linear-gradient(105deg, rgba(7,24,36,0.82) 0%, rgba(7,42,50,0.60) 55%, rgba(7,59,58,0.50) 100%)',
              }}
            />
          </>
        )}

        {/* Text — layered above image/scrim */}
        <div className="relative mx-auto max-w-6xl">
          {/* Soft gold accent line */}
          <div
            className="mb-4 h-[2px] w-8 rounded-full"
            style={{ background: 'linear-gradient(90deg, #E7C65A 0%, transparent 100%)' }}
          />
          <h1
            className="font-serif text-3xl md:text-4xl"
            style={spaceCoverUrl ? { color: '#FFFFFF' } : {
              background: 'linear-gradient(120deg, #55D7D2 0%, #FFFFFF 55%)',
              WebkitBackgroundClip: 'text',
              WebkitTextFillColor: 'transparent',
              backgroundClip: 'text',
            }}
          >
            {space.name}
          </h1>
          {space.tagline && (
            <p className="mt-2 text-[14px]" style={{ color: 'rgba(255,255,255,0.68)' }}>
              {space.tagline}
            </p>
          )}
        </div>
      </div>

      <SpaceNav spaceSlug={slug} spaceName={space.name} isMember={isMember} />

      <main className="flex-1 py-10 pb-24 md:pb-10">
        <div className="mx-auto max-w-6xl px-6 md:px-10">
          {children}
        </div>
      </main>
    </div>
  )
}
