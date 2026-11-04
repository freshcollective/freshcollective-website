import { strict as assert } from 'node:assert'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, it } from 'node:test'

const SRC = join(process.cwd(), 'src')
const FORM = join(
  SRC, 'app', 'creator-studio', 'settings', 'CollectiveSettingsForm.tsx',
)
const MEMBER_HEADER = join(
  SRC, 'components', 'spaces', 'CollectiveIdentityHeader.tsx',
)
const STUDIO_HEADER = join(
  SRC, 'components', 'creator', 'CollectiveArtworkHeader.tsx',
)

const form = () => readFileSync(FORM, 'utf8')

/**
 * The editor is a React client component and this harness has no DOM
 * or FileReader, so file selection and upload cannot be driven here.
 * These are source-shape checks over the decisions that were wrong:
 * whether choosing an image uploads it, what is validated before the
 * request, and which field each display surface reads.
 */

describe('choosing a banner uploads it', () => {
  it('selection triggers the upload, as the logo does', () => {
    // The defect: it only staged the file. Pressing the form's Save
    // button — the obvious thing, at the foot of the page — reported
    // success while the banner had never been sent.
    const source = form()
    const select = source.slice(
      source.indexOf('function handleFileSelect'),
      source.indexOf('async function uploadBanner'),
    )
    assert.ok(
      /void uploadBanner\(file\)/.test(select),
      'choosing a banner no longer uploads it',
    )
  })

  it('there is no separate upload step to miss', () => {
    const source = form()
    assert.ok(
      !/onClick=\{uploadBanner\}/.test(source),
      'the two-step upload button is back',
    )
    assert.ok(
      !/Upload banner</.test(source),
      'the "Upload banner" step is back',
    )
  })

  it('a failed upload leaves a retry', () => {
    // So a creator is not left with a staged file and no way to send it.
    const source = form()
    assert.ok(/bannerFile && bannerError && !bannerUploading/.test(source))
    assert.ok(/Try again/.test(source))
  })

  it('cannot be submitted twice at once', () => {
    assert.ok(/if \(!chosen \|\| bannerUploading\) return/.test(form()))
  })

  it('shows that an upload is in progress', () => {
    const source = form()
    assert.ok(/\{bannerUploading && \(/.test(source))
    assert.ok(/Uploading&hellip;/.test(source))
  })
})

describe('what is checked before the request', () => {
  it('accepts a JPG whose MIME type is missing', () => {
    // Some browsers and operating systems hand over an empty `type`
    // for a perfectly good JPG. The logo has always accepted either;
    // the banner was MIME-only and rejected it.
    const source = form()
    const select = source.slice(
      source.indexOf('function handleFileSelect'),
      source.indexOf('async function uploadBanner'),
    )
    assert.ok(/ALLOWED_IMAGE_TYPES\.includes\(file\.type\)/.test(select))
    assert.ok(/\\\.\(jpe\?g\|png\)\$/.test(select) || /jpe\?g\|png/.test(select))
  })

  it('enforces the size limit the copy states', () => {
    const source = form()
    assert.ok(/const MAX_IMAGE_BYTES = 10 \* 1024 \* 1024/.test(source))
    assert.ok(/file\.size > MAX_IMAGE_BYTES/.test(source))
    assert.ok(/larger than 10 MB/.test(source))
    // And the copy and the constant agree.
    assert.ok(/Max 10 MB/.test(source))
  })

  it('refuses the formats the server refuses', () => {
    const source = form()
    assert.ok(/ALLOWED_IMAGE_TYPES = \['image\/jpeg', 'image\/png'\]/.test(source))
    assert.ok(!/image\/svg/.test(source), 'SVG became selectable')
    assert.ok(!/image\/gif/.test(source), 'GIF became selectable')
  })

  it('the stale TODO about storage is gone', () => {
    // It claimed the upload API was not available in production. It
    // has been for a long time, and the comment sent the next reader
    // looking for a missing endpoint.
    assert.ok(!/TODO: Connect banner upload to storage/.test(form()))
  })
})

describe('what happens after a successful upload', () => {
  it('the saved URL comes from the response, not the local file', () => {
    // The preview is a local object URL; only the response says what
    // was actually stored.
    const source = form()
    assert.ok(/setExistingBanner\(data\.cover_image_url \?\? null\)/.test(source))
    assert.ok(/setBannerPreview\(null\)/.test(source))
  })

  it('the surrounding page is refreshed', () => {
    // The header above the form, and every other server-rendered
    // surface, holds the old value in the router cache — without this
    // the new image appears only after a manual reload, which reads
    // as "it did not save".
    const source = form()
    const banner = source.slice(
      source.indexOf('async function uploadBanner'),
      source.indexOf('async function selectPreference'),
    )
    assert.ok(/router\.refresh\(\)/.test(banner))
  })

  it('the logo refreshes too', () => {
    const source = form()
    const logo = source.slice(
      source.indexOf('async function uploadLogo'),
      source.indexOf('async function removeLogo'),
    )
    assert.ok(/router\.refresh\(\)/.test(logo))
  })

  it('a failure reports the server message and keeps the old banner', () => {
    const source = form()
    const banner = source.slice(
      source.indexOf('async function uploadBanner'),
      source.indexOf('async function selectPreference'),
    )
    assert.ok(/typeof b\.detail === 'string' \? b\.detail/.test(banner))
    assert.ok(/setBannerError\(/.test(banner))
    // `existingBanner` is only ever reassigned from a 200 response.
    //
    // Matched on the error handler, not the word: `res.json().catch()`
    // sits a few lines above the legitimate `setExistingBanner`, and a
    // bare /catch/ matched that instead.
    const handler = banner.slice(banner.indexOf('} catch (err) {'))
    assert.ok(
      !/setExistingBanner/.test(handler),
      'a failed upload overwrites the saved banner in state',
    )
  })

  it('success is only reported after the response', () => {
    const source = form()
    const banner = source.slice(
      source.indexOf('async function uploadBanner'),
      source.indexOf('async function selectPreference'),
    )
    const responseAt = banner.indexOf('const data = await res.json()')
    const savedAt = banner.indexOf('setBannerSaved(true)')
    assert.ok(responseAt > -1 && savedAt > responseAt, 'success is claimed early')
  })
})

describe('the banner and the logo stay independent', () => {
  it('each has its own state, endpoint and error', () => {
    const source = form()
    for (const name of [
      'existingBanner', 'bannerError', 'bannerUploading',
      'existingLogo', 'logoError', 'logoUploading',
    ]) {
      assert.ok(source.includes(name), `missing ${name}`)
    }
    assert.ok(/\/cover`/.test(source))
    assert.ok(/\/logo`/.test(source))
  })

  it('the settings save sends neither image field', () => {
    // So saving the form cannot overwrite an image.
    const source = form()
    const submit = source.slice(
      source.indexOf('async function handleSubmit'),
      source.indexOf('const SLUG_RE') > source.indexOf('async function handleSubmit')
        ? source.indexOf('const SLUG_RE')
        : source.length,
    )
    const body = source.slice(
      source.indexOf('body: JSON.stringify({'),
      source.indexOf('if (!res.ok) {'),
    )
    assert.ok(!/cover_image_url/.test(body), 'the save sends cover_image_url')
    assert.ok(!/logo_url/.test(body), 'the save sends logo_url')
    assert.ok(submit.length > 0)
  })
})

describe('the agreed header-image design', () => {
  it('the member Collective header follows the creator choice', () => {
    // Changed deliberately. It used to prefer Location artwork
    // unconditionally — `locationArt ?? legacyBanner` — which is why
    // an uploaded banner appeared nowhere. Phase 1 makes it the
    // creator's choice, through the one shared rule.
    const header = readFileSync(MEMBER_HEADER, 'utf8')
    assert.ok(
      /selectCollectiveHeaderImage\(\{/.test(header),
      'the member header no longer uses the shared rule',
    )
    assert.ok(
      !/const backgroundImage = locationArt \?\? legacyBanner/.test(header),
      'the unconditional Location-first precedence is back',
    )
  })

  it('the Creator Studio header follows it too', () => {
    const header = readFileSync(STUDIO_HEADER, 'utf8')
    assert.ok(/selectCollectiveHeaderImage\(\{/.test(header))
    assert.ok(
      !/\?\? location\?\.thumbnail_artwork_url\s*\n?\s*\?\? coverImageUrl/.test(header),
      'the old unconditional chain is back',
    )
  })

  it('the settings section is the agreed header-image chooser', () => {
    const source = form()
    assert.ok(/Collective header image/.test(source))
    assert.ok(/Choose the image that welcomes people into your Collective/.test(source))
    assert.ok(/Use my Location artwork/.test(source))
    assert.ok(/Use my own banner/.test(source))
    assert.ok(
      !/If no separate banner is uploaded/.test(source),
      'the inverted precedence copy is back',
    )
  })

  it('both sources are previewed, so they can be compared', () => {
    const source = form()
    assert.ok(/imageUrl=\{locationArtwork\}/.test(source))
    assert.ok(/imageUrl=\{bannerPreview \?\? existingBanner\}/.test(source))
    // Matched as the JSX it was, not as the words: two comments
    // explain the old line, and a bare substring check failed on the
    // prose describing what it replaced.
    assert.ok(
      !/Banner uploaded\.\{' '\}/.test(source),
      'the "a file exists" line is back in place of a preview',
    )
  })

  it('the preview is the header shape and is not distorted', () => {
    const source = form()
    assert.ok(/aspectRatio: '16 \/ 5'/.test(source))
    assert.ok(/object-cover/.test(source))
  })

  it('offers Upload, Replace and Remove', () => {
    const source = form()
    assert.ok(/existingBanner \? 'Replace image' : 'Upload banner'/.test(source))
    assert.ok(/Remove banner/.test(source))
    assert.ok(/onClick=\{removeBanner\}/.test(source))
  })

  it('switching sources does not re-upload', () => {
    const source = form()
    const select = source.slice(
      source.indexOf('async function selectPreference'),
      source.indexOf('async function removeBanner'),
    )
    assert.ok(/header_image_preference: next/.test(select))
    assert.ok(!/FormData/.test(select), 'switching sends a file again')
  })

  it('the chooser is a radio group, not two loose buttons', () => {
    const source = form()
    assert.ok(/role="radiogroup"/.test(source))
    assert.ok(/role="radio"/.test(source))
    assert.ok(/aria-checked=\{selected\}/.test(source))
  })

  it('an option with no image cannot be chosen', () => {
    const source = form()
    assert.ok(/disabled=\{!locationArtwork\}/.test(source))
    assert.ok(/disabled=\{!existingBanner && !bannerPreview\}/.test(source))
  })

  it('the cards and signup still show the Collective image', () => {
    // These read the banner with no Location fallback before, so they
    // now read the resolved choice instead — the same field either way.
    for (const [path, needle] of [
      [join(SRC, 'app', 'dashboard', 'CreatorCollectiveCard.tsx'),
        'selectCollectiveHeaderImage'],
      [join(SRC, 'app', 'signup', 'member', 'page.tsx'), 'headerImageFor'],
      [join(SRC, 'app', 'checkout', 'member', 'page.tsx'), 'headerImageFor'],
      [join(SRC, 'components', 'explore', 'CollectiveCard.tsx'), 'headerImageFor'],
    ] as [string, string][]) {
      assert.ok(
        readFileSync(path, 'utf8').includes(needle),
        `${path} does not use the shared rule`,
      )
    }
  })
})

describe('World Artwork is untouched', () => {
  it('the settings form never mentions it', () => {
    const source = form()
    for (const forbidden of ['island_artwork', 'islandArtwork', 'world-artwork']) {
      assert.ok(!source.includes(forbidden), `the form touches ${forbidden}`)
    }
  })
})
