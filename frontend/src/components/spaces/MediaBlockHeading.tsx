import React from 'react'

/**
 * The optional title above a video, audio or file-download block.
 *
 * One component rather than the same three lines in three places. The
 * member Pathway renderer (``BlockList``), the member About renderer
 * (``AboutBlockRenderer``) and the Creator Studio preview
 * (``BlockEditorShared``) all render this block vocabulary
 * independently, and the preview's whole job is to show a creator what
 * their members will see. Triplicating the markup is how that promise
 * quietly stops being true.
 *
 * The treatment is the one the Exercise block already uses for its
 * optional title — serif, 20px, navy — so a heading on a recording and
 * a heading on an exercise read as the same kind of thing. Deliberately
 * not the small uppercase label used for ``embed``: this is a title the
 * creator wrote, not a category tag, and it should read like one.
 *
 * Renders nothing at all for a block without a heading, which is every
 * block authored before the field existed.
 */
export default function MediaBlockHeading({
  heading,
}: {
  heading?: string | null
}) {
  if (!heading?.trim()) return null
  return (
    <p className="mb-2 font-serif text-[20px] leading-tight text-navy-900">
      {heading}
    </p>
  )
}
