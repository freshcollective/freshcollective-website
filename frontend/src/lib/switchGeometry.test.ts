import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const SRC = join(dirname(fileURLToPath(import.meta.url)), '..')
const read = (p: string) => readFileSync(join(SRC, p), 'utf8')
const codeOnly = (p: string) =>
  read(p)
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, '')
    .replace(/(^|[^:])\/\/.*$/gm, '$1')

const SWITCH = 'components/platform/Switch.tsx'

/** Tailwind spacing step → px. `0.5` is 2px, `4` is 16px. */
const px = (step: string) => parseFloat(step) * 4

/**
 * A switch's thumb sits inside its track with an equal inset at both
 * ends, which makes the travel a consequence of the other three
 * numbers rather than a free choice:
 *
 *     travel = track − thumb − 2 × inset
 *
 * Every hand-rolled copy in this app got that wrong the same way:
 * anchored the thumb at 0, then translated by the inset-less distance,
 * leaving 2px of track at one end and 4px at the other.
 */
function assertSymmetric(
  label: string,
  { track, thumb, inset, travel }:
  { track: number; thumb: number; inset: number; travel: number },
) {
  const leftInset = inset
  const rightInset = track - (inset + travel) - thumb
  assert.equal(
    leftInset, rightInset,
    `${label}: thumb insets differ — ${leftInset}px left, ${rightInset}px right`,
  )
  assert.ok(
    inset + travel + thumb <= track,
    `${label}: thumb protrudes past the track`,
  )
  assert.ok(thumb < track, `${label}: thumb is not smaller than its track`)
}

describe('the canonical switch', () => {
  const src = codeOnly(SWITCH)

  test('track and thumb are the documented sizes', () => {
    assert.match(src, /block h-6 w-10 rounded-full/)   // 24 × 40
    assert.match(src, /h-5 w-5 rounded-full/)          // 20 × 20
  })

  test('the thumb is anchored, not left at zero', () => {
    // The whole defect in one assertion: without `left-0.5` the 16px
    // travel is measured from the wrong origin.
    assert.match(src, /absolute left-0\.5 top-0\.5/)
  })

  test('vertical centring is stated rather than inherited', () => {
    // It used to rest on the parent's `items-center` setting the static
    // position of an abspos flex child — true per spec, and it stops
    // applying the moment the wrapper's display changes.
    assert.match(src, /top-0\.5/)
  })

  test('the travel keeps the insets equal', () => {
    assert.match(src, /checked && 'translate-x-4'/)
    assertSymmetric('canonical', {
      track: 40, thumb: 20, inset: px('0.5'), travel: px('4'),
    })
  })

  test('unchecked, the thumb is inset and contained', () => {
    // Not `assertSymmetric` — symmetry is a property of the *pair* of
    // end states, not of either one alone. At rest the thumb sits
    // against the left inset; the right-hand gap is the travel.
    const inset = px('0.5')
    assert.equal(inset, 2, 'resting inset')
    assert.ok(inset + 20 <= 40, 'contained within the track')
    assert.ok(inset > 0, 'not flush against the edge')
  })

  test('the resting inset and the travelled inset are the same', () => {
    // The actual invariant Lindsey was looking at: the gap behind the
    // thumb unchecked equals the gap ahead of it checked.
    const inset = px('0.5')
    const travelled = 40 - (inset + px('4')) - 20
    assert.equal(travelled, inset)
  })

  test('the geometry invariant is written down beside the numbers', () => {
    assert.match(read(SWITCH), /travel = track width − thumb width − 2 × inset/)
  })
})

describe('the canonical switch keeps its semantics', () => {
  const src = codeOnly(SWITCH)

  test('a native checkbox underneath', () => {
    assert.match(src, /type="checkbox"/)
    assert.match(src, /role="switch"/)
    assert.match(src, /aria-checked=\{checked\}/)
  })

  test('the visual track is driven by the checkbox, not by JS', () => {
    assert.match(src, /peer-checked:bg-\[color:var\(--fc-accent-500\)\]/)
  })

  test('keyboard focus is visible, and only for keyboard', () => {
    assert.match(src, /peer-focus-visible:ring-2/)
  })

  test('disabled is still expressed', () => {
    assert.match(src, /peer-disabled:opacity-50/)
    assert.match(src, /peer-disabled:cursor-not-allowed/)
  })

  test('the colours are unchanged by the hardening', () => {
    // --fc-accent-500 is #38A09E, the same teal the hand-rolled copies
    // used; --fc-surface-card is #FFFFFF, the same white thumb.
    assert.match(src, /bg-\[color:var\(--fc-surface-card\)\]/)
    assert.match(codeOnly('styles/fc-tokens.css'), /--fc-accent-500:\s*#38A09E/)
  })

  test('the whole control is clickable, not just the hidden input', () => {
    assert.match(src, /<label htmlFor=\{inputId\}/)
  })
})

describe('no surface hand-rolls a switch with the broken travel', () => {
  function allSources(dir = SRC): string[] {
    const out: string[] = []
    for (const entry of readdirSync(dir)) {
      const full = join(dir, entry)
      if (statSync(full).isDirectory()) out.push(...allSources(full))
      else if (/\.tsx?$/.test(entry) && !/\.test\.tsx?$/.test(entry)) out.push(full)
    }
    return out
  }

  test('nothing translates a thumb that was never anchored', () => {
    // `translate-x-0.5` on an unanchored thumb is the signature of the
    // bug: it insets the unchecked end by 2px and leaves the checked
    // end 2px short.
    const offenders: string[] = []
    for (const file of allSources()) {
      const rel = file.slice(SRC.length + 1)
      const code = codeOnly(rel)
      if (!/role="switch"/.test(code)) continue
      if (/translate-x-0\.5/.test(code)) offenders.push(rel)
    }
    assert.deepEqual(offenders, [])
  })

  test('every remaining hand-rolled thumb is anchored and symmetric', () => {
    const hand = [
      // track 36 × 20, thumb 16, inset 2 → travel 36 − 16 − 4 = 16px
      'app/creator/spaces/[slug]/SpaceSettingsForm.tsx',
      'app/creator/spaces/[slug]/pathways/[pathway-slug]/PathwayForm.tsx',
      'app/creator/spaces/[slug]/pathways/[pathway-slug]/steps/[step-slug]/StepEditor.tsx',
    ]
    for (const rel of hand) {
      const code = codeOnly(rel)
      assert.match(code, /h-5 w-9 rounded-full/, `${rel}: track`)
      assert.match(code, /absolute left-0\.5 top-0\.5 h-4 w-4/, `${rel}: thumb`)
      assert.match(code, /'translate-x-4' : 'translate-x-0'/, `${rel}: travel`)
      assertSymmetric(rel, {
        track: 36, thumb: 16, inset: px('0.5'), travel: px('4'),
      })
    }
  })

  test('the two Account Settings toggles use the shared component', () => {
    const code = codeOnly('components/settings/ProfileForm.tsx')
    assert.ok(!/role="switch"/.test(code), 'no local switch markup')
    assert.equal((code.match(/<Switch\b/g) ?? []).length, 2)
    // Both keep an accessible name; the Public profile one had none.
    assert.match(code, /aria-label="Public profile"/)
    assert.match(code, /aria-label="Include me in Ways to Connect"/)
  })

  test('the toggles still flip state rather than setting a constant', () => {
    const code = codeOnly('components/settings/ProfileForm.tsx')
    assert.match(code, /onChange=\{\(\) => setIsPublic\(!isPublic\)\}/)
    assert.match(code, /onChange=\{\(\) => setWaysToConnect\(!waysToConnect\)\}/)
  })
})
