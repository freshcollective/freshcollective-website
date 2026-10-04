import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const read = (rel: string) => readFileSync(new URL(rel, import.meta.url), 'utf8')
const codeOnly = (rel: string) =>
  read(rel)
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, '')
    .replace(/(^|[^:])\/\/.*$/gm, '$1')

const PAGE = '../app/ways-to-connect/page.tsx'
const OPTIN = '../components/connections/WaysToConnectOptIn.tsx'
const EMPTY = '../components/connections/WaysToConnectEmptyState.tsx'
const SETTINGS = '../components/settings/ProfileForm.tsx'
const HEADER = '../components/layout/WorldHeader.tsx'
const DASHBOARD = '../app/dashboard/page.tsx'

describe('participation decides the page, not whether the feature exists', () => {
  const page = codeOnly(PAGE)

  test('the page reads the member’s own setting', () => {
    assert.match(page, /const me = await getMe\(\)/)
    assert.match(page, /ways_to_connect_enabled !== true/)
  })

  test('opted out renders the opt-in state', () => {
    assert.match(page, /if \(optedOut\) \{[\s\S]{0,120}<WaysToConnectOptIn \/>/)
  })

  test('a signed-out visitor is not treated as opted out', () => {
    // This route has no auth redirect of its own, so getMe() returns
    // null for a stranger. Reading that as a declined setting showed
    // them a page about *their* participation being off, with a CTA
    // that would 401 — confidently wrong, rather than merely unhelpful.
    assert.match(page, /const signedIn = me !== null/)
    assert.match(page, /const optedOut = signedIn && /)
  })

  test('participation is read before the recommendations', () => {
    // The API answers "nothing" for an opted-out member — the same
    // answer as "nobody qualifies" — so the order is what keeps the two
    // pages distinguishable.
    assert.ok(
      page.indexOf('ways_to_connect_enabled') < page.indexOf('getWaysToConnect()'),
      'the setting must be known before the recommendations are fetched',
    )
  })

  test('no recommendations are requested for somebody who declined them', () => {
    assert.match(page, /optedOut\s*\n?\s*(\/\/[^\n]*\n\s*)*\?\s*null/)
    assert.match(page, /:\s*await getWaysToConnect\(\)/)
  })

  test('the route is still gated only on the launch flag', () => {
    // Participation must not 404 the route — that is what would leave a
    // member with no way back to the feature.
    assert.match(page, /if \(!\(await waysToConnectVisible\(\)\)\) notFound\(\)/)

    // Exactly one gate. Checking only the text *before* the first
    // ``notFound()`` let a second one be added after it, which is
    // precisely the regression this test exists to stop.
    assert.equal(
      (page.match(/notFound\(\)/g) ?? []).length, 1,
      'the page must have one gate, and it must be the launch flag',
    )
    for (const line of page.split('\n')) {
      if (!line.includes('notFound')) continue
      assert.ok(
        !line.includes('ways_to_connect_enabled'),
        `the preference must never 404 the route: ${line.trim()}`,
      )
    }
  })
})

describe('the two empty-looking states say different things', () => {
  const optIn = read(OPTIN)
  const empty = read(EMPTY)

  test('opted out says it is turned off', () => {
    assert.match(optIn, /Ways to Connect is currently turned off/)
  })

  test('opted in with nobody yet keeps its own copy', () => {
    assert.match(empty, /Connection grows through shared experiences/)
    assert.match(empty, /One place to start/)
  })

  test('neither borrows the other’s wording', () => {
    assert.ok(!empty.includes('turned off'), 'the empty state must not imply a setting')
    assert.ok(
      !optIn.includes('Connection grows through shared experiences'),
      'the opt-in state must not imply we simply found nobody',
    )
  })

  test('they are different components, chosen by different conditions', () => {
    const page = codeOnly(PAGE)
    assert.match(page, /<WaysToConnectOptIn \/>/)
    assert.match(page, /<WaysToConnectEmptyState/)
    assert.ok(page.indexOf('<WaysToConnectOptIn') < page.indexOf('<WaysToConnectEmptyState'))
  })
})

describe('turning it on', () => {
  const src = codeOnly(OPTIN)

  test('it uses the canonical settings endpoint', () => {
    // The same PATCH Account Settings issues. A second write path would
    // be a second place for the semantics to drift.
    assert.match(src, /apiUrl\('\/api\/auth\/me'\)/)
    assert.match(src, /method: 'PATCH'/)
    assert.match(src, /ways_to_connect_enabled: true/)
    assert.match(codeOnly(SETTINGS), /apiUrl\('\/api\/auth\/me'\)/)
  })

  test('it sends only the one field', () => {
    // Sending the whole profile from here would let a stale form value
    // overwrite something the member changed elsewhere.
    const body = src.slice(src.indexOf('JSON.stringify'), src.indexOf('})', src.indexOf('JSON.stringify')))
    assert.ok(!body.includes('is_public'), 'must not touch profile visibility')
    assert.ok(!body.includes('name'), 'must not touch the name')
  })

  test('the CTA says what it does', () => {
    assert.match(read(OPTIN), /Turn on Ways to Connect/)
  })

  test('it re-reads from the server rather than switching the view locally', () => {
    // What appears next is computed server-side and may well be the
    // empty state.
    assert.match(src, /router\.refresh\(\)/)
    assert.ok(!/setParticipating|useState\(true\)/.test(src))
  })

  test('a failed save reports and does not pretend to succeed', () => {
    assert.match(src, /if \(!res\.ok\)/)
    assert.match(src, /setError\(/)
    const ok = src.indexOf('if (!res.ok)')
    const refresh = src.indexOf('router.refresh()')
    assert.ok(ok < refresh, 'the failure branch must come first')
  })

  test('the button is disabled while saving', () => {
    assert.match(src, /disabled=\{saving\}/)
  })

  test('it points at Settings without inventing a help page', () => {
    assert.match(src, /href="\/settings\/profile"/)
    // Comment-stripped: the component explains in a comment *why* there
    // is no "Learn more", and a raw read fails on the explanation.
    assert.ok(
      !/Learn more/.test(codeOnly(OPTIN)),
      'no link to a surface that does not exist',
    )
  })
})

describe('the privacy copy', () => {
  // Comment-stripped, like everywhere else in this suite: the
  // component's own docstring discusses the eligibility rules in the
  // course of explaining why they are kept out of the copy, and a raw
  // read fails on the reasoning rather than on a leak. JSX text
  // survives stripping, so the copy itself is still fully checked.
  const copy = codeOnly(OPTIN)

  test('it names the signals in plain terms', () => {
    assert.match(copy, /Gathering you both attended/)
    assert.match(copy, /Pathway you.{1,3}re\s*\n?\s*both exploring/)
  })

  test('it says Collective membership alone is not a signal', () => {
    assert.match(copy, /same Collective is never\s*\n?\s*enough on its own/)
  })

  test('it says contact details are never revealed', () => {
    assert.match(copy, /never reveal your email address, phone number/)
  })

  test('it says messaging requires a mutual hello', () => {
    assert.match(copy, /until you\s*\n?\s*have both said hello/)
  })

  test('it says the choice is reversible', () => {
    assert.match(copy, /turn this off again at any\s*\n?\s*time/)
  })

  test('it does not dump the eligibility algorithm', () => {
    for (const leak of [
      'two signals', 'realised', 'category', 'rotation',
      'MAX_PEOPLE', 'day_index', 'eligib',
    ]) {
      assert.ok(
        !copy.toLowerCase().includes(leak.toLowerCase()),
        `member-facing copy must not expose: ${leak}`,
      )
    }
  })
})

describe('navigation never depends on participation', () => {
  test('the header gates only on the launch flag', () => {
    const src = codeOnly(HEADER)
    assert.match(src, /if \(waysToConnectOn\) items\.push\(\{ href: '\/ways-to-connect'/)
    assert.match(src, /if \(waysToConnectOn\) items\.push\(\{ href: '\/messages'/)
    assert.ok(!src.includes('ways_to_connect_enabled'))
  })

  test('the Your World doorway gates only on the launch flag', () => {
    const src = codeOnly(DASHBOARD)
    assert.match(src, /waysToConnectOn && \(/)
    assert.ok(
      !src.includes('ways_to_connect_enabled'),
      'the tile must not disappear when a member opts out',
    )
  })

  test('nothing in the nav or shells reads the preference', () => {
    for (const rel of [
      '../components/layout/SiteShell.tsx',
      '../components/layout/WorldShell.tsx',
      '../components/layout/MobileNav.tsx',
      '../components/layout/PublicHeader.tsx',
    ]) {
      assert.ok(
        !codeOnly(rel).includes('ways_to_connect_enabled'),
        `${rel} must not gate on participation`,
      )
    }
  })
})

describe('the Settings toggle still owns the setting', () => {
  const src = codeOnly(SETTINGS)

  test('it is still there and still the canonical Switch', () => {
    assert.match(src, /<Switch\s+checked=\{waysToConnect\}/)
    assert.match(src, /aria-label="Include me in Ways to Connect"/)
  })

  test('it reflects the stored value rather than a hardcoded default', () => {
    assert.match(src, /profile\.ways_to_connect_enabled/)
  })

  test('it can still turn participation off', () => {
    assert.match(src, /ways_to_connect_enabled: waysToConnect/)
    assert.match(src, /onChange=\{\(\) => setWaysToConnect\(!waysToConnect\)\}/)
  })
})
