import { test, describe } from 'node:test'
import assert from 'node:assert/strict'

import {
  type ColumnsPayload,
  cellImageAlt,
  cellKind,
  decodeColumns,
  emptyColumnsPayload,
  encodeColumns,
  setCellKind,
} from './columnsBlock.ts'
import {
  type ColumnsImageAsset,
  applyAltTextToCell,
  applyAltUnsetToCell,
  applyAssetIdToCell,
  applyAssetToCell,
  applyCaptionToCell,
  applyEmbedUrlToCell,
  cellImageFieldProps,
} from './columnsImageFields.ts'

/**
 * ImageBlockFields fires two callbacks per gesture, and the order
 * matters. These tests replay the real sequences — copied from the
 * control's own ``pickAsset``, ``remove``, ``toggleDecorative`` and
 * ``updateAlt`` — rather than calling the adapter one function at a
 * time, because every bug worth catching here lives in the second call
 * of a pair undoing the first.
 *
 * If ImageBlockFields ever changes which callbacks it fires or in what
 * order, these tests will keep passing while the editor breaks. That is
 * the known limit of testing an adapter in isolation; the sequences are
 * quoted in each test so the pairing is at least visible.
 */

const ASSETS: ColumnsImageAsset[] = [
  { id: 'a1', file_url: '/uploads/media/s/one.jpg', title: 'Morning light' },
  { id: 'a2', file_url: '/uploads/media/s/two.jpg', title: null },
]

/** A columns block whose second column is in image mode, nothing chosen. */
function imageModeBlock(): ColumnsPayload {
  let p = emptyColumnsPayload()
  p = { ...p, cells: p.cells.map((c, i) => (i === 0 ? { ...c, content: '<p>Words</p>' } : c)) }
  return setCellKind(p, 1, 'image')
}

// --- the control's own gestures, reproduced -------------------------------

/** ImageBlockFields.pickAsset: onMediaAssetIdChange(id); onEmbedUrlChange(''). */
function gesturePickAsset(p: ColumnsPayload, i: number, id: string | null) {
  p = applyAssetIdToCell(p, i, id, ASSETS)
  return applyEmbedUrlToCell(p, i, '')
}

/** ImageBlockFields.remove(): clears both sources, then resets alt. */
function gestureRemove(p: ColumnsPayload, i: number) {
  p = applyAssetIdToCell(p, i, null, ASSETS)
  p = applyEmbedUrlToCell(p, i, '')
  p = applyAltTextToCell(p, i, '')
  return applyAltUnsetToCell(p, i, true)
}

/** ImageBlockFields.updateAlt(v): onAltUnsetChange(false); onAltTextChange(v). */
function gestureTypeAlt(p: ColumnsPayload, i: number, v: string) {
  p = applyAltUnsetToCell(p, i, false)
  return applyAltTextToCell(p, i, v)
}

/** ImageBlockFields.toggleDecorative(true). */
function gestureDecorativeOn(p: ColumnsPayload, i: number) {
  p = applyAltUnsetToCell(p, i, false)
  return applyAltTextToCell(p, i, '')
}

/** ImageBlockFields.toggleDecorative(false). */
function gestureDecorativeOff(p: ColumnsPayload, i: number) {
  p = applyAltUnsetToCell(p, i, true)
  return applyAltTextToCell(p, i, '')
}


