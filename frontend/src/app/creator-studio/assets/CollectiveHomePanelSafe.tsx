'use client'

import React from 'react'
import CollectiveHomePanel from './CollectiveHomePanel'

/**
 * Wraps CollectiveHomePanel in a small ErrorBoundary so a runtime failure
 * inside the panel cannot blank the rest of the Assets page. The Atlas
 * v1.2 identity data is optional across the board and every legacy
 * combination is expected to render safely, but the boundary is here as
 * defense in depth — one broken panel should never take the page (or
 * the Asset Library below it) with it.
 */

interface Props {
  slug: string
  location: {
    name: string
    description: string | null
    hero_artwork_url: string | null
  } | null
  atmosphereNames: string[]
  colourPalette: {
    name: string
    palette: { primary: string; secondary: string; accent: string; background: string }
  } | null
}

interface BoundaryState {
  error: Error | null
}

class Boundary extends React.Component<React.PropsWithChildren<{ slug: string }>, BoundaryState> {
  constructor(props: React.PropsWithChildren<{ slug: string }>) {
    super(props)
    this.state = { error: null }
  }
  static getDerivedStateFromError(error: Error): BoundaryState {
    return { error }
  }
  componentDidCatch(error: Error, info: React.ErrorInfo) {
    // Development-visible error containing the collective slug and the
    // real exception so the diagnostic path is short.
    console.error(
      `[CollectiveHomePanel] rendering failed for slug=${this.props.slug}:`,
      error,
      info,
    )
  }
  render(): React.ReactNode {
    if (this.state.error) {
      return (
        <section
          className="overflow-hidden rounded-2xl bg-white p-6"
          style={{ border: '1px solid rgba(166, 69, 38, 0.24)' }}
        >
          <p className="text-[14.5px] font-semibold" style={{ color: '#A64526' }}>
            Collective Home couldn&apos;t be shown.
          </p>
          <p className="mt-2 text-[13px] leading-relaxed text-black">
            Your Asset Library below is still available. Please refresh in a moment, or check the browser console for the actual exception.
          </p>
        </section>
      )
    }
    return this.props.children
  }
}

export default function CollectiveHomePanelSafe(props: Props) {
  return (
    <Boundary slug={props.slug}>
      <CollectiveHomePanel {...props} />
    </Boundary>
  )
}
