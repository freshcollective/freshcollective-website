/**
 * A failed request must never look like a finished term.
 *
 * "Reserve your regular sessions" rendered nothing whenever its first
 * request did not come back cleanly. A 403, a 500 and a dropped
 * connection all set the same state as "this term has nothing left to
 * reserve" — and that state renders null. An EMBODY member with a valid
 * term pass, who could see "Your access" and book individual sessions,
 * went looking for a control the page had silently declined to draw.
 *
 * These cover the decision — which message, which action, and whether
 * the card appears at all — plus the wiring that connects it to the
 * component. There is no DOM renderer in this project (node:test only,
 * no testing-library or jsdom), so the component's own behaviour is
 * pinned by reading its source: that it has a distinct load_error
 * phase, that only an empty pattern list returns null, and that the
 * retry re-runs the request.
 */

import { readFileSync } from 'node:fs'
import { describe, test } from 'node:test'
import assert from 'node:assert/strict'

import {
  classifyLoadFailure,
  isVerificationFailure,
  nothingToReserveNotice,
  termHasEnded,
} from './regularSessions.ts'

const VERIFY_403 = {
  detail:
    'Please verify your email to continue. Check the link we sent to '
    + 'your inbox, or request a new one from your dashboard.',
}

const COMPONENT = readFileSync(
  'src/app/spaces/[slug]/gathering-series/[series-slug]/RegularSessions.tsx',
  'utf8',
)

function codeOnly(src: string): string {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/\{\s*\/\*[\s\S]*?\*\/\s*\}/g, '')
    .replace(/(^|[^:])\/\/.*$/gm, '$1')
}
const CODE = codeOnly(COMPONENT)

// ---------------------------------------------------------------------------
// 1 · An empty term stays silent — the one outcome that should
// ---------------------------------------------------------------------------