describe('choosing an image', () => {
  test('picking from the library sets the url, id and title', () => {
    const p = gesturePickAsset(imageModeBlock(), 1, 'a1')
    assert.equal(p.cells[1].image?.assetId, 'a1')
    assert.equal(p.cells[1].image?.url, '/uploads/media/s/one.jpg')
    assert.equal(p.cells[1].image?.assetTitle, 'Morning light')
  })

  test("the control's follow-up embed clear does not undo the pick", () => {
    // This is the whole reason applyEmbedUrlToCell checks assetId.
    const p = gesturePickAsset(imageModeBlock(), 1, 'a1')
    assert.ok(p.cells[1].image, 'the picked image survived onEmbedUrlChange("")')
  })

  test('picking does not disturb the text in the other column', () => {
    const p = gesturePickAsset(imageModeBlock(), 1, 'a1')
    assert.equal(p.cells[0].content, '<p>Words</p>')
    assert.equal(cellKind(p.cells[0]), 'text')
  })

  test('an unknown asset id is ignored rather than clearing the image', () => {
    const chosen = gesturePickAsset(imageModeBlock(), 1, 'a1')
    const after = applyAssetIdToCell(chosen, 1, 'does-not-exist', ASSETS)
    assert.equal(after.cells[1].image?.assetId, 'a1')
  })

  test('replacing swaps the image and keeps the alt and caption', () => {
    let p = gesturePickAsset(imageModeBlock(), 1, 'a1')
    p = gestureTypeAlt(p, 1, 'A heron')
    p = applyCaptionToCell(p, 1, 'Beside the river')
    p = gesturePickAsset(p, 1, 'a2')
    assert.equal(p.cells[1].image?.assetId, 'a2')
    assert.equal(p.cells[1].image?.alt, 'A heron')
    assert.equal(p.cells[1].image?.caption, 'Beside the river')
  })

  test('an uploaded asset lands in the column it was started from', () => {
    const p = applyAssetToCell(imageModeBlock(), 1, {
      id: 'up1', file_url: '/uploads/media/s/new.png', title: 'Fresh upload',
    })
    assert.equal(p.cells[1].image?.assetId, 'up1')
    assert.equal(p.cells[1].image?.url, '/uploads/media/s/new.png')
    assert.equal(p.cells[0].image, undefined, 'and not in column 1')
  })

  test('an external url is stored with no asset id', () => {
    const p = applyEmbedUrlToCell(imageModeBlock(), 1, '  https://example.org/p.jpg  ')
    assert.equal(p.cells[1].image?.assetId, null)
    assert.equal(p.cells[1].image?.url, 'https://example.org/p.jpg', 'trimmed')
  })

  test('emptying the box removes an external image but not a library one', () => {
    const external = applyEmbedUrlToCell(imageModeBlock(), 1, 'https://example.org/p.jpg')
    assert.equal(applyEmbedUrlToCell(external, 1, '').cells[1].image, undefined)

    const library = gesturePickAsset(imageModeBlock(), 1, 'a1')
    assert.ok(applyEmbedUrlToCell(library, 1, '').cells[1].image, 'library pick kept')
  })
})


describe('removing an image', () => {
  test('clears the picture but leaves the column in image mode', () => {
    let p = gesturePickAsset(imageModeBlock(), 1, 'a1')
    p = gestureRemove(p, 1)
    assert.equal(p.cells[1].image, undefined)
    assert.equal(cellKind(p.cells[1]), 'image', 'controls stay visible to pick another')
  })

  test('does not touch the other column, or the parked text', () => {
    let p = gesturePickAsset(imageModeBlock(), 1, 'a1')
    p = applyAssetIdToCell(p, 1, null, ASSETS)
    p = { ...p, cells: p.cells.map((c, i) => (i === 1 ? { ...c, content: '<p>parked</p>' } : c)) }
    p = gestureRemove(p, 1)
    assert.equal(p.cells[0].content, '<p>Words</p>')
    assert.equal(p.cells[1].content, '<p>parked</p>')
  })

  test('alt writes against a column with no image are no-ops', () => {
    const p = imageModeBlock()
    assert.equal(applyAltTextToCell(p, 1, 'x'), p)
    assert.equal(applyAltUnsetToCell(p, 1, false), p)
    assert.equal(applyCaptionToCell(p, 1, 'c'), p)
  })
})


