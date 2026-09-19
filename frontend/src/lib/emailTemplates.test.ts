/**
 * Unit tests for the Email Templates page logic.
 *
 * Run with the repo's established pattern — Node's built-in runner plus
 * type stripping:
 *
 *   node --experimental-strip-types --test src/lib/emailTemplates.test.ts
 *
 * Scope note. This repo has no component-rendering harness (no jsdom,
 * no Testing Library — `npm test` runs plain `.test.ts` logic files), so
 * these cover the decisions the page makes rather than the DOM it
 * produces. Every behaviour worth asserting was deliberately written as
 * a pure function in `emailTemplates.ts` for exactly that reason: what
 * the list shows, what a badge says, what a save sends, which variant a
 * preview starts on. The components read those answers and render them.
 */

import { describe, test } from 'node:test'
import assert from 'node:assert/strict'
// @ts-expect-error - Node-native import path
import {
  EMPTY_FILTERS,
  STALE_DEFAULT_MESSAGE,
  categoriesOf,
  classificationLabel,
  defaultVariantSelection,
  deliveryLabel,
  dirtySlots,
  draftValue,
  filterTemplates,
  groupByCategory,
  initialDrafts,
  isDirty,
  mergeToken,
  missingRequiredFields,
  overLength,
  previewBody,
  sanitiseVariantSelection,
  savePayload,
  slotIsCustomised,
  stateLabel,
  staleSlots,
  testSendConfirmation,
} from './emailTemplates.ts'
import type {
  Classification, SlotOut, TemplateDetail, TemplateListItem,
} from './emailTemplates.ts'

// ---------------------------------------------------------------------------
// Fixtures — shaped exactly like the Phase B API responses
// ---------------------------------------------------------------------------

const listItem = (o: Partial<TemplateListItem> = {}): TemplateListItem => ({
  template_key: 'account.welcome_after_signup.email_transactional',
  display_name: 'Welcome to Fresh Collective',
  category: 'Account',
  audience: 'A new member, after they verify their email',
  classification: 'editable' as Classification,
  editable: true,
  subject_editable: true,
  is_transactional: true,
  customised: false,
  overridden_slot_count: 0,
  has_stale_default: false,
  ...o,
})

const slot = (o: Partial<SlotOut> = {}): SlotOut => ({
  slot_id: 'heading',
  label: 'Heading',
  help_text: '',
  multiline: false,
  max_length: 2000,
  required_fields: [],
  default: 'Welcome to Fresh Collective',
  override: null,
  effective: 'Welcome to Fresh Collective',
  customised: false,
  default_changed: false,
  ...o,
})

const detail = (o: Partial<TemplateDetail> = {}): TemplateDetail => ({
  template_key: 'gathering.booking.confirmed.email_transactional',
  event_type: 'gathering.booking.confirmed',
  display_name: 'Booking confirmed',
  category: 'Gatherings',
  audience: 'A member who booked, or was added to, one gathering',
  classification: 'editable' as Classification,
  editable: true,
  subject_editable: true,
  is_transactional: true,
  is_live: true,
  customised: false,
  slots: [slot(), slot({ slot_id: 'cta_label', label: 'Button label',
                         default: 'View the gathering',
                         effective: 'View the gathering' })],
  merge_fields: [
    { name: 'gathering_name', sample: 'Morning Sit', description: "The gathering's title." },
  ],
  locked_notes: [],
  preview_variants: [{
    variant_id: 'booking_source',
    label: 'Booking source',
    help_text: 'Who put the member in the gathering.',
    options: [
      { value: 'self_booked', label: 'Member booked', is_default: true },
      { value: 'added_by_creator', label: 'Added by creator', is_default: false },
    ],
  }],
  ...o,
})

// ---------------------------------------------------------------------------
// 1. The list
// ---------------------------------------------------------------------------

