import React from 'react'
import {
  type ColumnsPayload,
  activeCells,
  cellCountForVariant,
  cellImageAlt,
  cellKind,
  gridTemplateForVariant,
} from '@/lib/columnsBlock'
import RichTextRenderer from '@/components/RichTextRenderer'
import { resolveMediaUrl } from '@/lib/api'

/**
 * One columns block, rendered.
 *
 * Shared by the member Pathway step renderer (``BlockList``) and the
 * public About page renderer (``AboutBlockRenderer``) because columns
 * blocks now have two cell types and a per-column-count breakpoint, and
 * keeping two copies of that in step with each other was the thing most
 * likely to go wrong. Both callers previously inlined the same six
 * lines; when images were added, one of them would eventually have been
 * updated and the other not.
 *
 * Deliberately not a client component: it holds no state and runs
 * inside a server component on the step page. The two callers differ
 * only in the margin they want around the grid and in the typography
 * class on each cell, so those are props.
 *
 * ``data-cols`` carries the column count into CSS, which is how the
 * three- and four-column layouts get later stacking breakpoints than
 * the two-column ones (see ``.fc-columns-grid`` in globals.css). Doing
 * it with an attribute rather than a class keeps the count available to
 * a plain CSS selector without the grid needing to know the rules.
 */

export default function ColumnsGrid({
  payload,
  className,
  cellClassName,
}: {
  payload: ColumnsPayload
  /** Outer margins. The step renderer carries a vertical rhythm here;
   *  the About renderer spaces its blocks from the outside. */
  className?: string
  /** Typography for a text cell. The About page wraps cells in prose. */
  cellClassName?: string
}) {
  const variant = payload.layout.variant
  const cells = activeCells(payload)

  return (
    <div
      className={['fc-columns-grid grid items-start gap-6', className].filter(Boolean).join(' ')}
      data-cols={cellCountForVariant(variant)}
      style={{ ['--fc-cols' as string]: gridTemplateForVariant(variant) }}
    >
      {cells.map((cell, i) => (
        <div key={i} className={['min-w-0', cellClassName].filter(Boolean).join(' ')}>
          {cellKind(cell) === 'image' ? <CellImage cell={cell} /> : <CellText cell={cell} />}
        </div>
      ))}
    </div>
  )
}

function CellText({ cell }: { cell: ColumnsPayload['cells'][number] }) {
  // Unchanged from the original inline render: an empty column stays
  // empty rather than collapsing the grid.
  if (!cell.content?.trim()) return null
  return <RichTextRenderer content={cell.content} />
}

function CellImage({ cell }: { cell: ColumnsPayload['cells'][number] }) {
  const image = cell.image
  // A column switched to Image but with nothing chosen yet. The
  // creator's editor still shows the image controls — see ``cellKind``
  // — but a member sees an empty column, not a broken picture.
  if (!image?.url) return null
  const src = resolveMediaUrl(image.url) ?? image.url

  return (
    // ``not-prose`` because the About page wraps each cell in Tailwind
    // typography, which would otherwise impose its own figure and image
    // margins and put this out of step with the step renderer.
    <figure className="not-prose">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={src}
        alt={cellImageAlt(image)}
        // ``h-auto`` with no object-fit: the image fills the column's
        // width and keeps its own proportions. Nothing here can stretch
        // it to match a taller text column beside it, and ``items-start``
        // on the grid stops the cell itself being stretched.
        className="h-auto w-full rounded-xl shadow-[0_1px_3px_rgba(15,30,55,0.08),0_2px_8px_rgba(15,30,55,0.04)]"
      />
      {image.caption?.trim() && (
        <figcaption className="mt-2 text-center text-[12px] text-black">
          {image.caption}
        </figcaption>
      )}
    </figure>
  )
}
