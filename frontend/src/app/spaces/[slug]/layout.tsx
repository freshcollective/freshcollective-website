import { notFound } from 'next/navigation'
import Link from 'next/link'
import SpaceNav from '@/components/spaces/SpaceNav'
import { getSpace } from '@/lib/serverApi'

interface Props {
  children: React.ReactNode
  params: Promise<{ slug: string }>
}

export default async function SpaceLayout({ children, params }: Props) {
  const { slug } = await params
  const space = await getSpace(slug)

  if (!space) notFound()

  return (
    <div className="flex min-h-screen flex-col bg-background">

      {/* ── Deep teal collective header (nav + identity banner) ── */}
      <div style={{ background: 'linear-gradient(180deg, #073B3A 0%, #0F5E5C 100%)' }}>

        {/* Top nav row */}
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-3.5 md:px-10">
          <Link
            href="/dashboard"
            className="font-serif text-lg text-white transition-opacity hover:opacity-75"
          >
            Fresh Collective
          </Link>
          <div className="flex items-center gap-4">
            <Link
              href="/settings"
              className="text-sm transition-colors hover:text-white"
              style={{ color: 'rgba(255,255,255,0.65)' }}
            >
              Settings
            </Link>
            <Link
              href="/dashboard"
              className="text-sm transition-colors hover:text-white"
              style={{ color: 'rgba(255,255,255,0.65)' }}
            >
              ← Dashboard
            </Link>
          </div>
        </div>

        {/* Collective identity band */}
        <div
          className="mx-auto max-w-6xl px-6 pb-8 pt-5 md:px-10"
          style={{ borderTop: '1px solid rgba(255,255,255,0.10)' }}
        >
          <div
            className="mb-3 h-[2px] w-8"
            style={{ background: 'rgba(255,255,255,0.35)' }}
          />
          <h1 className="font-serif text-3xl text-white md:text-4xl">{space.name}</h1>
          {space.tagline && (
            <p className="mt-1.5 text-[14px]" style={{ color: 'rgba(255,255,255,0.72)' }}>
              {space.tagline}
            </p>
          )}
        </div>
      </div>

      <SpaceNav spaceSlug={slug} />

      <main className="flex-1 py-10 pb-24 md:pb-10">
        <div className="mx-auto max-w-6xl px-6 md:px-10">
          {children}
        </div>
      </main>
    </div>
  )
}
