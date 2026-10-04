/**
 * What to call the parts of a Pathway, and whether to talk about progress.
 *
 * Two Pathway types, one content model. A Guided Experience is a
 * sequence you work through — steps, completion, a progress bar, "Begin"
 * then "Continue". A Knowledge Guide is a reference document — sections
 * you look things up in, on one continuous page with anchors. Nobody
 * finishes a reference document, so counting how much of it you have
 * read is a measurement of nothing, and offering to "continue" implies
 * a position we do not store.
 *
 * The rows are still `steps` in the database and the API, and that is
 * fine: this is a presentation distinction and renaming the storage
 * would be a much larger change for no member benefit.
 *
 * Everything here reads `pathway_type`, the canonical enum — never a
 * title, never a slug, and never a string comparison scattered through
 * a component. One place to change if a third type ever appears.
 *
 * `pathway_type` is optional on some payload shapes, and absent means
 * the original behaviour: a Guided Experience. Defaulting that way
 * keeps every existing surface and every older cached response working
 * exactly as before.
 */

/** The shape every caller has — more fields are fine, these are needed. */
export interface PathwayLike {
  pathway_type?: 'guided_experience' | 'knowledge_guide' | null
}

export function isKnowledgeGuide(pathway: PathwayLike | null | undefined): boolean {
  return pathway?.pathway_type === 'knowledge_guide'
}

/**
 * "5 sections" / "5 steps", or null when there is nothing to count.
 *
 * Returns null rather than "0 sections": an empty guide should say
 * nothing about its size, the same way an empty pathway already does.
 */
export function unitCountLabel(
  pathway: PathwayLike | null | undefined,
  count: number | null | undefined,
): string | null {
  if (!count || count <= 0) return null
  const unit = isKnowledgeGuide(pathway) ? 'section' : 'step'
  return `${count} ${unit}${count === 1 ? '' : 's'}`
}

/** The singular noun, for sentences that build their own copy. */
export function unitNoun(pathway: PathwayLike | null | undefined): 'section' | 'step' {
  return isKnowledgeGuide(pathway) ? 'section' : 'step'
}

/** The plural noun. */
export function unitNounPlural(
  pathway: PathwayLike | null | undefined,
): 'sections' | 'steps' {
  return isKnowledgeGuide(pathway) ? 'sections' : 'steps'
}

/**
 * The primary call to action.
 *
 * "Open guide" rather than "Continue reading" on purpose: continuing
 * implies a remembered position, and nothing stores one. Inventing
 * reading progress to justify a verb would be the wrong way round.
 */
export function openLabel(pathway: PathwayLike | null | undefined): string {
  return isKnowledgeGuide(pathway) ? 'Open guide' : 'Begin'
}

/** The "see everything inside" link. */
export function viewAllLabel(pathway: PathwayLike | null | undefined): string {
  return isKnowledgeGuide(pathway) ? 'View sections' : 'View all steps'
}

/**
 * Whether completion and progress mean anything for this Pathway.
 *
 * The one predicate that hides the progress bar, the "0 of 5 complete"
 * line and the percentage. Kept separate from the wording helpers
 * because it is a different decision — a surface can get the noun right
 * and still wrongly draw a progress bar.
 */
export function showsProgress(pathway: PathwayLike | null | undefined): boolean {
  return !isKnowledgeGuide(pathway)
}