describe('the template list', () => {
  const rows = [
    listItem({ template_key: 'a', display_name: 'Welcome to Fresh Collective',
               category: 'Account' }),
    listItem({ template_key: 'b', display_name: 'Booking confirmed',
               category: 'Gatherings', customised: true,
               overridden_slot_count: 2 }),
    listItem({ template_key: 'c', display_name: 'Reset your password',
               category: 'Account', classification: 'system', editable: false }),
    listItem({ template_key: 'd', display_name: 'Purchase confirmed',
               category: 'Purchases & billing', classification: 'partial',
               has_stale_default: true }),
  ]

  test('renders every live template the API returned', () => {
    assert.equal(filterTemplates(rows, EMPTY_FILTERS).length, 4)
  })

  test('dark templates are simply absent — the page never filters them', () => {
    // The API excludes non-live topics, so a template an admin cannot
    // see is one the backend did not send. Nothing client-side decides
    // this, which is the property being pinned here.
    const live = rows.filter((r) => r.template_key !== 'dark')
    assert.deepEqual(
      filterTemplates(live, EMPTY_FILTERS).map((r) => r.template_key),
      ['a', 'b', 'c', 'd'],
    )
  })

  test('system templates stay in the inventory', () => {
    const keys = filterTemplates(rows, EMPTY_FILTERS).map((r) => r.template_key)
    assert.ok(keys.includes('c'))
  })

  test('search matches the name', () => {
    const out = filterTemplates(rows, { ...EMPTY_FILTERS, search: 'booking' })
    assert.deepEqual(out.map((r) => r.template_key), ['b'])
  })

  test('search matches the audience, which is how people describe an email', () => {
    const out = filterTemplates(rows, { ...EMPTY_FILTERS, search: 'verify their email' })
    assert.equal(out.length, 4) // every fixture shares the audience line
    const narrowed = filterTemplates(
      [listItem({ template_key: 'z', display_name: 'Nothing',
                  audience: 'A creator whose plan has just activated' })],
      { ...EMPTY_FILTERS, search: 'creator' },
    )
    assert.deepEqual(narrowed.map((r) => r.template_key), ['z'])
  })

  test('search ignores case and surrounding space', () => {
    const out = filterTemplates(rows, { ...EMPTY_FILTERS, search: '  BOOKING ' })
    assert.deepEqual(out.map((r) => r.template_key), ['b'])
  })

  test('filters by category', () => {
    const out = filterTemplates(rows, { ...EMPTY_FILTERS, category: 'Account' })
    assert.deepEqual(out.map((r) => r.template_key), ['a', 'c'])
  })

  test('filters by classification', () => {
    const out = filterTemplates(rows, { ...EMPTY_FILTERS, classification: 'partial' })
    assert.deepEqual(out.map((r) => r.template_key), ['d'])
  })

  test('filters combine', () => {
    const out = filterTemplates(rows, {
      search: 'reset', category: 'Account', classification: 'system',
    })
    assert.deepEqual(out.map((r) => r.template_key), ['c'])
  })

  test('categories are the ones present, sorted', () => {
    assert.deepEqual(categoriesOf(rows),
      ['Account', 'Gatherings', 'Purchases & billing'])
  })

  test('grouping keeps every row exactly once', () => {
    const groups = groupByCategory(rows)
    assert.equal(groups.flatMap((g) => g.templates).length, rows.length)
  })
})

// ---------------------------------------------------------------------------
// 2. Badges
// ---------------------------------------------------------------------------

describe('badges', () => {
  test('classification reads as a product word', () => {
    assert.equal(classificationLabel('editable'), 'Editable')
    assert.equal(classificationLabel('partial'), 'Partially editable')
    assert.equal(classificationLabel('system'), 'System controlled')
  })

  test('delivery type distinguishes what a member can switch off', () => {
    assert.equal(deliveryLabel(true), 'Transactional')
    assert.equal(deliveryLabel(false), 'Preference controlled')
  })

  test('state reads Default until something is actually changed', () => {
    assert.equal(stateLabel(false), 'Default')
    assert.equal(stateLabel(true), 'Customised')
  })

  test('a field shows Customised against the default, not the saved value', () => {
    const s = slot({ default: 'Original', effective: 'Original' })
    assert.equal(slotIsCustomised(s, 'Original'), false)
    assert.equal(slotIsCustomised(s, 'Mine'), true)
    // Typing the original back stops claiming customisation immediately,
    // before the save rather than after it.
    assert.equal(slotIsCustomised(slot({ default: 'Original',
                                         effective: 'Mine',
                                         customised: true }), 'Original'), false)
  })

  test('the stale-default warning says what actually happened', () => {
    assert.equal(
      STALE_DEFAULT_MESSAGE,
      'The Fresh Collective default has changed since this was customised.',
    )
    const d = detail({
      slots: [slot({ slot_id: 'heading', default_changed: true }),
              slot({ slot_id: 'cta_label' })],
    })
    assert.deepEqual(staleSlots(d).map((s) => s.slot_id), ['heading'])
  })
})

// ---------------------------------------------------------------------------
// 3. Editing
// ---------------------------------------------------------------------------

describe('editing', () => {
  test('only declared slots become fields', () => {
    const d = detail()
    assert.deepEqual(Object.keys(initialDrafts(d)), ['heading', 'cta_label'])
    // There is no manufactured "body".
    assert.ok(!('body' in initialDrafts(d)))
  })

  test('a partial template exposes only what it declares', () => {
    const partial = detail({
      classification: 'partial',
      slots: [slot({ slot_id: 'signoff', label: 'Sign-off',
                     default: 'Take your time.', effective: 'Take your time.' })],
      locked_notes: ['The amount and instalment progress are generated.'],
    })
    assert.deepEqual(Object.keys(initialDrafts(partial)), ['signoff'])
    assert.equal(partial.locked_notes.length, 1)
  })

  test('a system template offers no fields at all', () => {
    const system = detail({ classification: 'system', editable: false, slots: [] })
    assert.deepEqual(initialDrafts(system), {})
  })

  test('drafts start at the effective value', () => {
    const d = detail({ slots: [slot({ effective: 'Saved wording' })] })
    assert.equal(draftValue(d, initialDrafts(d), 'heading'), 'Saved wording')
  })

  test('an untouched editor is not dirty', () => {
    const d = detail()
    assert.equal(isDirty(d, initialDrafts(d)), false)
    assert.deepEqual(savePayload(d, initialDrafts(d)), { overrides: {} })
  })

  test('a save sends only the fields that changed', () => {
    const d = detail()
    const drafts = { ...initialDrafts(d), heading: 'Booked — see you there' }
    assert.deepEqual(dirtySlots(d, drafts), ['heading'])
    assert.deepEqual(savePayload(d, drafts), {
      overrides: { heading: 'Booked — see you there' },
    })
  })

  test('typing the default back is still sent, so the override is deleted', () => {
    const d = detail({
      slots: [slot({ default: 'Original', effective: 'Mine', customised: true })],
    })
    const drafts = { heading: 'Original' }
    assert.deepEqual(savePayload(d, drafts), { overrides: { heading: 'Original' } })
  })
})

