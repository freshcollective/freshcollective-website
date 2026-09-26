/**
 * The language Ways to Connect puts around a shared experience.
 *
 * Pure-function tests, the same shape as ``src/lib/pricing.test.ts``
 * and its neighbours. Phrasing is the part of this feature most
 * likely to read badly in a real account — three unnamed people, one
 * named person and four unnamed, a group of exactly two — so every
 * awkward combination is exercised here rather than discovered on a
 * member's screen.
 */

import { strict as assert } from 'node:assert'
import { describe, test } from 'node:test'

import {
  MAX_NAMES,
  contextSentence,
  contextsInCollective,
  describePeople,
  findGatheringContext,
  findPathwayContext,
  gatheringSentence,
  groupContexts,
  hasAnyContext,
  pathwaySentence,
  splitPeople,
  type GatheringContext,
  type PathwayContext,
  type PersonRef,
} from './waysToConnect.ts'

const COLLECTIVE = {
  id: 'sp_1',
  slug: 'embody',
  name: 'EMBODY',
  timezone: 'Australia/Melbourne',
}

function named(name: string, id = `u_${name}`): PersonRef {
  return { id, display_name: name, avatar_url: null }
}
function unnamed(id: string): PersonRef {
  return { id, display_name: null, avatar_url: null }
}

function gathering(
  people: PersonRef[],
  basis: 'upcoming' | 'attended' = 'upcoming',
  over: Partial<GatheringContext> = {},
): GatheringContext {
  return {
    kind: 'gathering',
    id: 'ev_1',
    title: 'Thursday EMBODY',
    starts_at: '2026-10-08T19:00:00',
    basis,
    collective: COLLECTIVE,
    people,
    ...over,
  }
}

function pathway(
  people: PersonRef[],
  over: Partial<PathwayContext> = {},
): PathwayContext {
  return {
    kind: 'pathway',
    id: 'pw_1',
    slug: 'life-in-alignment',
    title: 'Life in Alignment',
    collective: COLLECTIVE,
    people,
    ...over,
  }
}

// ---------------------------------------------------------------------------

describe('describePeople — named members', () => {
  test('one person', () => {
    assert.equal(describePeople([named('Sarah')]), 'Sarah')
  })

  test('two people join with "and", not a comma', () => {
    assert.equal(describePeople([named('Sarah'), named('James')]), 'Sarah and James')
  })

  test('three people use a serial list', () => {
    assert.equal(
      describePeople([named('Sarah'), named('James'), named('Maya')]),
      'Sarah, James and Maya',
    )
  })

  test('beyond MAX_NAMES the remainder becomes a count', () => {
    const people = ['Sarah', 'James', 'Maya', 'Ana', 'Tom'].map((n) => named(n))
    assert.equal(
      describePeople(people),
      'Sarah, James, Maya and 2 other people',
    )
    assert.equal(MAX_NAMES, 3)
  })
})

describe('describePeople — unnamed members', () => {
  test('a single unnamed person is "someone else", not a headcount', () => {
    const out = describePeople([unnamed('u1')])
    assert.equal(out, 'someone else')
    assert.ok(!out.includes('Member'), out)
    // "one other person" counts a person the way a form would. The
    // fact is identical; only one of them sounds like company.
    assert.ok(!out.includes('one other person'))
    assert.ok(!/\b1\b/.test(out), 'never a numeral for a single person')
  })

  test('several unnamed people collapse to a count, never repeated labels', () => {
    const out = describePeople([unnamed('u1'), unnamed('u2'), unnamed('u3')])
    assert.equal(out, '3 people')
    assert.ok(!out.includes('Member'))
    assert.ok(!/null|undefined/.test(out))
  })

  test('two unnamed people alone are counted, not softened', () => {
    assert.equal(describePeople([unnamed('a'), unnamed('b')]), '2 people')
  })

  test('one named plus one unnamed', () => {
    assert.equal(
      describePeople([named('Sarah'), unnamed('u1')]),
      'Sarah and someone else',
    )
  })

  test('one named plus several unnamed keeps the number', () => {
    assert.equal(
      describePeople([named('Sarah'), unnamed('u1'), unnamed('u2')]),
      'Sarah and 2 other people',
    )
  })

  test('the softened phrase applies only to exactly one person', () => {
    // Past one, a number is the honest thing — "some other people"
    // is vaguer than we need to be.
    for (const n of [2, 3, 5]) {
      const group = Array.from({ length: n }, (_, i) => unnamed(`u${i}`))
      const out = describePeople([named('Sarah'), ...group])
      assert.equal(out, `Sarah and ${n} other people`)
      assert.ok(!out.includes('someone else'), out)
    }
  })

  test('two named plus several unnamed', () => {
    assert.equal(
      describePeople([named('Sarah'), named('James'), unnamed('a'), unnamed('b')]),
      'Sarah, James and 2 other people',
    )
  })

  test('a blank or whitespace name counts as unnamed', () => {
    const blank: PersonRef = { id: 'u1', display_name: '   ', avatar_url: null }
    assert.equal(describePeople([named('Sarah'), blank]), 'Sarah and someone else')
  })

  test('an empty group describes nobody', () => {
    assert.equal(describePeople([]), '')
  })
})

