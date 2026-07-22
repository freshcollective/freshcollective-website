/**
 * Fresh Collective — small internal utilities.
 *
 * Intentionally dependency-free. If a project-wide `cn` / `clsx` /
 * `tailwind-merge` becomes available later, the primitives can be
 * migrated in one place.
 */

type ClassInput = string | number | false | null | undefined

/**
 * Concatenate class names. Falsy values are dropped.
 *
 * NOTE: This does not deduplicate Tailwind classes. the primitives put the
 * consumer's `className` last so it overrides base classes by CSS order —
 * which works for most cases without pulling in tailwind-merge.
 */
export function cn(...classes: ClassInput[]): string {
  return classes.filter(Boolean).join(' ')
}

/**
 * Generate a stable id for pairing labels with inputs when no id is supplied.
 * Uses React.useId at the call site (see FormField).
 */
export function fieldId(base: string, suffix: string): string {
  return `${base}-${suffix}`
}