describe('an empty session list is still silent', () => {
  test('only an empty pattern list reaches the silent state', () => {
    assert.match(
      CODE,
      /patterns\.length === 0\s*\?\s*\{ kind: 'unavailable' \}/,
      'the empty-list case no longer maps to the silent state',
    )
  })

  test('nothing renders the member a blank space any more', () => {
    // Previously 'unavailable' returned null. A member with access was
    // shown nothing at all, which is why the control looked absent.
    const nulls = CODE.match(/if \(phase\.kind === '(\w+)'\) return null/g) ?? []
    assert.deepEqual(nulls, [], `a phase still renders nothing: ${nulls.join(' | ')}`)
  })

  test('the empty case explains itself instead of disappearing', () => {
    assert.match(CODE, /phase\.kind === 'unavailable'/)
    assert.match(CODE, /nothingToReserveNotice\(/)
    assert.match(CODE, /notice\.headline/)
    assert.match(CODE, /notice\.body/)
  })

  test('a failed request no longer borrows the silent state', () => {
    // The defect: !res.ok and catch both set 'unavailable'.
    assert.ok(
      !/!res\.ok[\s\S]{0,160}?setPhase\(\{ kind: 'unavailable' \}\)/.test(CODE),
      'a non-OK response still sets the silent state',
    )
    assert.ok(
      !/catch[\s\S]{0,120}?setPhase\(\{ kind: 'unavailable' \}\)/.test(CODE),
      'a thrown request still sets the silent state',
    )
  })
})

// ---------------------------------------------------------------------------
// 2 · Verification errors
// ---------------------------------------------------------------------------

describe('a confirmed verification response guides the member', () => {
  test('it is recognised', () => {
    assert.equal(isVerificationFailure(403, VERIFY_403), true)
  })

  test('it explains what to do and links the existing resend flow', () => {
    const f = classifyLoadFailure(403, VERIFY_403)
    assert.equal(f.kind, 'verification')
    assert.match(f.headline, /verify your email/i)
    // The dashboard is where VerifyEmailBanner's resend action already
    // lives, and where the server's own 403 text points.
    assert.equal(f.actionHref, '/dashboard')
    assert.ok(f.actionLabel)
    // Retrying cannot fix an unverified address, so no retry is offered.
    assert.equal(f.retryable, false)
  })

  test('it reassures them their term is intact', () => {
    assert.match(classifyLoadFailure(403, VERIFY_403).body, /unaffected/i)
  })

  test('an unrecognised 403 does NOT claim to be a verification problem', () => {
    // Area access also 403s here. Sending someone to check their inbox
    // when they simply cannot reach this Area wastes their time.
    for (const body of [
      { detail: 'You do not have access to this Area.' },
      { detail: '' },
      null,
      { detail: 42 },
      {},
    ]) {
      assert.equal(isVerificationFailure(403, body), false, JSON.stringify(body))
      assert.equal(classifyLoadFailure(403, body).kind, 'generic', JSON.stringify(body))
    }
  })

  test('the verification phrase alone, on another status, is not trusted', () => {
    assert.equal(isVerificationFailure(500, VERIFY_403), false)
    assert.equal(isVerificationFailure(null, VERIFY_403), false)
  })
})

// ---------------------------------------------------------------------------
// 3 · Server and network failures
// ---------------------------------------------------------------------------

describe('server and network failures are visible and retryable', () => {
  for (const status of [500, 502, 503, 504, 404, 422]) {
    test(`${status} shows a retryable message`, () => {
      const f = classifyLoadFailure(status, { detail: 'boom' })
      assert.equal(f.kind, 'generic')
      assert.equal(f.retryable, true)
      assert.ok(f.headline.length > 0 && f.body.length > 0)
    })
  }

  test('a dropped connection (no status) is retryable', () => {
    const f = classifyLoadFailure(null, null)
    assert.equal(f.kind, 'generic')
    assert.equal(f.retryable, true)
  })

  test('an expired session offers sign-in rather than a pointless retry', () => {
    const f = classifyLoadFailure(401, { detail: 'Not authenticated.' })
    assert.equal(f.kind, 'signed_out')
    assert.equal(f.actionHref, '/login')
    assert.equal(f.retryable, false)
  })

  test('no raw server detail is ever shown to the member', () => {
    const leaky = {
      detail:
        'psycopg2.OperationalError: FATAL password authentication failed '
        + 'for user "fc" at /app/app/services/regular_sessions.py line 241',
    }
    for (const status of [400, 403, 404, 500, 503]) {
      const f = classifyLoadFailure(status, leaky)
      const shown = `${f.headline} ${f.body} ${f.actionLabel ?? ''}`
      for (const fragment of ['psycopg2', 'FATAL', 'password', '/app/', 'line 241']) {
        assert.ok(
          !shown.includes(fragment),
          `${status} leaked "${fragment}" to the member`,
        )
      }
      assert.ok(!shown.includes(leaky.detail), `${status} echoed the raw detail`)
    }
  })

  test('every failure says something, whatever the shape of the body', () => {
    for (const body of [null, undefined, '', 0, [], { detail: null }, 'text']) {
      for (const status of [null, 400, 403, 418, 500]) {
        const f = classifyLoadFailure(status, body)
        assert.ok(f.headline.trim(), `empty headline for ${status}/${JSON.stringify(body)}`)
        assert.ok(f.body.trim(), `empty body for ${status}/${JSON.stringify(body)}`)
      }
    }
  })
})

// ---------------------------------------------------------------------------
// 4 · Successful retry
// ---------------------------------------------------------------------------

describe('retry re-runs the request and can recover', () => {
  test('the card offers a retry when, and only when, retrying could work', () => {
    assert.equal(classifyLoadFailure(500, null).retryable, true)
    assert.equal(classifyLoadFailure(null, null).retryable, true)
    assert.equal(classifyLoadFailure(403, VERIFY_403).retryable, false)
    assert.equal(classifyLoadFailure(401, null).retryable, false)
  })

  test('the retry button is wired to re-run the load', () => {
    assert.match(CODE, /onClick=\{\(\) => setLoadAttempt\(\(n\) => n \+ 1\)\}/)
    // ...and the effect must actually depend on that counter, or the
    // button would re-render the card without re-requesting anything.
    assert.match(CODE, /\}, \[base, loadAttempt\]\)/)
  })

  test('the retry is only offered on retryable failures', () => {
    assert.match(CODE, /failure\.retryable && \(/)
  })

  test('a recovering load leaves the error state behind', () => {
    // The effect resets to 'loading' on each attempt, so a successful
    // retry cannot leave the previous error on screen.
    assert.match(CODE, /setPhase\(\{ kind: 'loading' \}\)/)
    assert.match(CODE, /\{ kind: 'choosing' \}/)
  })
})

