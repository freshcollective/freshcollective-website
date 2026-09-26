/**
 * The surface is not available right now.
 *
 * Two distinct causes, one calm screen, and neither of them says
 * "you have not crossed paths with anyone". That sentence is a claim
 * about the member's life, and we must not make it because a request
 * failed or because a deployment is half-flipped.
 *
 *   unavailable — the backend flag is off. Normally impossible, since
 *                 the flags are turned on together; this exists so a
 *                 mismatched deploy is a quiet sentence rather than a
 *                 stack trace.
 *   error       — anything else. The member gets a retry, because
 *                 that is the thing most likely to work.
 */

import Link from 'next/link'

export default function WaysToConnectUnavailable({
  reason,
}: {
  reason: 'unavailable' | 'error'
}) {
  const isFlag = reason === 'unavailable'

  return (
    <section className="mx-auto max-w-[720px] px-6 pb-24 pt-4 md:px-8 md:pt-6">
      <div
        className="rounded-3xl bg-white px-8 py-12 text-center md:px-12 md:py-14"
        style={{
          border: '1px solid rgba(12, 24, 38, 0.06)',
          boxShadow: '0 14px 40px rgba(12, 24, 38, 0.06), 0 2px 8px rgba(12, 24, 38, 0.03)',
        }}
      >
        <h2
          className="font-serif text-[20px] leading-tight md:text-[23px]"
          style={{ color: '#0C1826' }}
        >
          {isFlag
            ? 'Ways to Connect isn’t open yet.'
            : 'We couldn’t load this just now.'}
        </h2>

        <p
          className="mx-auto mt-4 max-w-[480px] text-[14.5px] leading-[1.7]"
          style={{ color: 'rgba(12, 24, 38, 0.72)', fontFamily: 'Georgia, serif' }}
        >
          {isFlag
            ? 'This part of Fresh Collective is still being prepared. Nothing is missing from your account — there is simply nothing here to open yet.'
            : 'Something went wrong on our side, not yours. Your shared experiences are all still here.'}
        </p>

        <div className="mt-8">
          {isFlag ? (
            <Link
              href="/dashboard"
              className="inline-flex items-center rounded-full border px-6 py-2.5 text-[13px] font-medium transition-colors"
              style={{ borderColor: 'rgba(12, 24, 38, 0.14)', color: '#0C1826' }}
            >
              Back to Your World <span aria-hidden="true" className="ml-1.5">→</span>
            </Link>
          ) : (
            /* A plain link to this same route. The page is
               server-rendered, so following it re-runs the request —
               no client state to reset and nothing to get stuck. */
            <Link
              href="/ways-to-connect"
              prefetch={false}
              className="inline-flex items-center rounded-full px-6 py-2.5 text-[13px] font-semibold text-white transition-opacity hover:opacity-90"
              style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
            >
              Try again
            </Link>
          )}
        </div>
      </div>
    </section>
  )
}
