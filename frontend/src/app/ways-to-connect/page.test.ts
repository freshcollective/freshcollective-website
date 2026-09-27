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
const GROUPS = code('components/connections/SharedContextGroups.tsx')
const CARD = code('components/connections/SharedContextCard.tsx')
const EMPTY = code('components/connections/WaysToConnectEmptyState.tsx')
const UNAVAILABLE = code('components/connections/WaysToConnectUnavailable.tsx')
const NOTE = code('components/connections/RecognitionNote.tsx')
const INCONTEXT = code('components/connections/InContextRecognition.tsx')
const CLIENT = code('lib/serverApi.ts')
const PATHWAY_OVERVIEW = code('app/spaces/[slug]/pathways/[pathway-slug]/page.tsx')
const PATHWAY_STEP = code('app/spaces/[slug]/pathways/[pathway-slug]/[step-slug]/page.tsx')
const GATHERING_PAGE = code('app/spaces/[slug]/events/[eventId]/page.tsx')

describe('feature gating', () => {
  test('the route still 404s when the frontend flag is off', () => {
    assert.match(PAGE, /if\s*\(!isWaysToConnectEnabled\(\)\)\s*notFound\(\)/)
  })

  test('in-context Recognition is gated on the same flag', () => {
    assert.match(INCONTEXT, /isWaysToConnectEnabled\(\)/)
  })

  test('the backend flag is not mirrored through the profile', () => {
    for (const source of [PAGE, INCONTEXT]) {
      assert.ok(!/ways_to_connect_enabled/.test(source))
    }
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

describe('the destination is context-first', () => {
  test('the three groups are the shared things, not people', () => {
    assert.match(GROUPS, /Coming up/)
    assert.match(GROUPS, /Shared pathways/)
    assert.match(GROUPS, /Recent crossings/)
  })

  test('each group renders only when it has something in it', () => {
    for (const g of ['comingUp', 'pathways', 'recent']) {
      assert.match(
        GROUPS,
        new RegExp(`grouped\\.${g}\\.length > 0 &&`),
        `${g} heading must be conditional`,
      )
    }
  })

  test('a card leads the Gathering or Pathway, not the person', () => {
    // Compare positions inside the rendered markup, not the whole
    // module — the sentence is computed near the top and rendered
    // near the bottom, which is exactly the point.
    const jsx = CARD.slice(CARD.indexOf('return ('))
    const titleAt = jsx.indexOf('{context.title}')
    const metaAt = jsx.indexOf('{metaLine(context)}')
    const peopleAt = jsx.indexOf('{sentence}')

    assert.ok(titleAt > -1 && metaAt > -1 && peopleAt > -1)
    assert.ok(titleAt < metaAt, 'the shared thing leads')
    assert.ok(metaAt < peopleAt, 'the people come after the context')
  })

  test('the action goes back into the shared context', () => {
    assert.match(CARD, /\/spaces\/\$\{context\.collective\.slug\}\/events\/\$\{context\.id\}/)
    assert.match(CARD, /\/spaces\/\$\{context\.collective\.slug\}\/pathways\/\$\{context\.slug\}/)
  })

  test('there is no link to a person anywhere', () => {
    for (const source of [CARD, GROUPS, NOTE]) {
      assert.ok(!/\/profile\//.test(source), 'no profile links')
      assert.ok(!/person\.id\}\`/.test(source), 'no person-keyed hrefs')
    }
  })

  test('no person-indexed grouping exists', () => {
    for (const source of [GROUPS, CARD]) {
      assert.ok(!/groupBy(Person|People)/i.test(source))
      assert.ok(!/byPerson/i.test(source))
    }
  })
})

describe('no ranking anywhere', () => {
  test('no score, rank, match or strength in the surface', () => {
    for (const [name, source] of Object.entries({
      PAGE, GROUPS, CARD, EMPTY, NOTE, UNAVAILABLE,
    })) {
      for (const banned of ['score', 'ranking', 'rank(', 'strength', 'match%', 'relevance']) {
        assert.ok(
          !source.toLowerCase().includes(banned),
          `${name} must not contain "${banned}"`,
        )
      }
    }
  })

  test('the truncated notice offers no counts and no way to page', () => {
    assert.match(GROUPS, /truncated &&/)
    assert.ok(!/load more/i.test(GROUPS))
    assert.ok(!/\btotal\b/i.test(GROUPS))
    assert.ok(!/of \$\{/.test(GROUPS), 'no "60 of 84"')
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
    for (const source of [NOTE, EMPTY]) {
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

  test('the layout is a single column list, not a fixed grid', () => {
    assert.match(GROUPS, /flex flex-col/)
    assert.ok(!/grid-cols-\d/.test(GROUPS), 'one recognition in a grid reads as a broken grid')
  })

  test('the card constrains its own width rather than the viewport', () => {
    assert.match(GROUPS, /max-w-\[720px\]/)
  })
})
