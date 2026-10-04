import Link from 'next/link'

/**
 * The calm "your plan doesn't include this" surface for Creator Studio.
 *
 * Generalised from ``creator-studio/offers/UpgradeNotice``, which did
 * this for Offer Pages alone. The sidebar hides every commercial entry
 * on Community, so a direct URL is the only way to arrive at one of
 * these pages on that plan — and arriving should explain the plan, not
 * show a 403, an empty table, or a tool whose every action fails.
 *
 * Navigation hiding is never the security boundary: the backend plan
 * guards in ``app/creator/plan_guards.py`` remain authoritative for
 * every write. This component only decides what a Community creator
 * *reads*.
 */
export default function PlanUpgradeNotice({
  title,
  intro,
  unlocks,
}: {
  /** The feature as the sidebar names it, e.g. "Payment Options". */
  title: string
  /** One sentence on what the feature is for. */
  intro: string
  /** What upgrading specifically unlocks, as a sentence fragment. */
  unlocks: string
}) {
  return (
    <div className="w-full max-w-[1180px] px-8 py-8 md:px-10 md:py-10">
      <div className="mb-8">
        <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500">
          Creator Studio
        </p>
        <h1 className="font-serif text-2xl text-navy-900 md:text-3xl">{title}</h1>
        <p className="mt-2 max-w-2xl text-[15px] leading-relaxed text-black">
          {intro}
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
          {' '}{title} isn&rsquo;t part of it. Upgrading to Creator unlocks
          {' '}{unlocks}.
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
    </div>
  )
}
