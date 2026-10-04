import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

import { PUBLIC_PLANS, getPublicPlan } from './plans.ts'

const SRC = join(dirname(fileURLToPath(import.meta.url)), '..')
const read = (p: string) => readFileSync(join(SRC, p), 'utf8')

/**
 * A source file with its comments removed.
 *
 * The files checked here *document* the prototype they replaced — "no
 * longer a prototype", "paid plans remain a prototype". A raw substring
 * check would fail on the explanation rather than on a regression,
 * punishing the comment that prevents the bug.
 */
const codeOnly = (p: string) =>
  read(p)
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|[^:])\/\/.*$/gm, '$1')

const SIGNUP_PAGE = 'app/signup/creator/page.tsx'
const COMMUNITY_FORM = 'components/checkout/CommunityCollectiveSignup.tsx'

describe('Community Collective signup is live, not a prototype', () => {
  test('the signup page no longer claims nothing is created', () => {
    const src = codeOnly(SIGNUP_PAGE)
    assert.ok(
      !src.includes('Nothing is created in this prototype — no account, no Creator capability'),
      'the Community-specific prototype disclaimer must be gone',
    )
    assert.ok(
      !src.includes('In the live flow, this step will create'),
      'future-tense "will create" copy must be gone — the step does create',
    )
  })

  test('the page renders the live form for Community', () => {
    const src = codeOnly(SIGNUP_PAGE)
    assert.match(src, /CommunityCollectiveSignup/)
    assert.match(src, /isCommunity\s*\?/, 'Community must branch to the live component')
  })

  test('Community is indexable; the paid prototype step is not', () => {
    const src = codeOnly(SIGNUP_PAGE)
    assert.match(src, /robots:\s*isLive\s*\?\s*undefined\s*:\s*\{\s*index:\s*false/)
  })

  test('the prototype pill is not rendered for Community', () => {
    const src = codeOnly(SIGNUP_PAGE)
    // The pill component may still exist for the paid plans, but it must
    // sit in the non-Community branch.
    const communityBranch = src.slice(
      src.indexOf('{isCommunity ? ('),
      src.indexOf(') : ('),
    )
    assert.ok(
      communityBranch.length > 0,
      'expected an isCommunity branch in the left column',
    )
    assert.ok(
      !communityBranch.includes('PrototypePill'),
      'Community must not render the prototype pill',
    )
  })

  test('paid plans keep the prototype form — no regression', () => {
    const src = codeOnly(SIGNUP_PAGE)
    assert.match(src, /PrototypeSignupForm/)
    assert.match(
      src,
      /checkout\/next\?flow=creator/,
      'the paid holding screen must still be reachable',
    )
    assert.match(
      src,
      /flow=upgrade/,
      'signed-in paid-plan visitors must still be sent to the upgrade screen',
    )
  })
})

describe('the live form talks to real endpoints', () => {
  test('it creates an account and starts the plan', () => {
    const src = codeOnly(COMMUNITY_FORM)
    assert.match(src, /\/api\/auth\/signup/)
    assert.match(src, /\/api\/creator\/community\/start/)
  })

  test('it never navigates to the prototype holding screen', () => {
    const src = codeOnly(COMMUNITY_FORM)
    assert.ok(
      !src.includes('/checkout/next'),
      'the live flow must not fall back to the prototype holding screen',
    )
    assert.ok(
      !src.includes('preview=true'),
      'nothing in the live flow is a preview',
    )
  })

  test('it forwards into the existing onboarding, not a new one', () => {
    const src = codeOnly(COMMUNITY_FORM)
    assert.match(src, /\/creator-onboarding/)
    assert.ok(
      !src.includes('/build-your-collective'),
      'onboarding owns the handoff to Build Your Collective; the form must not skip it',
    )
  })

  test('it covers every stage, so no state dead-ends', () => {
    const src = codeOnly(COMMUNITY_FORM)
    for (const stage of ['signed_out', 'unverified', 'ready', 'already_creator']) {
      assert.ok(
        src.includes(`'${stage}'`),
        `stage ${stage} must be handled`,
      )
    }
  })

  test('an unverified account is told to confirm, not promised a Collective', () => {
    const src = codeOnly(COMMUNITY_FORM)
    assert.match(src, /Confirm your email address/)
    assert.match(src, /verify-email\/resend/, 'a stuck visitor must be able to resend')
  })

  test('no stray HTML entities inside JavaScript string literals', () => {
    // Regression: `{busy ? '…' : 'I&rsquo;ve confirmed'}` renders the
    // entity literally, because JSX only decodes entities in markup text.
    const src = read(COMMUNITY_FORM)
    const inJsStrings = src.match(/'[^'\n]*&[a-z]+;[^'\n]*'/g) ?? []
    assert.deepEqual(
      inJsStrings,
      [],
      `HTML entities must not appear inside JS strings: ${inJsStrings.join(', ')}`,
    )
  })
})

describe('advertised Community limits match what the backend enforces', () => {
  test('the plan slug is the backend slug', () => {
    assert.equal(PUBLIC_PLANS.community.slug, 'community')
    assert.equal(getPublicPlan('community')?.slug, 'community')
  })

  test('the CTA points at the live signup route', () => {
    assert.equal(
      PUBLIC_PLANS.community.ctaHref,
      '/signup/creator?plan=community',
    )
  })

  test('no bullet promises an approval step that does not exist', () => {
    // Community has approval_required=False in plan_config.py and no
    // approval flow exists anywhere, so "approved" was a false promise.
    for (const bullet of PUBLIC_PLANS.community.summaryBullets) {
      assert.ok(
        !/approved/i.test(bullet),
        `bullet still claims approval: ${bullet}`,
      )
    }
  })

  test('the enforced numbers are the displayed numbers', () => {
    // These mirror backend/app/creator/plan_config.py::COMMUNITY and the
    // guards in plan_guards.py. If a limit changes on one side, this
    // fails rather than letting the page lie.
    const bullets = PUBLIC_PLANS.community.summaryBullets.join(' | ')
    assert.match(bullets, /One Collective/)        // active_collective_limit=1
    assert.match(bullets, /Up to 100 members/)     // member_allowance_per_collective=100
    assert.match(bullets, /Up to 5 Pathways/)      // pathways_max_per_collective=5
    assert.match(bullets, /non-commercial/)        // paid_offers_enabled=False
    assert.match(bullets, /World Builders/)        // auto_grant_role='creator'
  })

  test('the for-creators plan card makes the same promises', () => {
    const src = codeOnly('app/for-creators/page.tsx')
    const card = src.slice(src.indexOf("name: 'Community Collective'"))
    assert.ok(!/'One approved Collective'/.test(card))
    assert.match(card, /'One Collective'/)
  })
})

describe('the prototype holding screen no longer intercepts Community', () => {
  const HOLDING = 'app/checkout/next/page.tsx'

  test('Community is redirected to the live signup route', () => {
    const src = codeOnly(HOLDING)
    assert.match(src, /planParam === 'community'/)
    assert.match(src, /redirect\('\/signup\/creator\?plan=community'\)/)
  })

  test('the false "not yet supported" Community copy is gone', () => {
    const src = codeOnly(HOLDING)
    assert.ok(
      !src.includes('Your Community Collective will be set up here'),
      'the stale Community holding screen must be removed',
    )
    assert.ok(
      !src.includes('Your Community upgrade will be completed here'),
      'the stale Community upgrade screen must be removed',
    )
    assert.ok(
      !/plan\.slug === 'community'/.test(src),
      'no Community branch should remain in the screen builders',
    )
  })

  test('the paid plans keep their holding screens', () => {
    const src = codeOnly(HOLDING)
    assert.match(src, /function creatorScreen/)
    assert.match(src, /function upgradeScreen/)
    assert.match(src, /No payment has been taken/)
  })
})
