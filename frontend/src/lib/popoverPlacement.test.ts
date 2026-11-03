import { strict as assert } from 'node:assert'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, it } from 'node:test'

import {
  VIEWPORT_PADDING,
  placePopover,
  placementClasses,
} from './popoverPlacement.ts'

const SRC = join(process.cwd(), 'src')
const PICKER = join(SRC, 'components', 'community', 'EmojiPicker.tsx')
const EDITOR = join(SRC, 'components', 'ui', 'AboutRichTextEditor.tsx')
const PATHWAY_EDITOR = join(SRC, 'components', 'creator', 'RichTextEditor.tsx')
const TOOLBAR = join(SRC, 'components', 'creator', 'EditorToolbar.tsx')

/** The emoji panel, from its Tailwind classes. */
const PANEL = { width: 288, height: 320 }
const DESKTOP = { width: 1440, height: 900 }

/** A trigger rect, from its left/top and a 28×28 button. */
function trigger(left: number, top: number, size = 28) {
  return { left, top, right: left + size, bottom: top + size }
}

describe('horizontal placement', () => {
  it('opens rightward when there is room', () => {
    const out = placePopover({
      trigger: trigger(100, 200), panel: PANEL, viewport: DESKTOP,
    })
    assert.equal(out.x, 'left')
  })

  it('flips when opening rightward would overflow', () => {
    // The reported bug: in a narrow column the emoji button sits close
    // to the right edge, and a 288px panel ran past it.
    const out = placePopover({
      trigger: trigger(DESKTOP.width - 60, 200),
      panel: PANEL,
      viewport: DESKTOP,
    })
    assert.equal(out.x, 'right')
  })

  it('flips exactly at the boundary, not before', () => {
    const justFits = DESKTOP.width - PANEL.width - VIEWPORT_PADDING
    assert.equal(
      placePopover({
        trigger: trigger(justFits, 200), panel: PANEL, viewport: DESKTOP,
      }).x,
      'left',
    )
    assert.equal(
      placePopover({
        trigger: trigger(justFits + 1, 200), panel: PANEL, viewport: DESKTOP,
      }).x,
      'right',
    )
  })

  it('does not flip when the other side has no room either', () => {
    // A phone narrower than the panel. Flipping would overflow the
    // left edge instead, which is not an improvement — the panel's own
    // max-width handles it.
    const phone = { width: 320, height: 720 }
    const out = placePopover({
      trigger: trigger(200, 100), panel: PANEL, viewport: phone,
    })
    assert.equal(out.x, 'left')
  })

  it('flips on a phone when the trigger is far enough right', () => {
    const phone = { width: 390, height: 844 }
    const out = placePopover({
      trigger: trigger(340, 100), panel: PANEL, viewport: phone,
    })
    assert.equal(out.x, 'right')
  })
})

describe('vertical placement', () => {
  it('honours the caller preference when there is room', () => {
    assert.equal(
      placePopover({
        trigger: trigger(100, 100), panel: PANEL, viewport: DESKTOP,
        prefer: 'bottom',
      }).y,
      'bottom',
    )
    assert.equal(
      placePopover({
        trigger: trigger(100, 500), panel: PANEL, viewport: DESKTOP,
        prefer: 'top',
      }).y,
      'top',
    )
  })

  it('opens upward when there is no room below', () => {
    const out = placePopover({
      trigger: trigger(100, DESKTOP.height - 80),
      panel: PANEL, viewport: DESKTOP, prefer: 'bottom',
    })
    assert.equal(out.y, 'top')
  })

  it('opens downward when there is no room above', () => {
    const out = placePopover({
      trigger: trigger(100, 10), panel: PANEL, viewport: DESKTOP,
      prefer: 'top',
    })
    assert.equal(out.y, 'bottom')
  })

  it('keeps the preference when neither side fits', () => {
    // A cramped popover where the caller expected it beats one that
    // jumps somewhere equally cramped.
    const shallow = { width: 1440, height: 360 }
    const out = placePopover({
      trigger: trigger(100, 170), panel: PANEL, viewport: shallow,
      prefer: 'bottom',
    })
    assert.equal(out.y, 'bottom')
  })

  it('defaults to opening downward', () => {
    assert.equal(
      placePopover({
        trigger: trigger(100, 100), panel: PANEL, viewport: DESKTOP,
      }).y,
      'bottom',
    )
  })
})

describe('placementClasses', () => {
  it('maps each corner to Tailwind', () => {
    assert.equal(placementClasses({ x: 'left', y: 'bottom' }), 'top-full mt-1 left-0')
    assert.equal(placementClasses({ x: 'right', y: 'bottom' }), 'top-full mt-1 right-0')
    assert.equal(placementClasses({ x: 'left', y: 'top' }), 'bottom-full mb-1 left-0')
    assert.equal(placementClasses({ x: 'right', y: 'top' }), 'bottom-full mb-1 right-0')
  })

  it('never emits a fixed pixel offset', () => {
    // "Avoid adding large fixed offsets that only work at one screen
    // width" — the placement is a side, not a nudge.
    for (const x of ['left', 'right'] as const) {
      for (const y of ['top', 'bottom'] as const) {
        assert.ok(!/\[\d+px\]|-?\d+px/.test(placementClasses({ x, y })))
      }
    }
  })
})

