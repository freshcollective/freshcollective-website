import Link from 'next/link'

/**
 * Inline upgrade notice for creators on Community when they navigate
 * directly to ``/creator-studio/offers`` (or an editor URL) — the
 * sidebar hides the entry, so a direct URL is the only way to arrive
 * here on that plan. Keeps the surface calm rather than showing a
 * 403 or a "broken" empty state.
 *
 * Reused by the index page and by the editor's server component so
 * the language stays consistent.
 */
export default function UpgradeNotice() {
  return (
    <>
      <div className="mb-8">
        <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500">
          Creator Studio
        </p>
        <h1 className="font-serif text-2xl text-navy-900 md:text-3xl">Offer Pages</h1>
        <p className="mt-2 max-w-2xl text-[15px] leading-relaxed text-black">
          Offer Pages let you share a beautiful, focused page for anything
          you offer — a pathway, a gathering, a program — without needing
          a separate website.
        </p>
      </div>

      <div
        className="rounded-2xl border p-6 md:p-8"
        style={{
          background: 'rgba(56,160,158,0.05)',
          borderColor: 'rgba(56,160,158,0.24)',
        }}
      >
        <p
          className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.16em]"
          style={{ color: '#0f766e' }}
        >
          Included on Creator
        </p>
        <h2 className="mb-2 font-serif text-[22px] leading-snug text-navy-900">
          Available when you begin creating commercially
        </h2>
        <p className="mb-5 max-w-2xl text-[14.5px] leading-relaxed text-black">
          The Community plan is designed for non-commercial collectives, so
          Offer Pages aren&rsquo;t part of it. Upgrade to Creator to
          publish paid offers, share Offer Pages, and unlock the wider
          commercial toolset.
        </p>
        <div className="flex flex-wrap items-center gap-3">
          <Link
            href="/creator-studio/billing"
            className="inline-flex items-center rounded-xl px-5 py-2.5 text-[14px] font-semibold text-white transition-opacity hover:opacity-90"
            style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
          >
            View plans
          </Link>
          <Link
            href="/creator-studio"
            className="text-[13.5px] font-medium text-slate-700 hover:text-slate-900"
          >
            ← Back to My World
          </Link>
        </div>
      </div>
    </>
  )
}