describe('splitPeople', () => {
  test('separates the nameable from the counted', () => {
    const { names, others } = splitPeople([
      named('Sarah'), unnamed('a'), named('James'), unnamed('b'),
    ])
    assert.deepEqual(names, ['Sarah', 'James'])
    assert.equal(others, 2)
  })
})

// ---------------------------------------------------------------------------

describe('gathering sentences', () => {
  test('upcoming, on the Gathering’s own page', () => {
    assert.equal(
      gatheringSentence(gathering([named('Sarah'), named('James')]), 'here'),
      'You’ll be here with Sarah and James.',
    )
  })

  test('upcoming, seen from elsewhere', () => {
    assert.equal(
      gatheringSentence(gathering([named('Sarah')]), 'there'),
      'You’ll be there with Sarah.',
    )
  })

  test('attended, on the Gathering’s own page', () => {
    assert.equal(
      gatheringSentence(gathering([named('Sarah'), named('James')], 'attended'), 'here'),
      'You were here with Sarah and James.',
    )
  })

  test('attended, seen from elsewhere', () => {
    assert.equal(
      gatheringSentence(gathering([named('Maya')], 'attended'), 'there'),
      'You were there with Maya.',
    )
  })

  test('mixed named and unnamed reads naturally', () => {
    assert.equal(
      gatheringSentence(gathering([named('Sarah'), unnamed('a'), unnamed('b')]), 'there'),
      'You’ll be there with Sarah and 2 other people.',
    )
  })

  test('a single unnamed companion reads as company, not a count', () => {
    assert.equal(
      gatheringSentence(gathering([unnamed('u1')]), 'here'),
      'You’ll be here with someone else.',
    )
    assert.equal(
      gatheringSentence(gathering([named('Sarah'), unnamed('u1')]), 'here'),
      'You’ll be here with Sarah and someone else.',
    )
    assert.equal(
      gatheringSentence(gathering([unnamed('u1')], 'attended'), 'here'),
      'You were here with someone else.',
    )
  })

  test('nobody to name produces no sentence at all', () => {
    assert.equal(gatheringSentence(gathering([])), '')
  })
})

describe('pathway sentences', () => {
  test('present tense, both still walking it', () => {
    assert.equal(
      pathwaySentence(pathway([named('Emma')])),
      'You’re moving through this with Emma.',
    )
  })

  test('several walkers', () => {
    assert.equal(
      pathwaySentence(pathway([named('Sarah'), named('Maya')])),
      'You’re moving through this with Sarah and Maya.',
    )
  })

  test('a single unnamed walker is someone else', () => {
    assert.equal(
      pathwaySentence(pathway([unnamed('a')])),
      'You’re moving through this with someone else.',
    )
    assert.equal(
      pathwaySentence(pathway([named('Emma'), unnamed('a')])),
      'You’re moving through this with Emma and someone else.',
    )
  })

  test('several unnamed walkers are counted', () => {
    assert.equal(
      pathwaySentence(pathway([named('Emma'), unnamed('a'), unnamed('b')])),
      'You’re moving through this with Emma and 2 other people.',
    )
  })
})

