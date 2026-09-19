/**
 * World Management → Communications → Email Templates.
 *
 * Types mirroring the admin API, plus the page's decision logic kept
 * out of the components so it can be tested with the repo's existing
 * `node --test` pattern.
 *
 * Two rules this module exists to hold in one place:
 *
 * **The backend is authoritative.** Nothing here decides what is
 * editable, which templates are live, or whether a value is valid. It
 * derives labels and diffs from what the API returned.
 *
 * **Only changed fields are saved.** A save sends the slots the admin
 * actually touched. Sending everything would re-stamp attribution and
 * fingerprints on copy nobody edited, quietly claiming authorship of
 * Fresh Collective's own wording.
 */

// ---------------------------------------------------------------------------
// API shapes
// ---------------------------------------------------------------------------

export type Classification = 'editable' | 'partial' | 'system'

export interface TemplateListItem {
  template_key: string
  display_name: string
  category: string
  audience: string
  classification: Classification
  editable: boolean
  subject_editable: boolean
  is_transactional: boolean
  customised: boolean
  overridden_slot_count: number
  has_stale_default: boolean
}

export interface SlotOut {
  slot_id: string
  label: string
  help_text: string
  multiline: boolean
  max_length: number
  required_fields: string[]
  default: string
  override: string | null
  effective: string
  customised: boolean
  default_changed: boolean
}

export interface MergeFieldOut {
  name: string
  sample: string
  description: string
}

export interface PreviewVariantOption {
  value: string
  label: string
  is_default: boolean
}

export interface PreviewVariant {
  variant_id: string
  label: string
  help_text: string
  options: PreviewVariantOption[]
}

export interface TemplateDetail {
  template_key: string
  event_type: string
  display_name: string
  category: string
  audience: string
  classification: Classification
  editable: boolean
  subject_editable: boolean
  is_transactional: boolean
  is_live: boolean
  customised: boolean
  slots: SlotOut[]
  merge_fields: MergeFieldOut[]
  locked_notes: string[]
  preview_variants: PreviewVariant[]
}

export interface PreviewResponse {
  template_key: string
  mode: 'effective' | 'default'
  subject: string
  preheader: string | null
  html: string
  text: string
  effective_slots: Record<string, string>
  errors: Record<string, string[]>
}

export interface TestSendResponse {
  sent_to: string
  subject: string
  accepted: boolean
  detail: string | null
}

export type PreviewMode = 'effective' | 'default'
export type VariantSelection = Record<string, string>
export type Drafts = Record<string, string>

// ---------------------------------------------------------------------------
// Labels
// ---------------------------------------------------------------------------

export function classificationLabel(c: Classification): string {
  if (c === 'editable') return 'Editable'
  if (c === 'partial') return 'Partially editable'
  return 'System controlled'
}

/**
 * Transactional delivery is a promise about reach, not about copy: a
 * member cannot switch it off. Saying so beside a booking confirmation
 * answers the question an admin would otherwise have to go and look up.
 */
export function deliveryLabel(isTransactional: boolean): string {
  return isTransactional ? 'Transactional' : 'Preference controlled'
}

export function stateLabel(customised: boolean): string {
  return customised ? 'Customised' : 'Default'
}

export const STALE_DEFAULT_MESSAGE =
  'The Fresh Collective default has changed since this was customised.'

export function testSendConfirmation(email: string): string {
  return `Test email sent to ${email}`
}

// ---------------------------------------------------------------------------
// List filtering
// ---------------------------------------------------------------------------

export interface ListFilters {
  search: string
  category: string | null
  classification: Classification | null
}

export const EMPTY_FILTERS: ListFilters = {
  search: '',
  category: null,
  classification: null,
}

/**
 * Search matches the display name and the audience line. Audience is
 * included deliberately — an admin looking for "the one new creators
 * get" is describing the audience, not the title.
 */
export function filterTemplates(
  items: TemplateListItem[],
  filters: ListFilters,
): TemplateListItem[] {
  const needle = filters.search.trim().toLowerCase()
  return items.filter((t) => {
    if (filters.category && t.category !== filters.category) return false
    if (filters.classification && t.classification !== filters.classification) {
      return false
    }
    if (!needle) return true
    return (
      t.display_name.toLowerCase().includes(needle) ||
      t.audience.toLowerCase().includes(needle)
    )
  })
}

export function categoriesOf(items: TemplateListItem[]): string[] {
  return [...new Set(items.map((t) => t.category))].sort()
}

