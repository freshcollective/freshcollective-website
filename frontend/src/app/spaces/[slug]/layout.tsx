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
      <header
        className="border-b border-border py-3.5"
        style={{
          background: 'linear-gradient(135deg, #0d2533 0%, #173d50 55%, #10303e 100%)',
          borderTop: '2px solid var(--color-gold-500)',
        }}
      >
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 md:px-10">
          <Link href="/dashboard" className="font-serif text-lg text-white/90 transition-opacity hover:opacity-75">
            Fresh Collective
          </Link>
          <div className="flex items-center gap-4">
            <Link href="/settings" className="text-sm text-white/45 transition-colors hover:text-white/75">
              Settings
            </Link>
            <Link href="/dashboard" className="text-sm text-white/55 transition-colors hover:text-white/80">
              ← Dashboard
            </Link>
          </div>
        </div>
      </header>

      <div
        className="border-b border-white/10 px-6 py-8 md:px-10"
        style={{
          background: 'linear-gradient(135deg, #0d2533 0%, #173d50 55%, #10303e 100%)',
        }}
      >
        <div className="mx-auto max-w-6xl">
          <div
            className="mb-3 h-[2px] w-8"
            style={{ background: 'linear-gradient(90deg, #C9A83C 0%, transparent 100%)' }}
          />
          <h1 className="font-serif text-3xl text-white md:text-4xl">{space.name}</h1>
          {space.tagline && (
            <p className="mt-1.5 text-[14px]" style={{ color: 'rgba(255,255,255,0.50)' }}>{space.tagline}</p>
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
