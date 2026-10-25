import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

/**
 * Creator removal UI contracts.
 *
 * The removal dialog and the Removed People section carry product rules
 * that are easy to break by accident: the reason must not drive the ban,
 * the ban must demand an explanation, only an owner may see the control,
 * and the explanation must never leak to a member surface. These are
 * asserted against the source because that is where the rules live —
 * there is no DOM in this runner.
 */

const SRC = dirname(fileURLToPath(import.meta.url))
const PEOPLE = join(SRC, '..', 'app', 'creator-studio', 'people')

const client = readFileSync(join(PEOPLE, 'PeopleClient.tsx'), 'utf8')
const removed = readFileSync(join(PEOPLE, 'RemovedPeople.tsx'), 'utf8')
const page = readFileSync(join(PEOPLE, 'page.tsx'), 'utf8')

/** The dialog only, so assertions don't match the rest of a 3000-line file. */
const modal = client.slice(
  // From the reason vocabulary, which sits just above the component,
  // to the next component — so assertions cannot accidentally match
  // elsewhere in a 3000-line file.
  client.indexOf('const REMOVAL_REASONS'),
  client.indexOf('function MemberDetailPanel'),
)

describe('the removal dialog offers the agreed reasons', () => {
  for (const label of [
    'Member requested removal',
    'Membership no longer required',
    'Inappropriate behaviour',
    'Payment issues',
    'Other',
  ]) {
    test(`it offers "${label}"`, () => {
      assert.ok(modal.includes(label), label)
    })
  }

  test('the reason is sent to the server', () => {
    assert.match(modal, /reason,/)
  })

  test('an explanation field is offered', () => {
    assert.match(modal, /Explanation \(optional\)/)
    assert.match(modal, /Explanation \(required\)/)
  })

  test('the explanation is described as private', () => {
    assert.match(modal, /Only you and your collective’s moderators can see this/)
  })
})

