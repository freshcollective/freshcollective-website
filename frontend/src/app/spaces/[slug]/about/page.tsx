import { getSpace } from '@/lib/serverApi'
import { notFound } from 'next/navigation'

interface Props {
  params: Promise<{ slug: string }>
}

export default async function SpaceAboutPage({ params }: Props) {
  const { slug } = await params
  const space = await getSpace(slug)
  if (!space) notFound()

  return (
    <div className="max-w-2xl">

      {/* Header */}
      <div
        className="mb-8 overflow-hidden rounded-2xl px-7 py-8"
        style={{
          background:
            'radial-gradient(rgba(66,199,198,0.07) 1px, transparent 1px), ' +
            'radial-gradient(ellipse at 80% 20%, rgba(66,199,198,0.22), transparent 45%), ' +
            'linear-gradient(135deg, #071824 0%, #073B3A 55%, #0F5E5C 100%)',
          backgroundSize: '22px 22px, auto, auto',
        }}
      >
        <div
          className="mb-3 h-[2px] w-8 rounded-full"
          style={{ background: 'linear-gradient(90deg, #E7C65A 0%, transparent 100%)' }}
        />
        <h2 className="font-serif text-2xl" style={{ color: '#FFFFFF' }}>About</h2>
        <p className="mt-1 text-[15px] font-semibold" style={{ color: 'rgba(255,255,255,0.90)' }}>
          {space.name}
        </p>
        {space.tagline && (
          <p className="mt-2 text-[14px] leading-relaxed" style={{ color: 'rgba(255,255,255,0.65)' }}>
            {space.tagline}
          </p>
        )}
      </div>

      {/* Description */}
      {space.description ? (
        <div
          className="rounded-2xl bg-white px-7 py-8"
          style={{ border: '1px solid rgba(0,0,0,0.07)', boxShadow: '0 1px 4px rgba(0,0,0,0.04)' }}
        >
          <div
            className="prose prose-slate max-w-none text-[15px] leading-relaxed text-slate-700"
            style={{ whiteSpace: 'pre-wrap' }}
          >
            {space.description}
          </div>
        </div>
      ) : (
        <div
          className="rounded-2xl bg-white px-7 py-12 text-center"
          style={{ border: '1px solid rgba(0,0,0,0.07)' }}
        >
          <p className="font-serif text-lg text-navy-800">More coming soon.</p>
          <p className="mt-2 text-[14px] text-slate-400">
            The collective description will appear here once it has been added.
          </p>
        </div>
      )}

    </div>
  )
}
