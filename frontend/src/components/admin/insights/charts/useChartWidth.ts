'use client'

import { useEffect, useLayoutEffect, useRef, useState } from 'react'

/**
 * `useLayoutEffect` in the browser, `useEffect` on the server.
 *
 * The measurement has to happen before the browser paints, or the
 * first frame is drawn against the fallback width and the SVG
 * letterboxes inside its container — a visible flash of a small chart
 * floating in a wide card. React warns if `useLayoutEffect` is called
 * during server rendering, so the hook is chosen rather than the
 * behaviour being compromised.
 */
const useIsomorphicLayoutEffect =
  typeof window !== 'undefined' ? useLayoutEffect : useEffect

/**
 * The rendered width of a chart's container, in pixels.
 *
 * An SVG with a `viewBox` and no measured width scales its text along
 * with its geometry, so a chart on a narrow screen gets unreadably
 * small labels rather than fewer of them. Measuring instead lets the
 * chart keep its type at one size and drop ticks as it narrows, which
 * is the behaviour a reader wants.
 *
 * Starts at a sensible desktop width rather than zero so the first
 * paint is a chart rather than a collapsed box, and so server rendering
 * produces something reasonable.
 */
export function useChartWidth(initial = 720) {
  const ref = useRef<HTMLDivElement | null>(null)
  const [width, setWidth] = useState(initial)
  // Whether the width is a real measurement rather than the fallback.
  // A chart drawn against the fallback and then scaled to its container
  // is letterboxed — the plot floats, undersized, in the middle of the
  // card — so the caller waits rather than drawing something wrong.
  const [measured, setMeasured] = useState(false)

  useIsomorphicLayoutEffect(() => {
    const node = ref.current
    if (!node) return
    // Measure once, synchronously, before the first paint. The observer
    // below handles every later change, but it cannot help the first
    // frame — and without this the chart is drawn against the fallback
    // width and scaled, which letterboxes it inside a wider card.
    const initialWidth = node.getBoundingClientRect().width
    if (initialWidth > 0) {
      setWidth(initialWidth)
      setMeasured(true)
    }
    // ResizeObserver rather than a window resize listener: a sidebar
    // opening or a tab changing can resize the container without the
    // window changing at all. Absent it, the measurement above still
    // stands — the chart is simply not re-measured on resize.
    if (typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver((entries) => {
      const next = entries[0]?.contentRect.width
      if (next && Math.abs(next - width) > 1) {
        setWidth(next)
        setMeasured(true)
      }
    })
    observer.observe(node)
    return () => observer.disconnect()
    // `width` is deliberately absent from the dependency list:
    // including it would tear down and rebuild the observer on every
    // measurement it reports.
  }, [])

  return { ref, width, measured }
}