describe('the emoji picker uses it', () => {
  const picker = () => readFileSync(PICKER, 'utf8')

  it('measures the trigger, not the panel', () => {
    // Measuring the panel feeds its new position into the next
    // measurement, which is how a popover flickers between two places.
    const source = picker()
    assert.ok(/triggerRef\.current\?\.getBoundingClientRect\(\)/.test(source))
    assert.ok(
      !/panelRef\.current\?\.getBoundingClientRect/.test(source),
      'placement is being measured from the panel again',
    )
  })

  it('recomputes on every open', () => {
    assert.ok(/\}, \[open, align\]\)/.test(picker()))
  })

  it('declares the panel size its classes actually use', () => {
    // The decision is made before the panel exists, so the numbers are
    // stated. They have to match the classes or the flip point is wrong.
    const source = picker()
    assert.ok(/const PANEL_WIDTH = 288/.test(source))
    assert.ok(/const PANEL_HEIGHT = 320/.test(source))
    assert.ok(/w-72/.test(source), 'w-72 is 288px — the width changed')
    assert.ok(/max-h-80/.test(source), 'max-h-80 is 320px — the height changed')
  })

  it('never exceeds the screen, whichever way it opens', () => {
    assert.ok(/max-w-\[calc\(100vw-1rem\)\]/.test(picker()))
  })

  it('keeps every category scrollable', () => {
    assert.ok(/max-h-80 overflow-y-auto/.test(picker()))
  })
})

