import Link from 'next/link'
import { notFound } from 'next/navigation'
import { getYourCollection } from '@/lib/serverApi'
import CollectionCard from '@/components/offerings/CollectionCard'
import type { YourCollection } from '@/types/platform'

/**
 * Your World → Your Collection.
 *
 * Everything this member has acquired, across every Collective, in one
 * list. Not split into "my Offerings" and "my files": an acquired
 * Offering is one thing a person owns, and dividing it would make them
 * learn a distinction that exists only in the schema.
 *
 * Deliberately **not** the Creator Library. That is a creator-side
 * surface for the assets they upload, it is documented in published
 * World Builders instructions, and nothing here renames, moves or
 * touches it.
 *
 * ``null`` from the fetcher means the area is closed — the Offerings
 * feature is off — and the route 404s to match the API. An empty list
 * means a member who has not acquired anything yet, which is a
 * different thing and gets the invitation below.
 */
export default async function YourCollectionPage() {
  const collection: YourCollection | null = await getYourCollection()

  if (collection === null) notFound()

  const { items } = collection

  return (
    <div className="mx-auto w-full max-w-[1100px] px-5 py-8 md:px-8 md:py-12">

      <div className="mb-10">
        <h2
          className="font-serif text-[26px] leading-tight md:text-[30px]"
          style={{ color: '#0C1826' }}
        >
          Your Collection
        </h2>
        <p
          className="mt-2 max-w-[640px] text-[14px] italic leading-relaxed"
          style={{ color: 'rgba(12, 24, 38, 0.62)', fontFamily: 'Georgia, serif' }}
        >
          {items.length > 0
            ? 'Everything you’ve gathered from the creators and Collectives you’re part of.'
            : 'Resources you gather from across Fresh Collective live here.'}
        </p>
      </div>

      {items.length === 0 ? (
        /* The empty state is the page for most people the first time
           they arrive, so it is an invitation rather than a report of
           nothing. */
        <div
          className="rounded-2xl border bg-white px-7 py-14 text-center"
          style={{ borderColor: 'var(--fc-accent-line, rgba(56,160,158,0.20))' }}
        >
          <p
            className="font-serif text-[22px] leading-snug"
            style={{ color: '#0C1826' }}
          >
            ✨ Your Collection starts here
          </p>
          <p
            className="mx-auto mt-3 max-w-[480px] text-[14px] leading-relaxed"
            style={{ color: 'rgba(12,24,38,0.68)' }}
          >
            As you explore Fresh Collective, the resources you choose
            will find a home here. Discover workbooks, guides, audio
            experiences and more from the creators and Collectives you
            love.
          </p>
          <div className="mt-7 flex flex-wrap items-center justify-center gap-3">
            <Link
              href="/spaces"
              className="rounded-full px-5 py-2.5 text-[13.5px] font-semibold text-white transition-opacity hover:opacity-90"
              style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
            >
              Explore Collectives
            </Link>
            <Link
              href="/dashboard"
              className="rounded-full border border-slate-200 px-5 py-2.5 text-[13.5px] font-medium text-black transition-colors hover:border-teal-200 hover:text-teal-700"
            >
              Back to Your World
            </Link>
          </div>
        </div>
      ) : (
        <>
          <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
            {items.map((item) => (
              <CollectionCard key={item.entitlement_id} item={item} />
            ))}
          </div>
          <p
            className="mt-8 text-[12.5px] italic leading-relaxed"
            style={{ color: 'rgba(12,24,38,0.55)' }}
          >
            These are yours to keep. They stay here whether or not you
            remain a member of the Collective they came from, and
            whether or not the creator still offers them.
          </p>
        </>
      )}
    </div>
  )
}
