import { getCreatorSpaces } from '@/lib/serverApi'
import type { SpaceSummary } from '@/types/platform'
import CreatorSupportForm from './CreatorSupportForm'

/**
 * /creator/support — Request Fresh Collective Support (Community Care Stage 2B).
 *
 * The scoped intake for creators. It exists so creators have a clear
 * calm channel to Fresh Collective when something on the platform,
 * inside a collective, or with a member needs FC's attention. It is
 * deliberately not a general business or growth coaching channel —
 * the guidance on the page makes that scope explicit.
 */

export default async function CreatorSupportPage() {
  const spaces: SpaceSummary[] = await getCreatorSpaces()

  return (
    <div className="mx-auto max-w-2xl px-6 py-12 md:px-10">
      <div className="mb-8">
        <div className="mb-2 h-px w-8 bg-gold-400" />
        <h1 className="mb-2 font-serif text-3xl text-navy-900">
          Request Fresh Collective support
        </h1>
        <p className="text-[14px] leading-relaxed text-black">
          Use this form to tell Fresh Collective what you need help with.
          A Fresh Collective administrator will read every request and
          be in touch.
        </p>
      </div>

      <div
        className="mb-8 rounded-2xl px-5 py-4 text-[13px] leading-relaxed"
        style={{
          background: 'rgba(56,160,158,0.08)',
          border: '1px solid rgba(56,160,158,0.20)',
          color: '#0f4645',
        }}
      >
        <p className="mb-2 font-semibold">What this is for</p>
        <p>
          This service supports creators with their communities and their
          use of the platform — questions about member wellbeing, a
          concerning situation in your collective, a feature that is not
          behaving as you expect, or a technical issue.
        </p>
        <p className="mt-2">
          It is not a general business or growth coaching channel. For
          those conversations we point you to other resources outside the
          platform.
        </p>
      </div>

      <CreatorSupportForm spaces={spaces} />
    </div>
  )
}
