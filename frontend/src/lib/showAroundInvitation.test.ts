import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import { CONTACT_INFO_EMAIL } from './contact.ts'
import { CREATOR_FAQ, creatorFaqJsonLd } from './creatorFaq.ts'
import {
  SHOW_AROUND_LINK_LABEL,
  SHOW_AROUND_MAILTO,
  SHOW_AROUND_QUESTION,
  SHOW_AROUND_SUBJECT,
} from './showAroundInvitation.ts'

/**
 * The 15-minute show-around invitation.
 *
 * It appears twice and has to read identically in both places, so
 * most of what is worth asserting is that neither host retyped it.
 * The rest guards the two ways this could quietly become something
 * it was never meant to be: a scheduling tool, or an eighth FAQ
 * question.
 *
 * Source reads are comment-stripped, so a doc comment mentioning a
 * booking service cannot be mistaken for code using one.
 */

const read = (p: string) => readFileSync(p, 'utf8')

const codeOnly = (src: string) =>
  src
    .replace(/\{\s*\/\*[\s\S]*?\*\/\s*\}/g, '')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|[^:])\/\/.*$/gm, '$1')

const COMPONENT = codeOnly(read('src/components/marketing/ShowAroundInvitation.tsx'))
const MODULE = codeOnly(read('src/lib/showAroundInvitation.ts'))
const VIDEO = codeOnly(read('src/components/home/HomeIntroVideo.tsx'))
const FOR_CREATORS = codeOnly(read('src/app/for-creators/page.tsx'))


// ---------------------------------------------------------------------------
// 1. The words, as approved
// ---------------------------------------------------------------------------

describe('the invitation reads as approved', () => {
  test('the question', () => {
    assert.equal(SHOW_AROUND_QUESTION, 'Rather see it with a person?')
  })

  test('the action', () => {
    assert.equal(
      SHOW_AROUND_LINK_LABEL,
      'Email Linds to arrange a 15-minute show-around →',
    )
  })

  test('the arrow is the one the other quiet links use', () => {
    assert.ok(SHOW_AROUND_LINK_LABEL.endsWith('→'))
  })
})


// ---------------------------------------------------------------------------
// 2. Where it goes
// ---------------------------------------------------------------------------

describe('the mailto', () => {
  test('it is exactly the destination that was specified', () => {
    assert.equal(
      SHOW_AROUND_MAILTO,
      'mailto:info@freshcollective.au'
        + '?subject=Fresh%20Collective%20-%2015-minute%20show-around',
    )
  })

  test('the address is the shared one, not a second copy', () => {
    assert.ok(SHOW_AROUND_MAILTO.startsWith(`mailto:${CONTACT_INFO_EMAIL}`))
    assert.ok(
      MODULE.includes('CONTACT_INFO_EMAIL'),
      'the address is hardcoded and can now drift from lib/contact',
    )
  })

  test('the subject survives the round trip', () => {
    const subject = new URL(SHOW_AROUND_MAILTO).searchParams.get('subject')
    assert.equal(subject, SHOW_AROUND_SUBJECT)
    assert.equal(subject, 'Fresh Collective - 15-minute show-around')
  })

  test('the subject uses a plain hyphen, which every mail client survives', () => {
    assert.ok(!/[–—]/.test(SHOW_AROUND_SUBJECT))
  })
})


// ---------------------------------------------------------------------------
// 3. It is an email invitation, and stays one
// ---------------------------------------------------------------------------

describe('no scheduling tool is introduced', () => {
  const BOOKING = /calendly|cal\.com|acuity|savvycal|bookings|book-a-|schedul(e|ing)-link/i

  for (const [name, src] of [
    ['the module', MODULE],
    ['the component', COMPONENT],
    ['the homepage video section', VIDEO],
    ['For Creators', FOR_CREATORS],
  ] as const) {
    test(`${name} links to no booking service`, () => {
      assert.ok(!BOOKING.test(src))
    })
  }

  test('the only destination is a mailto', () => {
    const hrefs = [...COMPONENT.matchAll(/href=\{?([^}\s>]+)/g)].map((m) => m[1]!)
    assert.equal(hrefs.length, 1)
    assert.ok(hrefs[0]!.includes('SHOW_AROUND_MAILTO'))
  })
})


// ---------------------------------------------------------------------------
// 4. One implementation, used twice
// ---------------------------------------------------------------------------

