import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import { PAYOUTS_HREF, payoutSetupCard, payoutReadyHeadline } from './payoutSetupCard.ts'
import type { CreatorStripeConnectStatus } from '../types/platform.ts'

const read = (rel: string) => readFileSync(new URL(rel, import.meta.url), 'utf8')
const codeOnly = (rel: string) =>
  read(rel)
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, '')
    .replace(/(^|[^:])\/\/.*$/gm, '$1')

const STUDIO = '../app/creator-studio/page.tsx'
const BILLING = '../app/creator-studio/billing/page.tsx'
const CARD = '../app/creator-studio/PayoutSetupCard.tsx'

function status(
  state: string,
  extra: Partial<CreatorStripeConnectStatus> = {},
): CreatorStripeConnectStatus {
  return {
    connected: state !== 'not_started',
    state,
    stripe_mode: 'test',
    stripe_account_id: state === 'not_started' ? null : 'acct_x',
    transfers_status: null,
    transfers_status_codes: [],
    payouts_status: null,
    payouts_status_codes: [],
    transfers_enabled: false,
    payouts_enabled: false,
    details_submitted: false,
    requirements: [],
    requirements_deadline: null,
    action_required: false,
    external_account_count: 0,
    payout_interval: null,
    payout_delay_days: null,
    connect_routing_enabled: false,
    ...extra,
  } as CreatorStripeConnectStatus
}

describe('who sees the card', () => {
  test('a paid-capable creator with no Stripe sees it', () => {
    const view = payoutSetupCard(true, status('not_started'))
    assert.ok(view)
    assert.equal(view.heading, 'Set up payouts')
  })

  test('Community sees nothing', () => {
    assert.equal(payoutSetupCard(false, status('not_started')), null)
    assert.equal(payoutSetupCard(false, status('action_required')), null)
  })

  test('a ready creator is not nagged', () => {
    assert.equal(payoutSetupCard(true, status('ready')), null)
  })

  test('a ready creator with routing already live is not nagged either', () => {
    assert.equal(
      payoutSetupCard(true, status('ready', { connect_routing_enabled: true })),
      null,
    )
  })

  test('a failed status fetch shows nothing rather than guessing', () => {
    // A prompt built on an unanswered question is worse than no prompt.
    assert.equal(payoutSetupCard(true, null), null)
    assert.equal(payoutSetupCard(true, undefined), null)
  })
})

describe('copy by Connect state', () => {
  test('not_started → Set up payouts, calm', () => {
    const v = payoutSetupCard(true, status('not_started'))!
    assert.equal(v.heading, 'Set up payouts')
    assert.equal(v.ctaLabel, 'Set up payouts')
    assert.equal(v.tone, 'neutral')
  })

  for (const state of ['onboarding', 'verifying']) {
    test(`${state} → Finish payout setup`, () => {
      const v = payoutSetupCard(true, status(state))!
      assert.equal(v.heading, 'Finish payout setup')
      assert.equal(v.tone, 'progress')
    })
  }

  for (const state of ['action_required', 'restricted']) {
    test(`${state} → Action needed for payouts, amber not red`, () => {
      const v = payoutSetupCard(true, status(state))!
      assert.equal(v.heading, 'Action needed for payouts')
      assert.equal(v.tone, 'attention')
      assert.notEqual(v.tone, 'stopped')
    })
  }

  test('transfers_only defers to the canonical copy', () => {
    // It genuinely means "money can arrive but cannot leave" — not
    // "nearly set up".
    const v = payoutSetupCard(true, status('transfers_only'))!
    assert.match(v.heading, /bank details/i)
    assert.ok(!/Finish payout setup|Set up payouts/.test(v.heading))
  })

  for (const state of ['unsupported', 'closed']) {
    test(`${state} promises no automatic payouts`, () => {
      const v = payoutSetupCard(true, status(state))!
      assert.equal(v.tone, 'stopped')
      assert.equal(v.ctaLabel, null, 'nothing useful to press')
      assert.equal(v.note, null, 'no Stripe reassurance where Stripe is the problem')
    })
  }

  test('every card points at the payout section of Billing', () => {
    for (const state of [
      'not_started', 'onboarding', 'verifying', 'action_required',
      'restricted', 'transfers_only', 'unsupported', 'closed',
    ]) {
      assert.equal(payoutSetupCard(true, status(state))!.href, PAYOUTS_HREF)
    }
    assert.equal(PAYOUTS_HREF, '/creator-studio/billing#payouts')
  })
})

