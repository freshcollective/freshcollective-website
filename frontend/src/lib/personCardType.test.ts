import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

import { personCardType } from '../components/connections/personCardType.ts'

const SRC = join(dirname(fileURLToPath(import.meta.url)), '..')
const read = (p: string) => readFileSync(join(SRC, p), 'utf8')
const codeOnly = (p: string) =>
  read(p)
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, '')
    .replace(/(^|[^:])\/\/.*$/gm, '$1')

const CARD = 'components/connections/PersonCard.tsx'
const ROLES = 'components/connections/personCardType.ts'

/** Every JSX element in the card that carries text. */
function cardCode() {
  return codeOnly(CARD)
}

describe('the card declares no typography of its own', () => {
  const src = cardCode()

  test('no inline font-family anywhere', () => {
    // Five branches used to hand-write `fontFamily: 'Georgia, serif'`
    // while the name used the `font-serif` utility. Same typeface here,
    // but two mechanisms — so either could be changed without the other.
    assert.ok(
      !/fontFamily/.test(src),
      'family is a role decision, not a branch decision',
    )
    assert.ok(!/font-serif/.test(src), 'use the token via the role map')
  })

  test('no literal font sizes', () => {
    const sizes = src.match(/text-\[\d+(\.\d+)?px\]/g)
    assert.equal(sizes, null, `literal sizes left behind: ${sizes}`)
  })

  test('no literal weights', () => {
    const weights = src.match(/font-(thin|light|normal|medium|semibold|bold|black)\b/g)
    assert.equal(weights, null, `literal weights left behind: ${weights}`)
  })

  test('no literal line heights', () => {
    assert.ok(!/leading-(tight|snug|relaxed|loose|none)\b/.test(src))
    assert.ok(!/leading-\[\d/.test(src))
  })

  test('every text element names a role', () => {
    // The role map is the only source of type on this card.
    for (const role of ['name', 'reason', 'sharedLabel', 'evidence', 'state',
      'prompt', 'supporting', 'error', 'action', 'actionPrimary',
      'actionQuiet', 'footer']) {
      assert.ok(
        src.includes(`T.${role}.className`),
        `role '${role}' is defined but never used`,
      )
    }
  })
})

describe('the same semantic element is identical on every card', () => {
  const src = cardCode()

  test('all three relationship-state lines share one role', () => {
    // "✓ Connected", "Hello sent" and "👋 … said hello" rendered in
    // three different weights before this. They are the same kind of
    // statement about the same relationship.
    const stateUses = src.match(/T\.state\.className/g) ?? []
    assert.equal(
      stateUses.length, 3,
      'expected exactly the three state lines to use the state role',
    )
  })

  test('the state role is the only treatment near those strings', () => {
    for (const phrase of ['Connected', 'Hello sent', 'said hello']) {
      const i = src.indexOf(phrase)
      assert.ok(i > 0, `missing state copy: ${phrase}`)
      const before = src.slice(Math.max(0, i - 420), i)
      assert.ok(
        /T\.state\.(className|style)/.test(before),
        `'${phrase}' is not rendered through the state role`,
      )
    }
  })

  test('the incoming notice no longer emphasises inside an emphasis', () => {
    const i = src.indexOf('said hello')
    const around = src.slice(Math.max(0, i - 400), i + 80)
    assert.ok(
      !/className="font-semibold"/.test(around),
      'the role already carries the weight',
    )
  })

  test('both text actions share one role', () => {
    for (const phrase of ['Message →', "'Say hello back'"]) {
      const i = src.indexOf(phrase)
      assert.ok(i > 0, `missing action copy: ${phrase}`)
      const before = src.slice(Math.max(0, i - 700), i)
      assert.ok(
        /T\.action\.className/.test(before),
        `'${phrase}' is not rendered through the action role`,
      )
    }
  })

  test('stepping back from an action is typographically an action too', () => {
    // Cancel was `font-medium` beside a `font-semibold` sibling in the
    // same row. Only its colour should mark it as the quieter one.
    assert.equal(
      personCardType.actionQuiet.className,
      personCardType.action.className,
      'quiet means a different colour, not a different weight',
    )
    assert.notEqual(
      personCardType.actionQuiet.style.color,
      personCardType.action.style.color,
    )
  })
})

describe('the roles sit on the Fresh Collective scale', () => {
  const roles = Object.entries(personCardType)

  test('sizes come from the token scale, with one named exception', () => {
    for (const [role, def] of roles) {
      const fromToken = def.className.includes('text-[length:var(--fc-fs-')
      const fromStyle = 'fontSize' in def.style
      assert.ok(
        fromToken || fromStyle,
        `role '${role}' declares no size at all`,
      )
      if (fromStyle) {
        assert.equal(role, 'name', 'only the card title may sit off-scale')
      }
    }
  })

  test('the one off-scale value is named rather than repeated', () => {
    // Comment-stripped throughout this block: the module documents the
    // values it is replacing, and a raw read fails on the explanation
    // rather than on a breach.
    const src = codeOnly(ROLES)
    assert.match(src, /const TITLE_PX = '19px'/)
    assert.equal((src.match(/19px/g) ?? []).length, 1)
  })

  test('no half-pixel sizes survive', () => {
    const src = codeOnly(ROLES)
    assert.ok(
      !/\d+\.\d+px/.test(src),
      'the card used to carry 13.5, 12.5 and 11.5px',
    )
  })

  test('weights come from tokens, and only the permitted three', () => {
    for (const [role, def] of roles) {
      const weight = def.className.match(/font-\[var\(--fc-fw-([a-z]+)\)\]/)
      assert.ok(weight, `role '${role}' declares no weight token`)
      assert.ok(
        ['regular', 'semibold', 'bold'].includes(weight[1]),
        `role '${role}' uses weight '${weight[1]}'`,
      )
    }
  })

  test('the serif is requested through the token, never a literal stack', () => {
    const src = codeOnly(ROLES)
    assert.ok(
      !/Georgia/.test(src),
      'the family belongs to --fc-font-serif, not to this file',
    )
    assert.match(src, /const SERIF = 'font-\[var\(--fc-font-serif\)\]'/)
  })

  test('serif is reserved for the human voice', () => {
    // Name, the reason sentence, the relationship state and the question
    // asked before sending. Not labels, not actions, not metadata.
    const serif = roles
      .filter(([, d]) => d.className.includes('--fc-font-serif'))
      .map(([r]) => r)
      .sort()
    assert.deepEqual(serif, ['name', 'prompt', 'reason', 'state'])
  })

  test('every role declares a colour', () => {
    for (const [role, def] of roles) {
      assert.match(def.style.color, /^(#[0-9A-Fa-f]{6}|rgba\()/, role)
    }
  })

  test('the card palette is unchanged by the refactor', () => {
    // Consistency was the goal; recolouring the card was not.
    const colours = new Set(roles.map(([, d]) => d.style.color))
    for (const kept of [
      '#0C1826', 'rgba(12, 24, 38, 0.78)', 'rgba(12, 24, 38, 0.72)',
      'rgba(12, 24, 38, 0.6)', 'rgba(12, 24, 38, 0.42)',
      'rgba(12, 24, 38, 0.45)', '#1E6E6C', '#2F8F8D', '#B4483C',
    ]) {
      assert.ok(colours.has(kept), `lost the card colour ${kept}`)
    }
  })

  test('no role is defined and left unused by the card', () => {
    const src = cardCode()
    for (const [role] of roles) {
      assert.ok(src.includes(`T.${role}.`), `unused role: ${role}`)
    }
  })
})