describe('both places render the same component', () => {
  test('the homepage video section uses it', () => {
    assert.ok(VIDEO.includes('<ShowAroundInvitation'))
  })

  test('For Creators uses it', () => {
    assert.ok(FOR_CREATORS.includes('<ShowAroundInvitation'))
  })

  test('neither host retyped the copy', () => {
    for (const src of [VIDEO, FOR_CREATORS]) {
      assert.ok(!src.includes('Rather see it with a person'))
      assert.ok(!src.includes('15-minute show-around'))
      assert.ok(!src.includes('mailto:info@freshcollective.au?subject='))
    }
  })

  test('it appears once in each place', () => {
    assert.equal(VIDEO.split('<ShowAroundInvitation').length - 1, 1)
    assert.equal(FOR_CREATORS.split('<ShowAroundInvitation').length - 1, 1)
  })
})


// ---------------------------------------------------------------------------
// 5. A link, reachable by keyboard
// ---------------------------------------------------------------------------

describe('the action is an accessible text link', () => {
  test('it is an anchor, not a button', () => {
    assert.ok(/<a\b/.test(COMPONENT))
    assert.ok(
      !/<button/.test(COMPONENT),
      'a second CTA button was introduced',
    )
  })

  test('focus is visible', () => {
    assert.ok(/focus-visible:outline/.test(COMPONENT))
    assert.ok(COMPONENT.includes('#246B6A'))
  })

  test('it uses the existing teal link treatment', () => {
    assert.ok(/underline/.test(COMPONENT))
    assert.ok(COMPONENT.includes('TEAL_DEEP'))
  })

  test('the question is understated, not a heading', () => {
    assert.ok(!/<h[1-6]/.test(COMPONENT))
    assert.ok(!/uppercase/.test(COMPONENT))
  })

  test('it is centred', () => {
    assert.ok(/text-center/.test(COMPONENT))
  })
})


// ---------------------------------------------------------------------------
// 6. On For Creators: supporting content, not an eighth question
// ---------------------------------------------------------------------------

describe('the FAQ is unchanged by it', () => {
  test('there are still exactly seven questions', () => {
    assert.equal(CREATOR_FAQ.length, 7)
  })

  test('the FAQPage structured data still carries exactly seven', () => {
    const jsonLd = creatorFaqJsonLd() as { mainEntity: unknown[] }
    assert.equal(jsonLd.mainEntity.length, 7)
  })

  test('the invitation is not inside the accordion', () => {
    const accordionEnd = FOR_CREATORS.indexOf('</details>')
    const invitation = FOR_CREATORS.indexOf('<ShowAroundInvitation')
    assert.ok(accordionEnd > 0 && invitation > accordionEnd)
  })

  test('it sits above the contact and policy line', () => {
    const invitation = FOR_CREATORS.indexOf('<ShowAroundInvitation')
    const contact = FOR_CREATORS.indexOf('Still wondering about something?')
    assert.ok(contact > 0, 'the contact line is gone')
    assert.ok(invitation < contact, 'the invitation is below the policy line')
  })

  test('the contact address and both policy links survive', () => {
    assert.ok(FOR_CREATORS.includes('mailto:${CONTACT_INFO_EMAIL}'))
    assert.ok(FOR_CREATORS.includes('/world-guide/creator-agreement'))
    assert.ok(
      FOR_CREATORS.includes('/world-guide/payment-refund-and-cancellation-policy'),
    )
  })

  test('the fee table is still rendered inside the FAQ', () => {
    assert.ok(FOR_CREATORS.includes('<FeeTable />'))
    assert.ok(CREATOR_FAQ.some((item) => item.feeTable))
  })
})


// ---------------------------------------------------------------------------
// 7. On the homepage: below the video, inside its section
// ---------------------------------------------------------------------------

describe('the homepage placement', () => {
  test('it comes after the video frame, not before it', () => {
    const frame = VIDEO.indexOf('aspect-video')
    const invitation = VIDEO.indexOf('<ShowAroundInvitation')
    assert.ok(frame > 0 && invitation > frame)
  })

  test('it stays inside the video section', () => {
    const invitation = VIDEO.indexOf('<ShowAroundInvitation')
    assert.ok(invitation < VIDEO.indexOf('</section>'))
  })

  test('the video is still the feature — no button competes with it', () => {
    // The only button in the section is the play control.
    assert.equal(VIDEO.split('<button').length - 1, 1)
  })
})