describe('the copy never claims a blocker', () => {
  const bodies = [
    'not_started', 'onboarding', 'verifying', 'action_required', 'restricted',
  ].map((s) => payoutSetupCard(true, status(s))!.body)

  test('it does not say payouts are required in order to sell', () => {
    for (const body of bodies) {
      const b = body.toLowerCase()
      assert.ok(!b.includes('before you can'), body)
      assert.ok(!b.includes('cannot purchase'), body)
      assert.ok(!b.includes('before members can'), body)
      assert.ok(!b.includes('you must'), body)
    }
  })

  test('it says setup prepares the account, and selling continues', () => {
    for (const body of bodies) {
      assert.match(body, /prepares your account/)
      assert.match(body, /keep creating and selling/)
    }
  })

  test('it does not claim existing payouts change', () => {
    for (const body of bodies) {
      assert.ok(!/now go to Stripe|will now be paid/i.test(body), body)
    }
    assert.match(bodies[0], /Fresh Collective currently manages creator payouts/)
  })

  test('the supporting line is the agreed Stripe sentence', () => {
    assert.equal(
      payoutSetupCard(true, status('not_started'))!.note,
      'Payments and payouts are securely managed by Stripe.',
    )
  })
})

describe('ready is not the same as routing active', () => {
  test('details accepted, routing not yet enabled', () => {
    assert.equal(
      payoutReadyHeadline(status('ready')),
      'Your payout details are set up',
    )
  })

  test('routing enabled', () => {
    assert.equal(
      payoutReadyHeadline(status('ready', { connect_routing_enabled: true })),
      'Automatic payouts are active',
    )
  })

  test('it is derived from existing creator-facing data', () => {
    // No new backend field: connect_routing_enabled is already on the
    // status payload, from connect_payouts_enabled_at.
    assert.match(codeOnly('./stripeConnectPanel.ts'), /status\.connect_routing_enabled/)
  })

  test('no internal field name is exposed to creators', () => {
    const panel = read('./stripeConnectPanel.ts')
    const card = read('./payoutSetupCard.ts')
    // Mentioned in comments is fine; it must not appear in rendered copy.
    for (const src of [codeOnly('./stripeConnectPanel.ts'), codeOnly('./payoutSetupCard.ts')]) {
      assert.ok(
        !/'[^']*connect_payouts_enabled_at[^']*'/.test(src),
        'internal column name in creator copy',
      )
    }
    assert.ok(panel.length > 0 && card.length > 0)
  })
})

describe('Creator Studio home wiring', () => {
  const src = codeOnly(STUDIO)

  test('it gates on the capability, not a plan slug', () => {
    assert.match(src, /paid_offers_enabled/)
    for (const slug of ["'creator'", "'founding-creator'", "'community'"]) {
      assert.ok(!src.includes(slug), `plan slug comparison: ${slug}`)
    }
  })

  test('it uses the canonical status endpoint', () => {
    assert.match(src, /getCreatorStripeConnectStatus\(\)/)
    assert.ok(
      !src.includes('stripe_connect_connected'),
      'the "row exists" boolean is not the readiness question',
    )
  })

  test('it tolerates a missing current_plan', () => {
    // Null for a Platform Owner.
    assert.match(src, /billing\?\.current_plan\?\.paid_offers_enabled/)
  })

  test('a Platform Owner with paid offers still sees it', () => {
    assert.match(src, /billing\?\.is_platform_owner/)
  })

  test('the status is not fetched for creators who cannot sell', () => {
    assert.match(src, /paidOffersEnabled\s*\n?\s*\?\s*await getCreatorStripeConnectStatus/)
  })

  test('the card renders only when there is one', () => {
    assert.match(src, /\{payoutCard && <PayoutSetupCard view=\{payoutCard\} \/>\}/)
  })

  test('it sits below the hero, not above it', () => {
    assert.ok(src.indexOf('</header>') < src.indexOf('<PayoutSetupCard'))
  })

  test('no other Creator Studio screen carries a payout warning', () => {
    // One orientation point, not warnings everywhere.
    const studioFiles = [
      '../app/creator-studio/pathways/PathwaysClient.tsx',
      '../app/creator-studio/settings/page.tsx',
    ]
    for (const rel of studioFiles) {
      assert.ok(
        !codeOnly(rel).includes('PayoutSetupCard'),
        `${rel} should not carry the payout card`,
      )
    }
  })
})

