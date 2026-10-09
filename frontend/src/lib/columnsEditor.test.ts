import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const SRC = readFileSync(join(root, 'components/creator/BlockEditorShared.tsx'), 'utf8')

const EDITOR = SRC.slice(SRC.indexOf('function ColumnsEditor'))
const PREVIEW = SRC.slice(
  SRC.indexOf('function ColumnsPreview'),
  SRC.indexOf('function ColumnsEditor'),
)

/**
 * The Creator Studio side of columns images.
 *
 * The behavioural work is tested elsewhere — the data layer in
 * columnsBlock.test.ts and the fiddly control mapping in
 * columnsImageFields.test.ts, both against real call sequences. What is
 * left here is wiring, and two things learned the hard way in this
 * backlog:
 *
 *   - A control with no label reads as missing. The exercise response
 *     toggle was reported as absent when it was rendering perfectly,
 *     because it was the only control in the form without a
 *     ``field-label`` above it.
 *
 *   - Image handling must reuse ImageBlockFields and the one media
 *     endpoint. A second uploader here would be a second set of
 *     validation rules to keep in step.
 */

describe('the content type control', () => {
  test('every column gets its own, labelled', () => {
    assert.match(EDITOR, /<label className="field-label" id=\{`col-\$\{i\}-type-label`\}>\s*Content type/)
  })

  test('is a two-option segmented control driven by the shared list', () => {
    assert.match(EDITOR, /COLUMNS_CELL_KINDS\.map\(\(k\) => \{/)
    assert.match(EDITOR, /\{k === 'text' \? 'Text' : 'Image'\}/)
  })

  test('announces which option is active', () => {
    assert.match(EDITOR, /aria-pressed=\{on\}/)
    assert.match(EDITOR, /role="group"/)
    assert.match(EDITOR, /aria-labelledby=\{`col-\$\{i\}-type-label`\}/)
  })

  test('switching goes through the non-destructive data-layer helper', () => {
    assert.match(EDITOR, /setPayload\(\(prev\) => setCellKind\(prev, i, kind\)\)/)
  })

  test('there is no confirmation dialog on switching', () => {
    // Match calls, not the word: the function's own comment explains
    // that there is nothing to confirm, and a blunt substring check
    // would trip on that.
    const changeKind = EDITOR.slice(
      EDITOR.indexOf('function changeKind'),
      EDITOR.indexOf('// --- image controls'),
    )
    assert.ok(changeKind.length > 0 && changeKind.length < 1000, 'slice bounds')
    assert.ok(!/\bconfirm\s*\(/.test(changeKind), 'calls confirm()')
    assert.ok(!/setConfirm\w*\s*\(/.test(changeKind), 'opens a confirm dialog')
  })
})

describe('image mode reuses the existing controls', () => {
  test('renders ImageBlockFields, not a bespoke picker', () => {
    assert.match(EDITOR, /<ImageBlockFields/)
    assert.match(EDITOR, /\{\.\.\.cellImageFieldProps\(cell\)\}/)
  })

  test('text mode still renders the rich text editor unchanged', () => {
    assert.match(EDITOR, /<RichTextEditor\s+content=\{cell\.content\}/)
    assert.match(EDITOR, /minRows=\{6\}/)
  })

  test('every image callback delegates to the tested adapter', () => {
    for (const fn of [
      'applyAssetToCell', 'applyAssetIdToCell', 'applyEmbedUrlToCell',
      'applyAltTextToCell', 'applyAltUnsetToCell', 'applyCaptionToCell',
    ]) {
      assert.ok(EDITOR.includes(fn), `${fn} not used by the editor`)
    }
  })

  test('the editor holds no alt-state logic of its own', () => {
    // If this grows back, it will drift from the adapter's tests.
    assert.ok(!/altUnset \?/.test(EDITOR), 'alt branching leaked back into the component')
    assert.ok(!/alt: value/.test(EDITOR))
  })
})

describe('uploads', () => {
  test('still use the one existing media endpoint', () => {
    const posts = SRC.match(/\/api\/creator\/spaces\/\$\{spaceSlug\}\/media/g) ?? []
    assert.equal(posts.length, 1, 'there must be exactly one media upload path')
    assert.match(SRC, /method: 'POST',\s*credentials: 'include',\s*body: form,/)
  })

  test('land in the column they were started from', () => {
    assert.match(EDITOR, /setUploadingCell\(i\)/)
    assert.match(EDITOR, /onUploadFile\(file, \(asset\) => applyAsset\(i, asset\)\)/)
  })

  test('show progress and errors only on that column', () => {
    assert.match(EDITOR, /uploadBusy=\{uploadBusy && uploadingCell === i\}/)
    assert.match(EDITOR, /uploadError=\{uploadingCell === i \? uploadError : null\}/)
  })

  test('cannot write into a closed editor', () => {
    // An upload can outlive the form; a late resolve must not call
    // setState on an unmounted tree, nor write into a payload nobody
    // is editing any more.
    assert.match(SRC, /const mounted = useRef\(true\)/)
    assert.match(SRC, /useEffect\(\(\) => \(\) => \{ mounted\.current = false \}, \[\]\)/)
    assert.match(SRC, /if \(!mounted\.current\) return/)
    assert.match(SRC, /if \(mounted\.current\) setUploadError/)
    assert.match(SRC, /if \(mounted\.current\) setUploadBusy\(false\)/)
  })

  test('still register the finished asset with the library even if the form closed', () => {
    // The upload succeeded and the asset exists; the parent's list
    // outlives this form.
    const order = SRC.indexOf('onAssetUploaded?.(asset)')
    const guard = SRC.indexOf('if (!mounted.current) return')
    assert.ok(order > 0 && guard > order, 'asset registration must precede the mount guard')
  })

  test('the editor is given what it needs to upload', () => {
    assert.match(EDITOR, /assets: CreatorMediaAsset\[\]/)
    assert.match(EDITOR, /spaceSlug\?: string/)
    assert.match(SRC, /onUploadFile=\{\(file, onUploaded\) => void uploadFromDevice\(file, onUploaded\)\}/)
  })
})

describe('the editor layout', () => {
  test('renders only the active columns', () => {
    assert.match(EDITOR, /const cells = activeCells\(payload\)/)
    assert.ok(!/payload\.cells\.map/.test(EDITOR), 'editor maps raw cells')
  })

  test('gives image controls full width instead of a quarter column', () => {
    assert.match(EDITOR, /const anyImage = cells\.some\(\(cell\) => cellKind\(cell\) === 'image'\)/)
    assert.match(EDITOR, /anyImage\s*\?\s*'space-y-6'/)
  })

  test('text-only blocks keep the side-by-side editing they had', () => {
    assert.match(EDITOR, /: 'fc-columns-grid grid items-start gap-4'/)
    assert.match(EDITOR, /gridTemplateForVariant\(payload\.layout\.variant\)/)
  })

  test('tells the creator when a narrower layout has parked content', () => {
    // Not destroyed — but they should not have to guess that.
    assert.match(EDITOR, /parkedCells\(payload\)\.filter\(cellIsPopulated\)\.length/)
    assert.match(EDITOR, /being kept aside because this layout is narrower/)
  })
})

describe('the block-stack preview', () => {
  test('shows real images, not placeholders', () => {
    assert.match(PREVIEW, /<img\s+src=\{resolveAssetUrl\(url\)\}/)
    assert.match(PREVIEW, /alt=\{cellImageAlt\(cell\.image\)\}/)
  })

  test('keeps aspect ratio', () => {
    assert.match(PREVIEW, /className="h-auto w-full rounded-md"/)
    assert.ok(!/object-cover/.test(PREVIEW))
  })

  test('shows captions when present', () => {
    assert.match(PREVIEW, /cell\.image\?\.caption\?\.trim\(\) &&/)
    assert.match(PREVIEW, /<figcaption/)
  })

  test('only falls back to an empty state when there is genuinely nothing', () => {
    assert.match(PREVIEW, /if \(!url\) return empty\('click Edit to choose an image\.'\)/)
    assert.match(PREVIEW, /if \(!cell\.content\?\.trim\(\)\) return empty\('click Edit to add content\.'\)/)
  })

  test('uses the same responsive rules as the published page', () => {
    assert.match(PREVIEW, /data-cols=\{cellCountForVariant\(variant\)\}/)
    assert.match(PREVIEW, /items-start/)
  })

  test('renders only the active columns', () => {
    assert.match(PREVIEW, /activeCells\(payload\)\.map/)
  })
})
