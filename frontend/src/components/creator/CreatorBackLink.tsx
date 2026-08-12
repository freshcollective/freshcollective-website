import Link from 'next/link'

/**
 * Small, reusable "← Back to X" affordance for Creator Studio
 * editor / detail surfaces.
 *
 * Sits at the top-left of the editor, above the page header art.
 * Uses a neutral colour rather than the teal accent so it reads as
 * "way back" rather than "primary action". Intentionally lightweight
 * so pages that already carry the pattern inline don't need to
 * migrate; this exists so future editor pages have a single place to
 * pick up the same wording, spacing, and hover behaviour.
 *
 * Usage:
 *   <CreatorBackLink href="/creator-studio/gatherings" label="Back to Gatherings" />
 */
export default function CreatorBackLink({
  href, label,
}: {
  href: string
  label: string
}) {
  return (
    <div className="mb-4">
      <Link
        href={href}
        className="inline-flex items-center gap-1 text-[13px] font-medium text-slate-600 transition-colors hover:text-teal-700"
      >
        <span aria-hidden="true">←</span> {label}
      </Link>
    </div>
  )
}