export function groupByCategory(
  items: TemplateListItem[],
): { category: string; templates: TemplateListItem[] }[] {
  return categoriesOf(items).map((category) => ({
    category,
    templates: items.filter((t) => t.category === category),
  }))
}

// ---------------------------------------------------------------------------
// Drafts
// ---------------------------------------------------------------------------

export function initialDrafts(detail: TemplateDetail): Drafts {
  const out: Drafts = {}
  for (const slot of detail.slots) out[slot.slot_id] = slot.effective
  return out
}

export function draftValue(
  detail: TemplateDetail, drafts: Drafts, slotId: string,
): string {
  if (slotId in drafts) return drafts[slotId]
  return detail.slots.find((s) => s.slot_id === slotId)?.effective ?? ''
}

/** Slot ids whose draft differs from what is currently in effect. */
export function dirtySlots(detail: TemplateDetail, drafts: Drafts): string[] {
  return detail.slots
    .filter((s) => s.slot_id in drafts && drafts[s.slot_id] !== s.effective)
    .map((s) => s.slot_id)
}

export function isDirty(detail: TemplateDetail, drafts: Drafts): boolean {
  return dirtySlots(detail, drafts).length > 0
}

/**
 * The save body: only what changed.
 *
 * A draft equal to the Fresh Collective default is still sent — the
 * backend deletes the override row rather than storing it, which is
 * how typing the original wording back genuinely returns to default.
 */
export function savePayload(
  detail: TemplateDetail, drafts: Drafts,
): { overrides: Drafts } {
  const overrides: Drafts = {}
  for (const slotId of dirtySlots(detail, drafts)) {
    overrides[slotId] = drafts[slotId]
  }
  return { overrides }
}

/**
 * Whether a field shows as customised *right now*, taking the unsaved
 * draft into account — a field edited back to the default should stop
 * claiming to be customised before the save, not after it.
 */
export function slotIsCustomised(slot: SlotOut, draft: string): boolean {
  return draft !== slot.default
}

export function staleSlots(detail: TemplateDetail): SlotOut[] {
  return detail.slots.filter((s) => s.default_changed)
}

// ---------------------------------------------------------------------------
// Preview variants
// ---------------------------------------------------------------------------

/**
 * The selection the preview starts on: each variant's declared default,
 * which matches the sample context the backend would use anyway.
 */
export function defaultVariantSelection(
  detail: TemplateDetail,
): VariantSelection {
  const out: VariantSelection = {}
  for (const v of detail.preview_variants) {
    const chosen = v.options.find((o) => o.is_default) ?? v.options[0]
    if (chosen) out[v.variant_id] = chosen.value
  }
  return out
}

/**
 * A selection the backend will accept: unknown ids and options are
 * dropped rather than sent, so a stale selection left over from the
 * previously-open template cannot turn a preview into a 400.
 */
export function sanitiseVariantSelection(
  detail: TemplateDetail, selection: VariantSelection,
): VariantSelection {
  const out: VariantSelection = {}
  for (const v of detail.preview_variants) {
    const wanted = selection[v.variant_id]
    const match = v.options.find((o) => o.value === wanted)
    out[v.variant_id] = (match ?? v.options.find((o) => o.is_default) ??
      v.options[0]).value
  }
  return out
}

export function previewBody(
  detail: TemplateDetail,
  mode: PreviewMode,
  drafts: Drafts,
  selection: VariantSelection,
): { mode: PreviewMode; drafts: Drafts; variant: VariantSelection } {
  return {
    mode,
    // Default mode asks "what would reset give me?" — drafts would
    // contradict the question.
    drafts: mode === 'default' ? {} : { ...drafts },
    variant: sanitiseVariantSelection(detail, selection),
  }
}

// ---------------------------------------------------------------------------
// Merge fields
// ---------------------------------------------------------------------------

export function mergeToken(field: MergeFieldOut): string {
  return `{{${field.name}}}`
}

/**
 * Fields a slot must keep to stay truthful. Dropping one is refused by
 * the API; naming them in the editor means an admin finds out while
 * writing rather than on save.
 */
export function missingRequiredFields(slot: SlotOut, value: string): string[] {
  // Same shape the backend matches: ``{{ field }}`` with optional inner
  // whitespace. A looser check here would flag copy the API accepts.
  const used = new Set(
    [...value.matchAll(/\{\{\s*([a-z][a-z0-9_]*)\s*\}\}/g)].map((m) => m[1]),
  )
  return slot.required_fields.filter((f) => !used.has(f))
}

export function overLength(slot: SlotOut, value: string): boolean {
  return value.length > slot.max_length
}
