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

      {/* ── Top navigation bar ── */}
      <header className="border-b border-border bg-surface py-3.5" style={{ borderTop: '2px solid #38A09E' }}>
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 md:px-10">
          <Link href="/dashboard" className="font-serif text-lg text-navy-900 transition-colors hover:text-teal-600">
            Fresh Collective
          </Link>
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

      {/* ── Collective identity banner — light aqua with subtle dot texture ── */}
      <div
        className="border-b border-teal-100 px-6 py-8 md:px-10"
        style={{
          background:
            'radial-gradient(rgba(56,160,158,0.10) 1px, transparent 1px), ' +
            'radial-gradient(circle at 85% 30%, rgba(66,199,198,0.18), transparent 40%), ' +
            'linear-gradient(135deg, #EAF8F7 0%, #F5FCFB 55%, #FAFAF8 100%)',
          backgroundSize: '22px 22px, 100% 100%, 100% 100%',
        }}
      >
        <div className="mx-auto max-w-6xl">
          <div className="mb-3 h-[2px] w-8 rounded-full bg-teal-400" />
          <h1 className="font-serif text-3xl text-navy-900 md:text-4xl">{space.name}</h1>
          {space.tagline && (
            <p className="mt-1.5 text-[14px] text-slate-500">{space.tagline}</p>
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
