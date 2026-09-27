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
  deriveContexts,
  featuredPeople,
  findGatheringContext,
  findPathwayContext,
  gatheringSentence,
  pathwaySentence,
  primaryCollective,
  reasonSentence,
  splitPeople,
  type PersonRef,
  type SharedGatheringRef,
  type SharedPathwayRef,
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

function sharedGathering(
  over: Partial<SharedGatheringRef> = {},
): SharedGatheringRef {
  return {
    kind: 'gathering',
    id: 'ev_1',
    title: 'Thursday EMBODY',
    starts_at: '2026-10-08T19:00:00',
    basis: 'upcoming',
    collective_id: COLLECTIVE.id,
    ...over,
  }
}

function sharedPathway(over: Partial<SharedPathwayRef> = {}): SharedPathwayRef {
  return {
    kind: 'pathway',
    id: 'pw_1',
    slug: 'life-in-alignment',
    title: 'Life in Alignment',
    collective_id: COLLECTIVE.id,
    crossing_at: '2026-09-20T10:00:00',
    ...over,
  }
}

/** A person carrying whatever they share. */
function person(
  name: string | null,
  shared: (SharedGatheringRef | SharedPathwayRef)[],
  over: Partial<PersonRef> = {},
): PersonRef {
  return {
    id: `u_${name ?? 'quiet'}`,
    display_name: name,
    avatar_url: null,
    collectives: [COLLECTIVE],
    shared,
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
      gatheringSentence([named('Sarah'), named('James')], 'upcoming', 'here'),
      'You’ll be here with Sarah and James.',
    )
  })

  test('upcoming, seen from elsewhere', () => {
    assert.equal(
      gatheringSentence([named('Sarah')], 'upcoming', 'there'),
      'You’ll be there with Sarah.',
    )
  })

  test('attended, on the Gathering’s own page', () => {
    assert.equal(
      gatheringSentence([named('Sarah'), named('James')], 'attended', 'here'),
      'You were here with Sarah and James.',
    )
  })

  test('attended, seen from elsewhere', () => {
    assert.equal(
      gatheringSentence([named('Maya')], 'attended', 'there'),
      'You were there with Maya.',
    )
  })

  test('mixed named and unnamed reads naturally', () => {
    assert.equal(
      gatheringSentence([named('Sarah'), unnamed('a'), unnamed('b')], 'upcoming', 'there'),
      'You’ll be there with Sarah and 2 other people.',
    )
  })

  test('a single unnamed companion reads as company, not a count', () => {
    assert.equal(
      gatheringSentence([unnamed('u1')], 'upcoming', 'here'),
      'You’ll be here with someone else.',
    )
    assert.equal(
      gatheringSentence([named('Sarah'), unnamed('u1')], 'upcoming', 'here'),
      'You’ll be here with Sarah and someone else.',
    )
    assert.equal(
      gatheringSentence([unnamed('u1')], 'attended', 'here'),
      'You were here with someone else.',
    )
  })

  test('nobody to name produces no sentence at all', () => {
    assert.equal(gatheringSentence([], 'upcoming'), '')
  })
})

describe('pathway sentences', () => {
  test('present tense, both still walking it', () => {
    assert.equal(
      pathwaySentence([named('Emma')]),
      'You’re moving through this with Emma.',
    )
  })

  test('several walkers', () => {
    assert.equal(
      pathwaySentence([named('Sarah'), named('Maya')]),
      'You’re moving through this with Sarah and Maya.',
    )
  })

  test('a single unnamed walker is someone else', () => {
    assert.equal(
      pathwaySentence([unnamed('a')]),
      'You’re moving through this with someone else.',
    )
    assert.equal(
      pathwaySentence([named('Emma'), unnamed('a')]),
      'You’re moving through this with Emma and someone else.',
    )
  })

  test('several unnamed walkers are counted', () => {
    assert.equal(
      pathwaySentence([named('Emma'), unnamed('a'), unnamed('b')]),
      'You’re moving through this with Emma and 2 other people.',
    )
  })
})