describe('what we never claim', () => {
  const samples = [
    gatheringSentence(gathering([named('Sarah')]), 'here'),
    gatheringSentence(gathering([named('Sarah')], 'attended'), 'here'),
    pathwaySentence(pathway([named('Sarah')])),
  ]

  test('no claim that anyone met, knows or connected', () => {
    for (const s of samples) {
      for (const word of ['met', 'know', 'knows', 'connected', 'friend', 'match']) {
        assert.ok(
          !new RegExp(`\\b${word}\\b`, 'i').test(s),
          `"${s}" must not claim "${word}"`,
        )
      }
    }
  })

  test('no recommendation or networking language', () => {
    for (const s of samples) {
      for (const phrase of ['you may know', 'recommend', 'suggested', 'similar to you']) {
        assert.ok(!s.toLowerCase().includes(phrase), `"${s}" contains "${phrase}"`)
      }
    }
  })
})

// ---------------------------------------------------------------------------

describe('finding a context', () => {
  const contexts = [gathering([named('Sarah')]), pathway([named('Emma')])]

  test('finds the Gathering by id', () => {
    assert.equal(findGatheringContext(contexts, 'ev_1')?.title, 'Thursday EMBODY')
  })

  test('returns null for an unrelated Gathering', () => {
    assert.equal(findGatheringContext(contexts, 'ev_other'), null)
  })

  test('finds the Pathway by id', () => {
    assert.equal(findPathwayContext(contexts, 'pw_1')?.title, 'Life in Alignment')
  })

  test('a context with nobody in it is not a match', () => {
    assert.equal(findGatheringContext([gathering([])], 'ev_1'), null)
  })

  test('a Gathering id never matches a Pathway context', () => {
    assert.equal(findGatheringContext([pathway([named('Emma')])], 'pw_1'), null)
  })
})

describe('contextsInCollective', () => {
  test('keeps only this Collective’s contexts', () => {
    const other = { ...COLLECTIVE, id: 'sp_2', name: 'The Grove' }
    const all = [
      gathering([named('Sarah')]),
      pathway([named('Emma')], { collective: other }),
    ]
    const mine = contextsInCollective(all, 'sp_1')
    assert.equal(mine.length, 1)
    assert.equal(mine[0].kind, 'gathering')
  })
})

// ---------------------------------------------------------------------------

describe('grouping the destination', () => {
  const soon = gathering([named('Sarah')], 'upcoming', { id: 'ev_soon' })
  const past = gathering([named('James')], 'attended', { id: 'ev_past' })
  const walk = pathway([named('Emma')])

  test('splits into coming up, pathways and recent crossings', () => {
    const g = groupContexts([soon, walk, past])
    assert.deepEqual(g.comingUp.map((c) => c.id), ['ev_soon'])
    assert.deepEqual(g.pathways.map((c) => c.id), ['pw_1'])
    assert.deepEqual(g.recent.map((c) => c.id), ['ev_past'])
  })

  test('a group with nothing in it stays empty so the heading can be dropped', () => {
    const g = groupContexts([soon])
    assert.equal(g.pathways.length, 0)
    assert.equal(g.recent.length, 0)
    assert.ok(hasAnyContext(g))
  })

  test('no contexts at all means nothing to show', () => {
    assert.equal(hasAnyContext(groupContexts([])), false)
  })

  test('contexts with nobody in them are dropped', () => {
    assert.equal(hasAnyContext(groupContexts([gathering([])])), false)
  })

  test('the same person may appear in more than one context', () => {
    const sarah = named('Sarah')
    const g = groupContexts([
      gathering([sarah], 'upcoming', { id: 'ev_a' }),
      pathway([sarah]),
    ])
    assert.equal(g.comingUp[0].people[0].id, sarah.id)
    assert.equal(g.pathways[0].people[0].id, sarah.id)
  })

  test('grouping is by shared thing, never by person', () => {
    // Two different people at the same Gathering stay one context.
    const g = groupContexts([gathering([named('Sarah'), named('James')])])
    assert.equal(g.comingUp.length, 1)
    assert.equal(g.comingUp[0].people.length, 2)
  })
})

describe('contextSentence dispatch', () => {
  test('picks the gathering voice for a gathering', () => {
    assert.match(contextSentence(gathering([named('Sarah')])), /You’ll be there/)
  })
  test('picks the pathway voice for a pathway', () => {
    assert.match(contextSentence(pathway([named('Emma')])), /moving through/)
  })
})