describe('alt text keeps its three states through the real gestures', () => {
  test('a freshly picked image starts with no alt decision recorded', () => {
    const p = gesturePickAsset(imageModeBlock(), 1, 'a1')
    assert.equal(p.cells[1].image?.alt, null)
    assert.equal(cellImageFieldProps(p.cells[1]).altUnset, true)
    // Which means it inherits the asset title.
    assert.equal(cellImageAlt(p.cells[1].image), 'Morning light')
  })

  test('typing alt text records it explicitly', () => {
    const p = gestureTypeAlt(gesturePickAsset(imageModeBlock(), 1, 'a1'), 1, 'A heron')
    assert.equal(p.cells[1].image?.alt, 'A heron')
    const props = cellImageFieldProps(p.cells[1])
    assert.equal(props.altUnset, false)
    assert.equal(props.altText, 'A heron')
    assert.equal(cellImageAlt(p.cells[1].image), 'A heron')
  })

  test('ticking decorative stores the empty string, not null', () => {
    const p = gestureDecorativeOn(gesturePickAsset(imageModeBlock(), 1, 'a1'), 1)
    assert.equal(p.cells[1].image?.alt, '')
    // And the renderer must NOT fall back to the asset title.
    assert.equal(cellImageAlt(p.cells[1].image), '')
  })

  test('unticking decorative returns to unset, and does not re-stick', () => {
    // The bug this guards: toggleDecorative(false) fires
    // onAltUnsetChange(true) and then onAltTextChange(''), and writing
    // that '' through would leave the image decorative — so the
    // checkbox could never be turned off.
    let p = gestureDecorativeOn(gesturePickAsset(imageModeBlock(), 1, 'a1'), 1)
    p = gestureDecorativeOff(p, 1)
    assert.equal(p.cells[1].image?.alt, null, 'back to no decision, not decorative')
    assert.equal(cellImageFieldProps(p.cells[1]).altUnset, true, 'checkbox is off')
  })

  test('decorative can be toggled repeatedly without sticking', () => {
    let p = gesturePickAsset(imageModeBlock(), 1, 'a1')
    for (let i = 0; i < 4; i++) {
      p = gestureDecorativeOn(p, 1)
      assert.equal(cellImageFieldProps(p.cells[1]).altUnset, false, `on, pass ${i}`)
      assert.equal(p.cells[1].image?.alt, '', `decorative, pass ${i}`)
      p = gestureDecorativeOff(p, 1)
      assert.equal(cellImageFieldProps(p.cells[1]).altUnset, true, `off, pass ${i}`)
      assert.equal(p.cells[1].image?.alt, null, `unset, pass ${i}`)
    }
  })

  test('clearing the alt field by hand marks the image decorative', () => {
    // Matches the image block: an emptied alt box is a recorded
    // decision, distinct from never having touched it.
    let p = gestureTypeAlt(gesturePickAsset(imageModeBlock(), 1, 'a1'), 1, 'A heron')
    p = gestureTypeAlt(p, 1, '')
    assert.equal(p.cells[1].image?.alt, '')
    assert.equal(cellImageFieldProps(p.cells[1]).altUnset, false)
  })

  test('all three states survive a save and reopen', () => {
    let p = gesturePickAsset(imageModeBlock(), 1, 'a1')
    for (const [gesture, expected] of [
      [gestureTypeAlt, 'Explicit'],
      [gestureDecorativeOn, ''],
      [gestureDecorativeOff, null],
    ] as const) {
      p = typeof expected === 'string' && expected !== ''
        ? (gesture as typeof gestureTypeAlt)(p, 1, expected)
        : (gesture as typeof gestureDecorativeOn)(p, 1)
      const reopened = decodeColumns(encodeColumns(p))
      assert.equal(reopened.cells[1].image?.alt, expected, String(expected))
      assert.deepEqual(cellImageFieldProps(reopened.cells[1]), cellImageFieldProps(p.cells[1]))
    }
  })
})


describe('captions', () => {
  test('a caption is stored, and clearing it stores null not an empty string', () => {
    let p = applyCaptionToCell(gesturePickAsset(imageModeBlock(), 1, 'a1'), 1, 'By the sea')
    assert.equal(p.cells[1].image?.caption, 'By the sea')
    assert.equal(cellImageFieldProps(p.cells[1]).caption, 'By the sea')
    p = applyCaptionToCell(p, 1, '   ')
    assert.equal(p.cells[1].image?.caption, null)
    assert.equal(cellImageFieldProps(p.cells[1]).caption, '')
  })
})


describe('the prop builder', () => {
  test('reports an empty, unset state for a column with no image', () => {
    assert.deepEqual(cellImageFieldProps(imageModeBlock().cells[1]), {
      mediaAssetId: null, embedUrl: '', caption: '', altText: '', altUnset: true,
    })
  })

  test('shows a library image in the picker and not the url box', () => {
    const props = cellImageFieldProps(gesturePickAsset(imageModeBlock(), 1, 'a1').cells[1])
    assert.equal(props.mediaAssetId, 'a1')
    assert.equal(props.embedUrl, '')
  })

  test('shows an external image in the url box and not the picker', () => {
    const p = applyEmbedUrlToCell(imageModeBlock(), 1, 'https://example.org/p.jpg')
    const props = cellImageFieldProps(p.cells[1])
    assert.equal(props.mediaAssetId, null)
    assert.equal(props.embedUrl, 'https://example.org/p.jpg')
  })

  test('tolerates a missing cell', () => {
    assert.deepEqual(cellImageFieldProps(undefined), {
      mediaAssetId: null, embedUrl: '', caption: '', altText: '', altUnset: true,
    })
  })
})
