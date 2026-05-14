import Link from 'next/link'
import { getCreatorSpaces, getCreatorSpace } from '@/lib/serverApi'

export default async function SettingsPage() {
  const spaces = await getCreatorSpaces()
  const primarySpace = spaces[0] ?? null
  const spaceDetail = primarySpace ? await getCreatorSpace(primarySpace.slug) : null

  return (
    <div className="max-w-3xl px-8 py-8 md:px-10 md:py-10">

      <div className="mb-8">
        <p
          className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.16em]"
          style={{ color: '#38A09E' }}
        >
          Creator Studio
        </p>
        <h1 className="font-serif text-2xl text-navy-900 md:text-3xl">Settings</h1>
      </div>

      {!primarySpace && (
        <div className="rounded-xl border border-dashed border-slate-200 bg-white p-8 text-center">
          <p className="mb-4 text-sm text-slate-400">
            Set up your space first to access settings.
          </p>
          <Link
            href="/creator"
            className="inline-flex items-center rounded-lg px-5 py-2.5 text-sm font-semibold text-white transition-opacity hover:opacity-90"
            style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
          >
            Go to creator area
          </Link>
        </div>
      )}

      {primarySpace && (
        <>
          <div className="mb-4 rounded-xl border border-border bg-white p-6">
            <h2 className="mb-5 font-serif text-base text-navy-900">Space settings</h2>
            <dl className="space-y-4">
              {[
                { label: 'Name', value: spaceDetail?.name ?? primarySpace.name },
                {
                  label: 'Tagline',
                  value: spaceDetail?.tagline ?? primarySpace.tagline ?? '—',
                },
                { label: 'Status', value: primarySpace.status },
                {
                  label: 'Visibility',
                  value: spaceDetail?.is_public ? 'Public' : 'Private',
                },
              ].map(({ label, value }) => (
                <div key={label} className="flex items-start gap-6">
                  <dt
                    className="w-20 shrink-0 text-[12px] font-medium"
                    style={{ color: 'rgba(0,0,0,0.38)', paddingTop: '1px' }}
                  >
                    {label}
                  </dt>
                  <dd className="text-[13.5px] text-navy-900">{value}</dd>
                </div>
              ))}
            </dl>
          </div>

          <Link
            href={`/creator/spaces/${primarySpace.slug}`}
            className="inline-flex items-center rounded-lg border border-border bg-white px-5 py-3 text-[13px] font-medium text-slate-600 transition-colors hover:border-teal-200 hover:text-teal-700"
          >
            Edit space settings →
          </Link>
        </>
      )}

    </div>
  )
}
