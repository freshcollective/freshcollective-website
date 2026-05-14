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

      {/* No collective yet */}
      {!primarySpace && (
        <div className="rounded-xl border border-dashed border-slate-200 bg-white p-8 text-center">
          <p className="mb-1.5 font-serif text-base text-navy-900">No collective yet</p>
          <p className="mb-5 text-sm text-slate-400">
            Set up your collective first to access its settings.
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
        <div className="space-y-4">

          {/* Collective details */}
          <div className="rounded-xl border border-border bg-white p-6">
            <div className="mb-4 flex items-center justify-between">
              <h2 className="font-serif text-base text-navy-900">Collective details</h2>
              <Link
                href={`/creator/spaces/${primarySpace.slug}`}
                className="text-[12px] font-medium text-teal-600 transition-colors hover:text-teal-700"
              >
                Edit →
              </Link>
            </div>
            <dl className="space-y-3.5">
              {[
                { label: 'Name',        value: spaceDetail?.name ?? primarySpace.name },
                { label: 'Tagline',     value: spaceDetail?.tagline ?? primarySpace.tagline ?? '—' },
                { label: 'Status',      value: primarySpace.status },
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

          {/* Visibility */}
          <div className="rounded-xl border border-border bg-white p-6">
            <div className="mb-4 flex items-center justify-between">
              <h2 className="font-serif text-base text-navy-900">Visibility</h2>
              <Link
                href={`/creator/spaces/${primarySpace.slug}`}
                className="text-[12px] font-medium text-teal-600 transition-colors hover:text-teal-700"
              >
                Edit →
              </Link>
            </div>
            <div className="flex items-start gap-6">
              <dt
                className="w-20 shrink-0 text-[12px] font-medium"
                style={{ color: 'rgba(0,0,0,0.38)', paddingTop: '1px' }}
              >
                Access
              </dt>
              <dd className="text-[13.5px] text-navy-900">
                {spaceDetail?.is_public ? 'Public — anyone can find and join' : 'Private — invite only'}
              </dd>
            </div>
          </div>

          {/* Pricing / access */}
          <div className="rounded-xl border border-border bg-white p-6">
            <div className="mb-4 flex items-center justify-between">
              <h2 className="font-serif text-base text-navy-900">Pricing &amp; access</h2>
              {/* TODO: link to Stripe configuration when billing is wired up */}
            </div>
            <div
              className="rounded-lg px-5 py-4"
              style={{ background: 'rgba(56,160,158,0.07)', border: '1px solid rgba(56,160,158,0.18)' }}
            >
              <p
                className="mb-1 text-[10.5px] font-bold uppercase tracking-[0.16em]"
                style={{ color: '#38A09E' }}
              >
                Founding creator access
              </p>
              <p className="text-[15px] font-semibold text-navy-900">14-day free trial</p>
              <p className="mt-0.5 text-[13px] text-slate-500">
                then <span className="font-medium text-navy-900">$19/month</span>
              </p>
            </div>
            <p className="mt-3 text-[12px] text-slate-400">
              Member pricing and Stripe billing configuration coming soon.
            </p>
          </div>

          {/* Creator profile */}
          <div className="rounded-xl border border-border bg-white p-6">
            <div className="mb-4 flex items-center justify-between">
              <h2 className="font-serif text-base text-navy-900">Creator profile</h2>
              <Link
                href="/settings/profile"
                className="text-[12px] font-medium text-teal-600 transition-colors hover:text-teal-700"
              >
                Edit →
              </Link>
            </div>
            <p className="text-[13.5px] text-slate-400">
              Your public profile is visible to members in your collective. Keep it current so
              people know who is leading the work.
            </p>
          </div>

        </div>
      )}

    </div>
  )
}