describe('the picker closes and is reachable without a mouse', () => {
  const picker = () => readFileSync(PICKER, 'utf8')

  it('closes on Escape and returns focus', () => {
    const source = picker()
    assert.ok(/e\.key !== 'Escape'/.test(source))
    assert.ok(/triggerRef\.current\?\.focus\(\)/.test(source))
    assert.ok(/addEventListener\('keydown', handleKey\)/.test(source))
    assert.ok(/removeEventListener\('keydown', handleKey\)/.test(source))
  })

  it('closes on an outside click', () => {
    assert.ok(/!ref\.current\.contains\(e\.target as Node\)\) setOpen\(false\)/
      .test(picker()))
  })

  it('opens from the keyboard', () => {
    // A browser fires `click` with `detail === 0` for Enter and Space
    // and never `mousedown`, so a mousedown-only trigger could not be
    // opened without a mouse at all.
    const source = picker()
    assert.ok(/onClick=\{\(e\) => \{[\s\S]{0,120}e\.detail !== 0/.test(source))
  })

  it('selects an emoji from the keyboard', () => {
    const source = picker()
    const emojiButton = source.slice(source.indexOf('{group.emojis.map'))
    assert.ok(/onClick=\{\(ev\) => \{[\s\S]{0,140}ev\.detail !== 0/.test(emojiButton))
  })

  it('still closes when an emoji is chosen with the mouse', () => {
    const source = picker()
    assert.ok(/onSelect\(e\)\s*\n\s*setOpen\(false\)/.test(source))
  })

  it('announces itself as a dialog trigger', () => {
    const source = picker()
    assert.ok(/aria-haspopup="dialog"/.test(source))
    assert.ok(/aria-expanded=\{open\}/.test(source))
    assert.ok(/role="dialog"/.test(source))
  })
})

describe('nothing clips the popover any more', () => {
  it('the editor shell does not hide overflow', () => {
    // The confirmed cause. `overflow-hidden` on the editor shell
    // clipped the panel at the container boundary — the same problem
    // RichTextEditor documents solving by rounding the parts instead.
    const source = readFileSync(EDITOR, 'utf8')
    const wrapper = source.slice(source.indexOf('  return ('))
    const firstDiv = wrapper.slice(wrapper.indexOf('<div className='))
    const classes = firstDiv.slice(0, firstDiv.indexOf('>'))
    assert.ok(
      !/overflow-hidden/.test(classes),
      `the editor shell clips its popovers again: ${classes}`,
    )
    assert.ok(/rounded-lg/.test(classes))
  })

  it('the corners are still rounded, on the parts', () => {
    const source = readFileSync(EDITOR, 'utf8')
    assert.ok(/rounded-t-lg/.test(source) || /TOOLBAR_CLASS/.test(source))
    assert.ok(/rounded-b-lg/.test(source), 'the editor area lost its rounding')
  })

  it('the Pathway editor still does not clip either', () => {
    // It was already correct and must stay so.
    const source = readFileSync(PATHWAY_EDITOR, 'utf8')
    const wrapper = source.slice(source.indexOf('  return ('))
    const firstDiv = wrapper.slice(wrapper.indexOf('<div className='))
    assert.ok(!/overflow-hidden/.test(firstDiv.slice(0, firstDiv.indexOf('>'))))
  })

  it('the panel sits above the toolbar chrome', () => {
    assert.ok(/z-30/.test(readFileSync(PICKER, 'utf8')))
  })
})

describe('one toolbar style across Creator Studio', () => {
  const toolbar = () => readFileSync(TOOLBAR, 'utf8')

  it('the shared classes match the Pathway editor they came from', () => {
    // The drift guard. These were copied from RichTextEditor, the
    // editor a creator meets most often; if either side is restyled
    // alone, the editors disagree again and this fails.
    const pathway = readFileSync(PATHWAY_EDITOR, 'utf8')
    const shared = toolbar()

    assert.ok(
      pathway.includes(
        'flex flex-wrap items-center gap-0.5 rounded-t-lg border-b border-slate-100 bg-slate-50 px-2 py-1.5',
      ),
      'the Pathway toolbar chrome changed',
    )
    assert.ok(
      shared.includes('flex flex-wrap items-center gap-0.5 rounded-t-lg ')
      && shared.includes('border-b border-slate-100 bg-slate-50 px-2 py-1.5'),
      'the shared toolbar chrome no longer matches',
    )

    for (const fragment of [
      'flex h-7 w-7 items-center justify-center rounded text-[13px] transition-colors',
      'bg-teal-600 text-white',
      'text-black hover:bg-slate-100 hover:text-slate-800',
    ]) {
      assert.ok(pathway.includes(fragment), `Pathway lost: ${fragment}`)
      assert.ok(shared.includes(fragment), `shared lost: ${fragment}`)
    }
  })

  it('the Gathering editor renders through the shared pieces', () => {
    const source = readFileSync(EDITOR, 'utf8')
    assert.ok(/className=\{TOOLBAR_CLASS\}/.test(source))
    assert.ok(/<ToolButton/.test(source))
    assert.ok(/<ToolDivider \/>/.test(source))
    assert.ok(
      !/function ToolBtn\(/.test(source),
      'the editor has its own button implementation again',
    )
  })

  it('the buttons follow the Creator Studio order and glyphs', () => {
    // Text marks, then structure, then insert — the order
    // RichTextEditor established.
    const source = readFileSync(EDITOR, 'utf8')
    const order = ['<strong>B</strong>', '<em>I</em>', 'H2', 'H3', '•≡', '1≡', '🔗']
    let last = -1
    for (const glyph of order) {
      const at = source.indexOf(glyph)
      assert.ok(at > -1, `missing ${glyph}`)
      assert.ok(at > last, `${glyph} is out of order`)
      last = at
    }
  })

  it('the toolbar wraps rather than overflowing on a phone', () => {
    assert.ok(/flex flex-wrap/.test(toolbar()))
  })

  it('every toolbar button works from the keyboard', () => {
    const source = toolbar()
    assert.ok(/e\.detail !== 0/.test(source))
    assert.ok(/aria-pressed=\{active \?\? false\}/.test(source))
    assert.ok(/aria-label=\{title\}/.test(source))
  })

  it('the active state is the one the other editors use', () => {
    assert.ok(/TOOL_BUTTON_ACTIVE = 'bg-teal-600 text-white'/.test(toolbar()))
  })
})

describe('the other editors are left alone', () => {
  it('the Pathway and guidance editors keep their own toolbars', () => {
    // Pointing them at the shared module is a tidy-up for its own
    // commit; RichTextEditor carries tables, colours and fonts whose
    // editing this change has no business touching.
    for (const path of [
      PATHWAY_EDITOR,
      join(SRC, 'components', 'creator', 'SimpleRichTextEditor.tsx'),
    ]) {
      const source = readFileSync(path, 'utf8')
      assert.ok(
        !/EditorToolbar/.test(source),
        `${path} was rewired — out of scope for this change`,
      )
    }
  })

  it('the Collective About editor keeps its capabilities', () => {
    // Its look changed deliberately; what it can produce did not.
    const settings = readFileSync(
      join(SRC, 'app', 'creator-studio', 'settings', 'CollectiveSettingsForm.tsx'),
      'utf8',
    )
    const editor = settings.slice(settings.indexOf('<AboutRichTextEditor'))
    assert.ok(!/extendedMarks/.test(editor.slice(0, editor.indexOf('/>'))))
  })

  it('italic and numbered lists stay behind the opt-in', () => {
    const source = readFileSync(EDITOR, 'utf8')
    assert.ok(/extendedMarks = false/.test(source))
    assert.ok(/\{extendedMarks && \([\s\S]{0,300}toggleItalic/.test(source))
    assert.ok(/\{extendedMarks && \([\s\S]{0,300}toggleOrderedList/.test(source))
  })
})
