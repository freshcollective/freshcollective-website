/**
 * Structural tests for the Ways to Connect surface.
 *
 * Same pattern as ``src/app/creator-studio/settings/DangerZone.test.ts``:
 * read the source, strip comments, assert the invariants that must
 * not silently regress — without spinning up React DOM.
 *
 * Comments are stripped first and deliberately, because several of
 * the invariants here are about words. Prose in a docstring saying
 * "we never say 'connected'" must not be what satisfies a test that
 * the copy never says "connected".
 */

import { strict as assert } from 'node:assert'
import { describe, test } from 'node:test'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const _here = dirname(fileURLToPath(import.meta.url))
const SRC = join(_here, '..', '..')

function code(relative: string): string {
  return readFileSync(join(SRC, relative), 'utf-8')
    .replace(/\{\s*\/\*[^]*?\*\/\s*\}/g, '')
    .replace(/\/\*[^]*?\*\//g, '')
    .replace(/^\s*\/\/.*$/gm, '')
}

const PAGE = code('app/ways-to-connect/page.tsx')
const PEOPLE = code('components/connections/PeopleYouveCrossed.tsx')
const CARD_P = code('components/connections/PersonCard.tsx')
const PORTRAIT = code('components/ui/MemberImage.tsx')
const CARD = code('components/connections/SharedContextCard.tsx')  // collective page
const EMPTY = code('components/connections/WaysToConnectEmptyState.tsx')
const UNAVAILABLE = code('components/connections/WaysToConnectUnavailable.tsx')
const NOTE = code('components/connections/RecognitionNote.tsx')
const INCONTEXT = code('components/connections/InContextRecognition.tsx')
const CLIENT = code('lib/serverApi.ts')
const PATHWAY_OVERVIEW = code('app/spaces/[slug]/pathways/[pathway-slug]/page.tsx')
const PATHWAY_STEP = code('app/spaces/[slug]/pathways/[pathway-slug]/[step-slug]/page.tsx')
const GATHERING_PAGE = code('app/spaces/[slug]/events/[eventId]/page.tsx')

describe('feature gating', () => {
  test('the route still 404s when it is unavailable', () => {
    // The gate moved from the raw flag to the shared
    // ``waysToConnectVisible`` helper, which adds the Platform Owner
    // preview on top of the same flag. For every ordinary member the
    // behaviour is unchanged — proven server-side in
    // test_ways_to_connect_owner_preview.py, which is the enforcing
    // layer rather than this one.
    assert.match(PAGE, /if\s*\(!\(await waysToConnectVisible\(\)\)\)\s*notFound\(\)/)
  })

  test('in-context Recognition is gated on the same flag', () => {
    assert.match(INCONTEXT, /isWaysToConnectEnabled\(\)/)
  })

  test('the launch flag is never derived from the member preference', () => {
    // These are two different questions — whether the product exists,
    // and whether this person takes part — and conflating them is how
    // the feature would vanish for somebody who opted out, leaving
    // them no route back to it.
    //
    // The page now reads ``ways_to_connect_enabled`` on purpose, to
    // choose between the opt-in state and the recommendations. What it
    // must not do is let that decide *availability*: the only gate is
    // ``waysToConnectVisible()``. Covered in depth in
    // ``waysToConnectOptIn.test.ts``; asserted here because this is
    // the file about the flag.
    assert.match(PAGE, /ways_to_connect_enabled/, 'the page reads the preference')
    for (const line of PAGE.split('\n')) {
      if (!line.includes('notFound')) continue
      assert.ok(
        !line.includes('ways_to_connect_enabled'),
        `availability must not depend on participation: ${line.trim()}`,
      )
    }

    // In-context Recognition stays clear of it entirely: those lines
    // come from the API, which already drops opted-out members, so the
    // component has no business re-deciding it.
    assert.ok(!/ways_to_connect_enabled/.test(INCONTEXT))
  })
})

describe('the four states are kept apart', () => {
  test('the client distinguishes unavailable from error from ok', () => {
    assert.match(CLIENT, /res\.status === 503/)
    assert.match(CLIENT, /status: 'unavailable'/)
    assert.match(CLIENT, /status: 'error'/)
    assert.match(CLIENT, /status: 'ok'/)
  })

  test('a failed request never becomes an empty Recognition state', () => {
    const start = CLIENT.indexOf('export async function getWaysToConnect')
    assert.ok(start > -1, 'getWaysToConnect must exist')
    // Up to the next top-level export — the whole function body and
    // nothing of its neighbours.
    const rest = CLIENT.slice(start + 1)
    const end = rest.indexOf('\nexport ')
    const fn = end === -1 ? rest : rest.slice(0, end)

    assert.ok(!/contexts:\s*\[\]/.test(fn), 'must not fabricate an empty payload')
    assert.ok(!/return \[\]/.test(fn), 'must not fall back to an empty list')
    // Every non-ok path must name itself rather than degrade quietly.
    assert.match(fn, /return \{ status: 'unavailable' \}/)
    assert.match(fn, /return \{ status: 'error' \}/)
  })

  test('the page routes unavailable and error away from the empty state', () => {
    assert.match(
      PAGE,
      /status === 'unavailable' \|\| result\.status === 'error'/,
    )
    assert.match(PAGE, /WaysToConnectUnavailable/)
  })

  test('the unavailable screen never claims the member shares nothing', () => {
    for (const claim of [
      'no one', 'nobody', "haven't crossed", 'no shared', 'zero',
    ]) {
      assert.ok(
        !UNAVAILABLE.toLowerCase().includes(claim),
        `unavailable state must not assert "${claim}"`,
      )
    }
  })

  test('an ordinary failure offers a retry', () => {
    assert.match(UNAVAILABLE, /Try again/)
  })
})

describe('the destination is people-first', () => {
  test('the page renders the featured people, not grouped contexts', () => {
    assert.match(PAGE, /featuredPeople\(result\.data\)/)
    assert.match(PAGE, /PeopleYouveCrossed/)
    assert.ok(!/groupContexts/.test(PAGE))
  })

  test('the card leads with the person', () => {
    const jsx = CARD_P.slice(CARD_P.indexOf('return ('))
    const nameAt = jsx.indexOf('{name}')
    const reasonAt = jsx.indexOf('{reason}')
    const sharedAt = jsx.indexOf('Shared')
    assert.ok(nameAt > -1 && reasonAt > nameAt, 'name precedes the reason')
    assert.ok(sharedAt > reasonAt, 'the evidence comes after the reason')
  })

  test('the card shows the shared evidence, unlike the old prototype', () => {
    assert.match(CARD_P, /person\.shared\.map/)
    assert.match(CARD_P, /\{thing\.title\}/)
  })

  test('there is no link to a profile anywhere', () => {
    for (const source of [CARD_P, PEOPLE, PORTRAIT]) {
      assert.ok(!/\/profile\//.test(source), 'no profile links')
      assert.ok(!/<Link/.test(source), 'a person is not a destination')
    }
  })

  test('the portrait has no category colour', () => {
    assert.match(PORTRAIT, /WARM_STONE/)
    assert.ok(!/right-now|shared-journey|thoughtful/.test(PORTRAIT),
      'the retired intent palette must not come back')
  })

  test('the card renders the server-resolved image, not its own ladder', () => {
    assert.match(CARD_P, /<MemberImage image=\{person\.image\}/)
    assert.ok(
      !/avatar_url/.test(CARD_P),
      'the card must not reach for avatar_url — the server already chose',
    )
  })

  test('the shared component renders what it is told', () => {
    // Four kinds decided server-side; this only draws them.
    assert.match(PORTRAIT, /image\.kind === 'photo'/)
    assert.match(PORTRAIT, /image\.initial/)
    assert.ok(
      !/is_public|creator/i.test(PORTRAIT),
      'visibility is a server decision, not a rendering one',
    )
  })

  test('the portrait is decorative — the name carries the meaning', () => {
    assert.match(PORTRAIT, /aria-hidden="true"/)
    assert.match(PORTRAIT, /alt=""/)
  })

  test('an unnamed person is never rendered as a card', () => {
    assert.match(CARD_P, /if \(!name\) return null/)
  })

  test('cards keep a fixed width instead of dividing the container', () => {
    // A grid gives each card a share of the width, so two people
    // produce two enormous cards and one produces an absurd one. The
    // card owns its width; the row centres what it is given.
    assert.match(CARD_P, /(sm|md|lg):w-\[\d+px\]/, 'card has a fixed desktop width')
    assert.match(CARD_P, /\bw-full\b/, 'and the full width on a phone')
    assert.ok(
      !/grid-cols-\d/.test(PEOPLE),
      'no column maths — one card in a 3-column grid is the bug',
    )
    // The only permitted length check is the "nobody at all" guard;
    // anything comparing against 2 or 3 is column maths returning.
    const branches = PEOPLE.match(/people\.length\s*(?:>=|===|>|<)\s*\d+/g) ?? []
    assert.deepEqual(
      branches, ['people.length === 0'],
      'layout must not branch on how many people there are',
    )
  })
})

describe('Say hello is a two-step action', () => {
  test('pressing it asks for confirmation rather than sending', () => {
    assert.match(CARD_P, /setState\('confirming'\)/)
    // 5b: the question varies — replying to someone who already said
    // hello reads differently from greeting first.
    assert.match(CARD_P, /Say hello to \$\{name\}\?/)
    assert.match(CARD_P, /Say hello back to \$\{name\}\?/)
  })

  test('the confirmation explains what it does', () => {
    assert.match(CARD_P, /open to connecting/)
    // 5b: replying completes the pair, so say that instead.
    assert.match(CARD_P, /connects you both/)
    // The old copy promised messaging after a mutual hello. 5b
    // deliberately stops at "Connected" — the existing messaging model
    // is creator-to-member inside a Collective and has no peer thread —
    // so that sentence would now be untrue.
    assert.ok(!/be able to message/.test(CARD_P))
  })

  test('it offers a way out', () => {
    assert.match(CARD_P, /Cancel/)
  })

  test('the sent state is quiet and final', () => {
    assert.match(CARD_P, /Hello sent/)
    assert.match(CARD_P, /aria-live="polite"/)
  })

  test('the send path reaches the real endpoint', () => {
    // 5a left this as an injected callback with nothing behind it. 5b
    // has the card call the API itself, because the page that renders
    // it is a server component and cannot hand down a function; the
    // prop survives as a preview override.
    assert.match(CARD_P, /onSendHello\?:/)
    assert.match(CARD_P, /await onSendHello\(person\.id\)/)
    assert.match(CARD_P, /await sayHello\(person\.id\)/)
  })

  test('the card does not hand-roll its own request', () => {
    // Was "nothing is persisted during 5a". 5b persists, so the
    // invariant worth keeping is the narrower one: the transport lives
    // in ``lib/waysToConnect`` with the types and the endpoint shape,
    // and the card calls it. An inline fetch here would be a second
    // place for the URL and the error handling to drift.
    assert.ok(!/fetch\(/.test(CARD_P), 'no inline fetch in the card')
    assert.ok(!/apiUrl/.test(CARD_P))
    assert.match(CARD_P, /sayHello/)
  })

  test('the action names who it is for', () => {
    assert.match(CARD_P, /sr-only/)
  })
})

describe('the empty state', () => {
  test('is honest about the product model, not about introductions', () => {
    assert.match(EMPTY, /Connection grows through shared experiences/)
    assert.ok(!/Introductions grow/.test(EMPTY),
      'the brokered-introduction heading belonged to a design we did not build')
  })

  test('explains that participation is what gives it something to show', () => {
    assert.match(EMPTY, /collectives/i)
    assert.match(EMPTY, /gatherings/i)
    assert.match(EMPTY, /pathways/i)
  })

  test('falls back to Explore Collectives when there is no doorway', () => {
    assert.match(EMPTY, /href="\/spaces"/)
    assert.match(EMPTY, /Explore Collectives/)
  })

  test('the contextual doorway points at a real Gathering', () => {
    assert.match(EMPTY, /\/spaces\/\$\{gathering\.spaceSlug\}\/events\/\$\{gathering\.id\}/)
  })

  test('invents no people and no activity', () => {
    for (const fake of ['Sarah', 'Emma', 'James', 'sample', 'example.com', 'placeholder']) {
      assert.ok(!EMPTY.includes(fake), `empty state must not invent "${fake}"`)
    }
  })

  test('the doorway costs nothing when the member belongs nowhere', () => {
    assert.match(PAGE, /if \(active\.length === 0\) return null/)
  })

  test('the doorway is bounded rather than fanning out', () => {
    assert.match(PAGE, /DOORWAY_COLLECTIVE_LIMIT/)
    assert.match(PAGE, /slice\(0, DOORWAY_COLLECTIVE_LIMIT\)/)
  })
})

describe('in-context Recognition', () => {
  test('renders nothing rather than an error on another page', () => {
    assert.match(INCONTEXT, /if \(result\.status !== 'ok'\) return null/)
  })

  test('returns null when the viewer shares nothing here', () => {
    assert.match(INCONTEXT, /if \(!context\) return null/)
  })

  test('uses the "here" vantage on the shared thing’s own page', () => {
    assert.match(INCONTEXT, /vantage="here"/)
  })

  test('the note is a single line with no action', () => {
    assert.ok(!/<button/.test(NOTE))
    assert.ok(!/<Link/.test(NOTE))
    assert.ok(!/href/.test(NOTE))
  })

  test('the note does not depend on avatar imagery', () => {
    assert.ok(!/Avatar/.test(NOTE), 'the sentence carries the meaning')
    assert.match(NOTE, /aria-hidden="true"/, 'the mark is decorative')
  })
})

describe('in-context Recognition is placed where it can be seen', () => {
  // Caught by the demo seed, not by a unit test: the pathway line was
  // originally on the pathway overview, which redirects every
  // accessible member straight to their current step. It compiled, it
  // type-checked, it was covered — and it was unreachable for exactly
  // the people who could have Recognition on it.

  test('the pathway overview still redirects past itself', () => {
    // The behaviour that made the original placement dead. If this
    // ever stops being true, the placement below can be reconsidered.
    assert.match(
      PATHWAY_OVERVIEW,
      /redirect\(`\/spaces\/\$\{slug\}\/pathways\/\$\{pathwaySlug\}\/\$\{continueSlug\}`\)/,
    )
  })

  test('the pathway line is NOT on the page that redirects', () => {
    assert.ok(
      !/PathwayRecognition/.test(PATHWAY_OVERVIEW),
      'a member with a shared pathway never sees the overview',
    )
  })

  test('the pathway line is on the step page', () => {
    assert.match(PATHWAY_STEP, /PathwayRecognition/)
    assert.match(PATHWAY_STEP, /pathwayId=\{overview\.id\}/)
  })

  test('the gathering line is on the gathering page', () => {
    assert.match(GATHERING_PAGE, /GatheringRecognition/)
    assert.match(GATHERING_PAGE, /gatheringId=\{event\.id\}/)
  })

  test('the gathering page does not redirect away from itself', () => {
    assert.ok(
      !/redirect\(/.test(GATHERING_PAGE),
      'if this page ever gains a redirect, re-check the placement',
    )
  })
})

describe('accessibility and mobile', () => {
  test('the card action names which thing it opens', () => {
    assert.match(CARD, /sr-only/)
    assert.match(CARD, /\{context\.title\}/)
  })

  test('decorative marks are hidden from assistive technology', () => {
    for (const source of [NOTE, EMPTY, PORTRAIT]) {
      assert.match(source, /aria-hidden="true"/)
    }
  })

  test('arrows are decorative rather than announced', () => {
    for (const source of [CARD, EMPTY]) {
      const arrows = source.match(/→/g) ?? []
      const hidden = source.match(/aria-hidden="true">→/g) ?? []
      assert.equal(arrows.length, hidden.length,
        'every → must sit inside an aria-hidden span')
    }
  })

  test('a short row is centred rather than left-hugging', () => {
    assert.match(PEOPLE, /flex flex-wrap justify-center/)
  })

  test('no placeholder cards and no empty columns', () => {
    // An empty column is still a visible gap; a card for nobody is
    // worse than a short row.
    assert.ok(!/placeholder/i.test(PEOPLE))
    assert.ok(!/Array\.from|fill\(/.test(PEOPLE), 'nothing is padded out')
  })

  test('the section constrains its own width rather than the viewport', () => {
    assert.match(PEOPLE, /max-w-\[980px\]/)
  })

  test('the portrait stays square against the card width', () => {
    assert.match(PORTRAIT, /aspectRatio: '1 \/ 1'/)
  })

  test('the initial sizes against the square, not the viewport', () => {
    // The container query has to be declared on the square itself —
    // on the span it would measure the span.
    const square = PORTRAIT.slice(PORTRAIT.indexOf('aspectRatio'))
    assert.match(square, /containerType: 'inline-size'/)
    assert.match(PORTRAIT, /cqw/)
  })

  test('a photo is cropped and a card is not', () => {
    // An illustrated card is drawn for its frame; cropping it would
    // cut the artwork.
    assert.match(PORTRAIT, /object-cover/)
    assert.match(PORTRAIT, /object-contain/)
  })
})