// ---------------------------------------------------------------------------
// 5 · The card is reachable at all
// ---------------------------------------------------------------------------

describe('the failure card is actually rendered', () => {
  test('the component renders the classified failure, not its own copy', () => {
    assert.match(CODE, /phase\.kind === 'load_error'/)
    assert.match(CODE, /failure\.headline/)
    assert.match(CODE, /failure\.body/)
  })

  test('it never renders the server body', () => {
    assert.ok(
      !/\{\s*(body|detail)\s*\}/.test(CODE),
      'the component renders a raw server field',
    )
  })
})


// ---------------------------------------------------------------------------
// 6 · Nothing to reserve — honest, never blank, and quiet when finished
// ---------------------------------------------------------------------------

describe('an empty listing tells a member with access something', () => {
  test('the notice says what is true and what still works', () => {
    const n = nothingToReserveNotice()
    assert.equal(n.headline, 'No regular sessions available to reserve')
    assert.match(n.body, /aren't any upcoming sessions available for regular booking/i)
    assert.match(n.body, /check the schedule for individual sessions/i)
  })

  test('it takes no arguments and cannot branch on a count', () => {
    // An earlier draft varied the wording on remaining_occurrence_count
    // > 0 — a state the API cannot produce, because the endpoint builds
    // the count and the patterns from the same event list and
    // build_patterns drops nothing. Unreachable code with a test on it
    // is how unreachable code survives, so both are gone.
    //
    // Asserted against the source, not Function.length: a defaulted
    // parameter reports length 0, so the obvious check passes while
    // the parameter quietly comes back.
    const lib = codeOnly(readFileSync('src/lib/regularSessions.ts', 'utf8'))
    const fn = lib.slice(lib.indexOf('export function nothingToReserveNotice'))
    const signature = fn.slice(0, fn.indexOf(')') + 1)
    assert.match(signature, /nothingToReserveNotice\(\)/, `signature: ${signature}`)
    const body = fn.slice(0, fn.indexOf('\n}'))
    assert.ok(!/remainingOccurrenceCount/.test(body), 'the count parameter is back')
    assert.ok(!/\bif\s*\(/.test(body), 'the notice branches again')
  })

  test('it never claims a reservation happened', () => {
    const { headline, body } = nothingToReserveNotice()
    for (const claim of [/reserved/i, /booked\b/i, /confirmed/i]) {
      assert.ok(!claim.test(`${headline} ${body}`), `${claim} reads as a booking`)
    }
  })

  test('the component renders it rather than returning null', () => {
    assert.match(CODE, /nothingToReserveNotice\(\)/)
    assert.match(CODE, /notice\.headline/)
    assert.match(CODE, /notice\.body/)
  })
})

describe('a finished term stays quiet', () => {
  const NOW = new Date('2026-10-13T00:00:00Z')

  test('an end date in the past counts as finished', () => {
    assert.equal(termHasEnded('2026-09-30T10:00:00Z', NOW), true)
  })

  test('an end date still ahead does not', () => {
    assert.equal(termHasEnded('2026-12-01T10:00:00Z', NOW), false)
  })

  test('no end date is NOT treated as finished', () => {
    // ends_at is nullable by design — the model keeps it null for an
    // ongoing weekly Series. Reading null as "finished" would restore
    // the silence this notice exists to end, on exactly the Series
    // least likely to have been tidied up.
    for (const absent of [null, undefined, '']) {
      assert.equal(termHasEnded(absent, NOW), false, String(absent))
    }
  })

  test('an unparseable date is not treated as finished', () => {
    assert.equal(termHasEnded('not-a-date', NOW), false)
  })

  test('the component suppresses the notice only for a finished term', () => {
    assert.match(CODE, /if \(termHasEnded\(seriesEndsAt\)\) return null/)
  })

  test('the page supplies the end date', () => {
    const page = codeOnly(
      readFileSync('src/app/spaces/[slug]/gathering-series/[series-slug]/page.tsx', 'utf8'))
    assert.match(page, /seriesEndsAt=\{detail\.ends_at\}/)
  })
})
