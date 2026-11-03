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
      source.indexOf('async function uploadLogo'),
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
      source.indexOf('async function uploadLogo'),
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
      source.indexOf('async function uploadLogo'),
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

describe('the display hierarchy is unchanged and now described honestly', () => {
  it('Location artwork still leads on the member Collective pages', () => {
    // Deliberate and documented. Changing it is a design decision,
    // not a bug fix — so this asserts it did NOT change.
    const header = readFileSync(MEMBER_HEADER, 'utf8')
    assert.ok(
      /const backgroundImage = locationArt \?\? legacyBanner/.test(header),
      'the member header precedence changed',
    )
  })

  it('Location artwork still leads in Creator Studio', () => {
    const header = readFileSync(STUDIO_HEADER, 'utf8')
    assert.ok(
      /location\?\.hero_artwork_url\s*\n?\s*\?\? location\?\.thumbnail_artwork_url\s*\n?\s*\?\? coverImageUrl/
        .test(header),
      'the Creator Studio header precedence changed',
    )
  })

  it('the settings copy no longer claims the banner leads', () => {
    // It said "If no separate banner is uploaded, this collective will
    // use its Location artwork by default" — the inverse of what every
    // display surface does, which is why a save that worked read as a
    // save that failed.
    const source = form()
    assert.ok(
      !/If no separate banner is uploaded/.test(source),
      'the inverted precedence copy is back',
    )
    assert.ok(/Location artwork leads/.test(source))
  })

  it('the copy names where the banner IS used', () => {
    // It is not unused: the dashboard cards, sign-up and checkout read
    // `cover_image_url` with no Location fallback.
    const source = form()
    assert.ok(/cards in dashboards, sign-up and checkout/.test(source))
  })

  it('those surfaces still read the banner directly', () => {
    for (const [path, needle] of [
      [join(SRC, 'app', 'dashboard', 'CreatorCollectiveCard.tsx'),
        'detail?.cover_image_url'],
      [join(SRC, 'app', 'signup', 'member', 'page.tsx'),
        'collective.cover_image_url'],
      [join(SRC, 'app', 'checkout', 'member', 'page.tsx'),
        'collective.cover_image_url'],
    ] as [string, string][]) {
      assert.ok(
        readFileSync(path, 'utf8').includes(needle),
        `${path} no longer reads the banner`,
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
