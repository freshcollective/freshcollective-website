/**
 * The destination's body: a few people, not a feed.
 *
 * At most three, chosen by the server. No "show more", no paging, no
 * search, no way to ask for somebody who was not offered — those
 * absences are what keep this from being a people directory, far more
 * than any wording does.
 *
 * Layout: a centred row of fixed-width cards rather than a grid that
 * divides the container. A grid gives each card a *share* of the
 * width, so two people produce two enormous cards and one person
 * produces an absurd one — the card grows to fill space it has no
 * content for. Fixing the card width and centring the row instead
 * means one, two or three people all look like the same object,
 * because they are.
 *
 * Wrapping, not scrolling, and no placeholders: an empty column is
 * still a visible gap, and a card for nobody is worse than a short
 * row.
 */

import PersonCard from './PersonCard'
import type { PersonRef } from '@/lib/waysToConnect'

export default function PeopleYouveCrossed({
  people,
}: {
  people: PersonRef[]
}) {
  if (people.length === 0) return null

  return (
    <section className="mx-auto max-w-[980px] px-6 pb-24 pt-2 md:px-8">
      <h2 className="font-serif text-[15px]" style={{ color: '#0C1826' }}>
        People you’ve crossed paths with
      </h2>
      <p className="mt-1 text-[12.5px]" style={{ color: 'rgba(12, 24, 38, 0.5)' }}>
        Shown because of something you genuinely share, not because of
        anything we guessed.
      </p>

      {/* Centred so a short row sits under the heading rather than
          hugging the left edge of a wide screen. The cards size
          themselves — see PersonCard. */}
      <ul className="mt-5 flex flex-wrap justify-center gap-5">
        {people.map((person) => (
          <PersonCard key={person.id} person={person} />
        ))}
      </ul>
    </section>
  )
}