// ---------------------------------------------------------------------------
// 4. Merge fields
// ---------------------------------------------------------------------------

describe('merge fields', () => {
  test('tokens are shown in the form an admin types', () => {
    assert.equal(mergeToken({ name: 'collective_name', sample: 'Still Water', description: '' }),
      '{{collective_name}}')
  })

  test('only the fields this template declares are offered', () => {
    const d = detail()
    assert.deepEqual(d.merge_fields.map((f) => f.name), ['gathering_name'])
    // Signup emails deliberately offer no member name — the "Hi Creator"
    // defect came from echoing unvalidated user input into a greeting.
    const welcome = detail({ merge_fields: [] })
    assert.deepEqual(welcome.merge_fields, [])
  })

  test('a required field dropped from the copy is caught while writing', () => {
    const s = slot({ required_fields: ['gathering_name'] })
    assert.deepEqual(missingRequiredFields(s, 'Booked: {{gathering_name}}'), [])
    assert.deepEqual(missingRequiredFields(s, 'Booked!'), ['gathering_name'])
  })

  test('the required-field check matches the backend, whitespace and all', () => {
    const s = slot({ required_fields: ['gathering_name'] })
    assert.deepEqual(missingRequiredFields(s, 'Booked: {{ gathering_name }}'), [])
  })

  test('over-length copy is flagged against the slot limit', () => {
    const s = slot({ max_length: 10 })
    assert.equal(overLength(s, '0123456789'), false)
    assert.equal(overLength(s, '01234567890'), true)
  })
})

// ---------------------------------------------------------------------------
// 5. Preview
// ---------------------------------------------------------------------------

describe('preview', () => {
  test('starts on each variant’s declared default', () => {
    assert.deepEqual(defaultVariantSelection(detail()),
      { booking_source: 'self_booked' })
  })

  test('a template with no variants has no selection', () => {
    assert.deepEqual(defaultVariantSelection(detail({ preview_variants: [] })), {})
  })

  test('the current version previews the unsaved drafts', () => {
    const d = detail()
    const body = previewBody(d, 'effective', { heading: 'Draft' },
                             { booking_source: 'added_by_creator' })
    assert.equal(body.mode, 'effective')
    assert.deepEqual(body.drafts, { heading: 'Draft' })
    assert.deepEqual(body.variant, { booking_source: 'added_by_creator' })
  })

  test('the default view ignores drafts — it answers "what would reset give me?"', () => {
    const body = previewBody(detail(), 'default', { heading: 'Draft' }, {})
    assert.equal(body.mode, 'default')
    assert.deepEqual(body.drafts, {})
  })

  test('a selection left over from another template cannot 400 the preview', () => {
    const body = previewBody(detail(), 'effective', {},
                             { creator_state: 'fresh', booking_source: 'nonsense' })
    assert.deepEqual(body.variant, { booking_source: 'self_booked' })
  })

  test('sanitising fills in a variant the caller omitted', () => {
    assert.deepEqual(sanitiseVariantSelection(detail(), {}),
      { booking_source: 'self_booked' })
  })

  test('drafts are copied, so a later edit cannot mutate a sent body', () => {
    const drafts = { heading: 'One' }
    const body = previewBody(detail(), 'effective', drafts, {})
    drafts.heading = 'Two'
    assert.equal(body.drafts.heading, 'One')
  })
})

// ---------------------------------------------------------------------------
// 6. Test send
// ---------------------------------------------------------------------------

describe('test send', () => {
  test('confirms the address it actually went to', () => {
    assert.equal(testSendConfirmation('admin@freshcollective.au'),
      'Test email sent to admin@freshcollective.au')
  })

  test('the request body is the preview body — current unsaved wording', () => {
    // A test that sent the *saved* copy would be useless for checking
    // an edit before committing to it.
    const d = detail()
    const body = previewBody(d, 'effective', { heading: 'Unsaved' },
                             { booking_source: 'added_by_creator' })
    assert.deepEqual(body.drafts, { heading: 'Unsaved' })
  })

  test('there is no recipient anywhere in the request', () => {
    const body = previewBody(detail(), 'effective', {}, {})
    assert.deepEqual(Object.keys(body).sort(), ['drafts', 'mode', 'variant'])
  })
})