describe('the ban is a separate, explicit decision', () => {
  test('it is its own control, phrased as a question', () => {
    assert.match(modal, /Allow this person to rejoin in the future\?/)
  })

  test('both answers are spelled out', () => {
    assert.match(modal, /they can rejoin and\s*\n?\s*purchase normally/)
    assert.match(modal, /block future membership/)
  })

  test('the reason never sets the ban', () => {
    // The one invariant most likely to be "helpfully" broken later:
    // choosing Inappropriate behaviour must not tick the block.
    const onReasonChange = modal.slice(
      modal.indexOf('onChange={(e) => setReason('),
      modal.indexOf('</select>'),
    )
    assert.ok(!/setRejoinBlocked/.test(onReasonChange))
  })

  test('the block defaults to off', () => {
    assert.match(modal, /useState\(false\)[\s\S]{0,80}rejoinBlocked|rejoinBlocked, setRejoinBlocked\] = useState\(false\)/)
  })

  test('the confirm button is disabled without an explanation', () => {
    assert.match(modal, /noteMissing = noteRequired/)
    assert.match(modal, /disabled=\{removing \|\| noteMissing/)
  })

  test('the button says what it will do', () => {
    assert.match(modal, /rejoinBlocked \? 'Remove and block' : 'Remove member'/)
  })

  test('a non-owner is not offered the control at all', () => {
    assert.match(modal, /\{canBan && \(/)
  })

  test('canBan comes from server-reported ownership', () => {
    assert.match(page, /canBan=\{spaceDetail\?\.is_owner === true\}/)
  })
})

describe('the payment-plan warning', () => {
  test('it is never pre-acknowledged', () => {
    assert.match(modal, /acknowledged, setAcknowledged\] = useState\(false\)/)
  })

  test('the acknowledgement is only sent when actually given', () => {
    assert.match(modal, /acknowledge_active_payment_plan: acknowledged/)
  })

  test('the server message is shown rather than paraphrased', () => {
    assert.match(modal, /setPlanWarning\(String\(detail\.message\)\)/)
  })

  test('an acknowledgement request resets any prior tick', () => {
    // Otherwise a second attempt could carry a stale acknowledgement.
    const branch = modal.slice(modal.indexOf("'acknowledgement_required'"))
    assert.match(branch.slice(0, 200), /setAcknowledged\(false\)/)
  })

  test('confirming is blocked until it is ticked', () => {
    assert.match(modal, /blockedNeedsUrgent = Boolean\(planWarning\) && !acknowledged/)
    assert.match(modal, /disabled=\{removing \|\| noteMissing \|\| blockedNeedsUrgent\}/)
  })

  test('it says billing continues, not that it was handled', () => {
    assert.match(modal, /Their payment plan will keep running/)
    assert.match(modal, /does not stop or refund their payments/)
  })
})

describe('the removal uses the new endpoint', () => {
  test('it POSTs to /remove rather than DELETEing', () => {
    assert.match(modal, /members\/\$\{member\.id\}\/remove/)
    assert.match(modal, /method: 'POST'/)
    assert.ok(!/method: 'DELETE'/.test(modal))
  })
})

describe('Removed People', () => {
  test('it renders nothing when nobody has been removed', () => {
    assert.match(removed, /rows\.length === 0\) return null/)
  })

  test('it shows the reason and the explanation', () => {
    assert.match(removed, /Reason: /)
    assert.match(removed, /\{r\.note\}/)
  })

  test('it says plainly who can see the explanation', () => {
    assert.match(removed, /Explanations are never\s*\n?\s*shown to members/)
  })

  test('it labels whether somebody may return', () => {
    assert.match(removed, /Blocked from rejoining/)
    assert.match(removed, /Can rejoin/)
  })

  test('only an owner sees the lift control', () => {
    assert.match(removed, /\{canManage && \(/)
  })

  test('lifting is one click, imposing opens the dialog', () => {
    assert.match(removed, /Allow rejoining/)
    // Imposing a block goes through BlockRejoiningDialog, which
    // enforces the written reason — see its own describe block.
    assert.match(removed, /onClick=\{\(\) => setBlocking\(r\)\}/)
  })

  test('an outstanding payment is surfaced and not called settled', () => {
    // Superseded wording lives in its own describe block below; here
    // we only need that the panel exists and promises no resolution.
    assert.match(removed, /Payment arrangement requires attention/)
    assert.ok(!/payment resolved/i.test(removed))
    assert.ok(!/refunded automatically/i.test(removed))
  })

  test('it never claims the removal resolved the money', () => {
    assert.ok(!/refunded automatically/i.test(removed))
    assert.ok(!/payment resolved/i.test(removed))
  })
})

describe('the member-initiated departure is untouched', () => {
  const leave = readFileSync(join(SRC, 'leaveCollective.ts'), 'utf8')

  test('the rejoin promise still stands', () => {
    assert.match(
      leave,
      /You can rejoin this Collective later, subject to its membership /,
    )
  })

  test('Your Collection is still promised', () => {
    assert.match(leave, /Your Collection/)
  })

  test('the creator reason vocabulary did not leak into it', () => {
    assert.ok(!/inappropriate_behaviour/.test(leave))
    assert.ok(!/rejoin_blocked/.test(leave))
  })
})

describe('the block dialog replaces the browser prompt', () => {
  test('no window.prompt anywhere in the section', () => {
    assert.ok(!/window\.prompt/.test(removed))
  })

  test('it is a dialog with the usual chrome', () => {
    assert.match(removed, /function BlockRejoiningDialog/)
    assert.match(removed, /role="dialog"/)
    assert.match(removed, /aria-modal="true"/)
    // Same backdrop and card as RemoveMemberModal — no new design.
    assert.match(removed, /rgba\(0,0,0,0\.45\)/)
    assert.match(removed, /rounded-2xl border border-border bg-white shadow-xl/)
  })

  test('it names the member', () => {
    assert.match(removed, /\{name\}<\/span>/)
    assert.match(removed, /name=\{blocking\.display_name\}/)
  })

  test('it explains both consequences', () => {
    assert.match(removed, /will not be able to\s*\n?\s*rejoin this collective/)
    assert.match(removed, /not be able to make new purchases/)
    assert.match(removed, /including free offerings/)
  })

  test('it says what is NOT lost, and that it is reversible', () => {
    assert.match(removed, /Anything they have already bought stays theirs/)
    assert.match(removed, /You can lift this\s*\n?\s*at any time/)
  })

  test('the reason is required and enforced before submitting', () => {
    assert.match(removed, /Reason \(required\)/)
    assert.match(removed, /ready = note\.trim\(\)\.length > 0/)
    assert.match(removed, /disabled=\{busy \|\| !ready\}/)
  })

  test('it has the two named buttons', () => {
    assert.match(removed, /Block future membership<\/button>|Block future membership'/)
    assert.match(removed, />\s*Cancel\s*<\/button>/)
  })

  test('cancelling submits nothing', () => {
    assert.match(removed, /onCancel=\{\(\) => setBlocking\(null\)\}/)
  })

  test('the reason is still described as private', () => {
    assert.match(removed, /Only you and your moderators can see\s*\n?\s*it/)
  })
})

describe('the payment warning directs the creator to the plan', () => {
  test('it is driven by live state, not the audit flag', () => {
    // ``payment_action_required`` records that the removal was taken
    // with a plan live and stays true forever; the warning must follow
    // ``payment_action_outstanding``, which the server derives.
    assert.match(removed, /r\.payment_action_outstanding &&/)
    assert.ok(!/r\.payment_action_required &&/.test(removed))
  })

  test('it uses the approved wording', () => {
    assert.match(removed, /Payment arrangement requires attention/)
    assert.match(removed, /This member has an active instalment plan/)
    assert.match(
      removed,
      /future payments may continue until the\s*\n?\s*plan is cancelled/,
    )
  })

  test('it links to Payment Plans filtered to that member', () => {
    assert.match(
      removed,
      /\/creator-studio\/payment-plans\?member=\$\{encodeURIComponent\(r\.email\)\}/,
    )
    assert.match(removed, /Manage payment plan/)
  })

  test('it is prominent enough to read as action required', () => {
    assert.match(removed, /border-amber-300 bg-amber-50/)
    assert.match(removed, /font-semibold text-amber-900/)
  })

  test('it offers no cancel action of its own', () => {
    // Cancellation stays a separate, explicit action on the page that
    // already does it safely. The prose mentions cancelling; what must
    // not exist is a control that does it from here. Asserted on the
    // panel's affordances, with strings stripped.
    const panel = removed
      .slice(removed.indexOf('payment_action_outstanding'))
      .slice(0, 1400)
      .replace(/'[^'\n]*'/g, "''")
      .replace(/"[^"\n]*"/g, '""')
    assert.ok(!/<button/i.test(panel))
    assert.ok(!/setPolicy/.test(panel))
    assert.ok(!/fetch\(/.test(panel))
    // A link out, not an action in place.
    assert.match(panel, /<Link/)
  })

  test('the Payment Plans page honours the member filter', () => {
    const plans = readFileSync(
      join(SRC, '..', 'app', 'creator-studio', 'payment-plans',
           'CreatorPaymentPlansClient.tsx'),
      'utf8',
    )
    assert.match(plans, /searchParams\.get\('member'\)/)
    assert.match(plans, /useState<string>\(memberParam\)/)
  })
})
