/**
 * Which way a popover should open, given where its trigger is.
 *
 * Pure, and separate from the component, for two reasons. It is the
 * part worth testing — "does it flip when there is no room" is a
 * decision, not a layout — and this harness has no DOM, so a
 * component test could not exercise it. And it is reusable: any
 * popover anchored to a trigger needs the same four answers.
 *
 * Measured from the **trigger**, never from the panel. Measuring the
 * panel and then moving it feeds its new position into the next
 * measurement, which is how a popover ends up flickering between two
 * placements.
 */

export interface Rect {
  top: number
  right: number
  bottom: number
  left: number
}

export interface Viewport {
  width: number
  height: number
}

export interface PanelSize {
  width: number
  height: number
}

export type HorizontalPlacement = 'left' | 'right'
export type VerticalPlacement = 'top' | 'bottom'

export interface Placement {
  /** `left` anchors the panel's left edge to the trigger's. */
  x: HorizontalPlacement
  /** `top` opens above the trigger, `bottom` below. */
  y: VerticalPlacement
}

/** Breathing room kept between the panel and the viewport edge. */
export const VIEWPORT_PADDING = 8

export function placePopover({
  trigger,
  panel,
  viewport,
  prefer = 'bottom',
  padding = VIEWPORT_PADDING,
}: {
  trigger: Rect
  panel: PanelSize
  viewport: Viewport
  /** The caller's preferred vertical side. */
  prefer?: VerticalPlacement
  padding?: number
}): Placement {
  const roomRight = viewport.width - trigger.left - padding
  const roomLeft = trigger.right - padding
  const roomBelow = viewport.height - trigger.bottom - padding
  const roomAbove = trigger.top - padding

  // Flip to right-aligned only when opening rightward overflows AND
  // the other side genuinely has room. A panel wider than the whole
  // viewport would otherwise just overflow the opposite edge instead,
  // which is not an improvement — the panel's own `max-width` handles
  // that case.
  const x: HorizontalPlacement =
    roomRight < panel.width && roomLeft >= panel.width ? 'right' : 'left'

  // Keep the caller's preference unless that side is out of room and
  // the other has enough. Staying put when neither side fits means a
  // cramped popover opens where the caller expected it to.
  let y: VerticalPlacement = prefer
  if (prefer === 'bottom' && roomBelow < panel.height && roomAbove >= panel.height) {
    y = 'top'
  } else if (prefer === 'top' && roomAbove < panel.height && roomBelow >= panel.height) {
    y = 'bottom'
  }

  return { x, y }
}

/** Tailwind positioning classes for a placement. */
export function placementClasses(placement: Placement): string {
  return [
    placement.y === 'bottom' ? 'top-full mt-1' : 'bottom-full mb-1',
    placement.x === 'left' ? 'left-0' : 'right-0',
  ].join(' ')
}
