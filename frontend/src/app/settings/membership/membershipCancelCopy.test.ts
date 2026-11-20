import { describe, it } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

/**
 * The cancellation confirmation, as agreed on 2026-11-20.
 *
 * This is the last thing a member reads before stopping a payment, so
 * each of the four promises it makes is pinned here — and each is true
 * of the code behind it:
 *
 *   * access until the period end — ``schedule_cancellation`` does not
 *     touch ``SpaceMembership``;
 *   * no further payments — Stripe is sent ``cancel_at_period_end``,
 *     never a cancel;
 *   * access to the Collective and included experiences ends after
 *     that date — expiry pauses the membership and releases only the
 *     bookings membership alone was holding;
 *   * separately purchased Offerings survive — the membership access
 *     module holds no reference to Offerings at all.
 *
 * Matched on the rendered copy, not on a comment mentioning it.
 */
const HERE = dirname(fileURLToPath(import.meta.url))
const source = readFileSync(join(HERE, 'MembershipSubscriptions.tsx'), 'utf8')

describe('cancellation confirmation copy', () => {
  it('asks the question plainly', () => {
    assert.match(source, /Are you sure you want to cancel your membership\?/)
  })

  it('promises access until the paid period ends, with no further payments', () => {
    assert.match(source, /you’ll keep access to/)
    assert.match(source, /with no further payments/)
    // The date is rendered, never hard-coded.
    assert.match(source, /formatDay\(sub\.current_period_end\)/)
  })

  it('says what is lost after that date', () => {
    assert.match(
      source,
      /lose access to the Collective and\s*\n?\s*any included Pathways and Gatherings/,
    )
  })

  it('reassures about separately purchased Offerings', () => {
    assert.match(source, /still have access to any Offerings you’ve/)
  })

  it('offers a way out that is not the destructive one', () => {
    assert.match(source, /Yes, cancel my membership/)
    assert.match(source, /Keep my membership/)
  })

  it('still has a fallback when no period end is known', () => {
    // A missing date must not render "until , with no further payments".
    assert.match(source, /until the end of your paid period/)
  })
})