describe('what we never claim', () => {
  const samples = [
    gatheringSentence([named('Sarah')], 'upcoming', 'here'),
    gatheringSentence([named('Sarah')], 'attended', 'here'),
    pathwaySentence([named('Sarah')]),
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

describe('reasonSentence — leads with the strongest truthful pattern', () => {
  test('repeated past attendance', () => {
    assert.equal(
      reasonSentence(person('Sarah', [
        sharedGathering({ id: 'a', basis: 'attended' }),
        sharedGathering({ id: 'b', basis: 'attended' }),
      ])),
      'You’ve both been showing up to EMBODY.',
    )
  })

  test('past attendance leads even when there is something coming up', () => {
    // The rule from review: never introduce a pair by their diary when
    // they have already been in the same room.
    const sentence = reasonSentence(person('Sarah', [
      sharedGathering({ id: 'a', basis: 'attended' }),
      sharedGathering({ id: 'b', basis: 'upcoming' }),
    ]))
    assert.equal(sentence, 'You’ve both been showing up to EMBODY.')
    assert.ok(!sentence.includes('coming to'), 'must not lead with the plan')
  })

  test('one past room plus a shared path names both', () => {
    assert.equal(
      reasonSentence(person('Sarah', [
        sharedGathering({ basis: 'attended' }),
        sharedPathway(),
      ])),
      'You’ve been in the same room at EMBODY, and you’re on the same path.',
    )
  })

  test('two shared pathways', () => {
    assert.equal(
      reasonSentence(person('Emma', [
        sharedPathway({ id: 'p1' }),
        sharedPathway({ id: 'p2' }),
      ])),
      'You’re both walking the same paths in EMBODY.',
    )
  })

  test('a pathway plus a plan mentions both, path first', () => {
    const sentence = reasonSentence(person('Emma', [
      sharedPathway(),
      sharedGathering({ basis: 'upcoming' }),
    ]))
    assert.equal(
      sentence,
      'You’re on the same path in EMBODY, and you’ll be there together soon.',
    )
    assert.ok(sentence.indexOf('path') < sentence.indexOf('soon'))
  })

  test('only plans is unreachable for a card, and still truthful', () => {
    // A pair with nothing realised never reaches a card — the server
    // will not feature them. The sentence stays honest anyway.
    assert.equal(
      reasonSentence(person('Tara', [
        sharedGathering({ id: 'a', basis: 'upcoming' }),
        sharedGathering({ id: 'b', basis: 'upcoming' }),
      ])),
      'Your paths are about to cross at EMBODY, more than once.',
    )
  })

  test('every card-reachable shape leads with something realised', () => {
    // The five categories, in order. Each sentence must open with what
    // happened or what is underway — never with the diary.
    const shapes: PersonRef[] = [
      person('c1', [sharedGathering({ id: 'a', basis: 'attended' }), sharedGathering({ id: 'b', basis: 'attended' })]),
      person('c2', [sharedGathering({ basis: 'attended' }), sharedPathway()]),
      person('c3', [sharedGathering({ id: 'a', basis: 'attended' }), sharedGathering({ id: 'b', basis: 'upcoming' })]),
      person('c4', [sharedPathway({ id: 'p1' }), sharedPathway({ id: 'p2' })]),
      person('c5', [sharedPathway(), sharedGathering({ basis: 'upcoming' })]),
    ]
    for (const p of shapes) {
      const s = reasonSentence(p)
      assert.ok(
        /^You’ve|^You’re on the same path|^You’re both walking/.test(s),
        `"${s}" should open with realised evidence`,
      )
      assert.ok(!/^You’re both coming to/.test(s))
      assert.ok(!/^Your paths are about to cross/.test(s))
    }
  })

  test('it never leads with a plan when history exists', () => {
    const withHistory = [
      person('A', [sharedGathering({ id: 'x', basis: 'attended' }), sharedGathering({ id: 'y', basis: 'upcoming' })]),
      person('B', [sharedGathering({ id: 'x', basis: 'attended' }), sharedGathering({ id: 'y', basis: 'attended' })]),
      person('C', [sharedGathering({ id: 'x', basis: 'attended' }), sharedPathway()]),
    ]
    for (const p of withHistory) {
      const s = reasonSentence(p)
      assert.ok(!/^You’re both coming to/.test(s), `"${s}" leads with a plan`)
      assert.ok(!/^Your paths are about to cross/.test(s), `"${s}" leads with a plan`)
    }
  })

  test('it does not repeat the shared titles', () => {
    const p = person('Sarah', [
      sharedGathering({ id: 'a', title: 'Thursday EMBODY', basis: 'attended' }),
      sharedGathering({ id: 'b', title: 'Full Moon', basis: 'attended' }),
    ])
    const s = reasonSentence(p)
    assert.ok(!s.includes('Thursday EMBODY'))
    assert.ok(!s.includes('Full Moon'))
  })

  test('it claims nothing about the relationship', () => {
    const samples = [
      reasonSentence(person('S', [sharedGathering({ id: 'a', basis: 'attended' }), sharedGathering({ id: 'b', basis: 'attended' })])),
      reasonSentence(person('S', [sharedGathering({ basis: 'attended' }), sharedPathway()])),
      reasonSentence(person('S', [sharedPathway({ id: 'p1' }), sharedPathway({ id: 'p2' })])),
      reasonSentence(person('S', [sharedGathering({ id: 'a', basis: 'upcoming' }), sharedGathering({ id: 'b', basis: 'upcoming' })])),
    ]
    for (const s of samples) {
      for (const word of ['met', 'know', 'knows', 'connected', 'friend', 'match', 'similar']) {
        assert.ok(
          !new RegExp(`\\b${word}\\b`, 'i').test(s),
          `"${s}" must not claim "${word}"`,
        )
      }
    }
  })

  test('no evidence means no sentence', () => {
    assert.equal(reasonSentence(person('Nobody', [])), '')
  })
})

describe('primaryCollective', () => {
  test('picks the collective most of the evidence belongs to', () => {
    const grove = { id: 'sp_2', slug: 'the-grove', name: 'The Grove', timezone: 'Australia/Melbourne' }
    const p = person('Sarah', [
      sharedGathering({ id: 'a', collective_id: grove.id }),
      sharedGathering({ id: 'b', collective_id: grove.id }),
      sharedPathway({ collective_id: COLLECTIVE.id }),
    ], { collectives: [COLLECTIVE, grove] })
    assert.equal(primaryCollective(p)?.name, 'The Grove')
  })

  test('null when a person shares no collective', () => {
    assert.equal(primaryCollective(person('X', [], { collectives: [] })), null)
  })
})

describe('featuredPeople', () => {
  const p = (n: string) => person(n, [sharedGathering()])

  test('takes exactly the count the server chose', () => {
    const payload = {
      people: [p('A'), p('B'), p('C'), p('D')],
      featured_count: 3,
      truncated: false,
    }
    assert.deepEqual(featuredPeople(payload).map((x) => x.display_name), ['A', 'B', 'C'])
  })

  test('a count of zero features nobody even when people exist', () => {
    const payload = { people: [p('A')], featured_count: 0, truncated: false }
    assert.deepEqual(featuredPeople(payload), [])
  })

  test('never exceeds the people it was given', () => {
    const payload = { people: [p('A')], featured_count: 3, truncated: false }
    assert.equal(featuredPeople(payload).length, 1)
  })
})

describe('deriveContexts — the in-context view', () => {
  test('one shared gathering, two people', () => {
    const people = [
      person('Sarah', [sharedGathering({ id: 'ev_1' })]),
      person('James', [sharedGathering({ id: 'ev_1' })]),
    ]
    const contexts = deriveContexts(people)
    assert.equal(contexts.length, 1)
    assert.deepEqual(contexts[0].people.map((p) => p.display_name), ['James', 'Sarah'])
  })

  test('unnamed people are counted here even though they get no card', () => {
    const people = [
      person('Sarah', [sharedGathering({ id: 'ev_1' })]),
      person(null, [sharedGathering({ id: 'ev_1' })]),
      { ...person(null, [sharedGathering({ id: 'ev_1' })]), id: 'u_quiet2' },
    ]
    const ctx = deriveContexts(people)[0]
    assert.equal(ctx.people.length, 3)
    assert.equal(
      gatheringSentence(ctx.people, 'upcoming', 'here'),
      'You’ll be here with Sarah and 2 other people.',
    )
  })

  test('named people sort ahead of unnamed ones', () => {
    const people = [
      person(null, [sharedGathering({ id: 'ev_1' })]),
      person('Sarah', [sharedGathering({ id: 'ev_1' })]),
    ]
    assert.equal(deriveContexts(people)[0].people[0].display_name, 'Sarah')
  })

  test('one person sharing two things yields two contexts', () => {
    const people = [person('Sarah', [sharedGathering({ id: 'ev_1' }), sharedPathway()])]
    assert.equal(deriveContexts(people).length, 2)
  })

  test('finds a gathering context by id', () => {
    const people = [person('Sarah', [sharedGathering({ id: 'ev_9' })])]
    assert.equal(findGatheringContext(people, 'ev_9')?.title, 'Thursday EMBODY')
    assert.equal(findGatheringContext(people, 'ev_other'), null)
  })

  test('finds a pathway context by id', () => {
    const people = [person('Emma', [sharedPathway({ id: 'pw_9' })])]
    assert.equal(findPathwayContext(people, 'pw_9')?.title, 'Life in Alignment')
  })

  test('a gathering id never matches a pathway', () => {
    const people = [person('Emma', [sharedPathway({ id: 'pw_1' })])]
    assert.equal(findGatheringContext(people, 'pw_1'), null)
  })

  test('contextsInCollective keeps only that collective', () => {
    const grove = { id: 'sp_2', slug: 'the-grove', name: 'The Grove', timezone: 'Australia/Melbourne' }
    const people = [
      person('Sarah', [sharedGathering({ id: 'a' })]),
      person('Emma', [sharedPathway({ collective_id: grove.id })], {
        collectives: [grove],
      }),
    ]
    const mine = contextsInCollective(people, COLLECTIVE.id)
    assert.equal(mine.length, 1)
    assert.equal(mine[0].kind, 'gathering')
  })

  test('contextSentence dispatches on kind', () => {
    const g = deriveContexts([person('Sarah', [sharedGathering()])])[0]
    const p = deriveContexts([person('Emma', [sharedPathway()])])[0]
    assert.match(contextSentence(g), /You’ll be there/)
    assert.match(contextSentence(p), /moving through/)
  })
})