describe('the card component is calm', () => {
  const src = codeOnly(CARD)

  test('error red is reserved for the stopped state', () => {
    const stopped = src.slice(src.indexOf('stopped:'))
    assert.match(stopped, /#A3433A/)
    const attention = src.slice(src.indexOf('attention:'), src.indexOf('stopped:'))
    assert.ok(!/#A3433A|#B4483C/.test(attention), 'attention must not be red')
  })

  test('it is a section with an accessible heading, not a banner', () => {
    assert.match(src, /aria-labelledby="payout-setup-heading"/)
    assert.match(src, /id="payout-setup-heading"/)
  })

  test('it always offers a route through to the detail', () => {
    assert.equal((src.match(/href=\{view\.href\}/g) ?? []).length, 2)
  })
})

describe('Billing hierarchy', () => {
  const src = read(BILLING)

  test('payouts comes before plan, usage, earnings and comparison', () => {
    const payouts = src.indexOf('>Payouts</h2>')
    const plan = src.indexOf('Current plan')
    const earnings = src.indexOf('Earnings estimate')
    const comparison = src.indexOf('>Plan comparison</h2>')
    assert.ok(payouts > 0, 'the Payouts section exists')
    assert.ok(payouts < plan, 'payouts must precede plan detail')
    assert.ok(payouts < earnings, 'payouts must precede earnings')
    assert.ok(payouts < comparison, 'payouts must precede plan comparison')
  })

  test('the section is named for the creator, not the provider', () => {
    assert.match(src, />Payouts<\/h2>/)
    assert.ok(!src.includes('>Payment setup</h2>'))
  })

  test('it carries the anchor the Studio card links to', () => {
    assert.match(src, /id="payouts"/)
  })

  test('the existing Connect panel and copy are still used', () => {
    assert.match(src, /<StripeConnectPanel/)
    assert.match(src, /billingPayoutPhase/)
  })

  test('the truthful preparation statement is retained', () => {
    const copy = read('./paymentsPayoutCopy.ts')
    assert.match(copy, /prepares your account for automatic\s*'?\s*\+?\s*'?\s*payouts/)
    assert.match(copy, /we’ll tell you before your sales start using it/)
  })
})

describe('Community still sees no payout setup on Billing', () => {
  // This regressed once during this work: moving the payout section to
  // the top of the page took it *out* of the capability gate, so every
  // creator would have seen it. The existing gate test caught it.
  const lines = codeOnly(BILLING).split('\n')

  function gateSpan() {
    const start = lines.findIndex(
      (l) => l.includes('{current_plan.paid_offers_enabled && ('),
    )
    assert.ok(start > -1, 'the capability gate exists')
    const indent = lines[start].length - lines[start].trimStart().length
    const end = lines.findIndex(
      (l, i) => i > start && l.trim() === ')}'
        && l.length - l.trimStart().length === indent,
    )
    assert.ok(end > start, 'the gate closes')
    return [start, end] as const
  }

  test('the payout section is inside the capability gate', () => {
    const [start, end] = gateSpan()
    const payouts = lines.findIndex((l) => l.includes('id="payouts"'))
    assert.ok(payouts > start && payouts < end,
      'the payout section must be gated on paid_offers_enabled')
  })

  test('the Connect panel is inside it too', () => {
    const [start, end] = gateSpan()
    const panel = lines.findIndex((l) => l.includes('<StripeConnectPanel'))
    assert.ok(panel > start && panel < end)
  })

  test('the gate itself now sits above the plan detail', () => {
    const [start] = gateSpan()
    const plan = lines.findIndex((l) => l.trim() === 'Current plan')
    assert.ok(plan > -1 && start < plan,
      'payouts must come before plan detail',
    )
  })
})
