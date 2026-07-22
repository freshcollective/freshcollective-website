'use client'

/**
 * Fresh Collective — Global error boundary.
 *
 * Rendered ONLY when the root layout itself fails to render. Must include
 * its own <html> and <body> because the root layout is not available.
 *
 * Uses inline styles (no design-system primitives) because a catastrophic error
 * may have prevented the stylesheet from loading. The tone still follows
 * The design language remains: quiet type, one primary action, no illustration.
 *
 * @see docs/fresh-design-language.md §18.3
 */

interface Props {
  error: Error & { digest?: string }
  reset: () => void
}

export default function GlobalError({ error, reset }: Props) {
  return (
    <html lang="en">
      <body
        style={{
          margin: 0,
          minHeight: '100vh',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          background: '#F7FBFA',
          color: '#000000',
          fontFamily:
            '-apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
          padding: '2rem',
        }}
      >
        <div style={{ maxWidth: 520, textAlign: 'center' }}>
          <h1
            style={{
              fontFamily: 'Georgia, "Times New Roman", Times, serif',
              fontSize: '23px',
              fontWeight: 600,
              letterSpacing: '-0.02em',
              lineHeight: 1.2,
              color: '#0C1826',
              margin: 0,
            }}
          >
            Something went wrong.
          </h1>
          <p style={{ fontSize: 14, lineHeight: 1.6, marginTop: 12 }}>
            An unexpected error prevented Fresh Collective from loading. Please
            try again.
          </p>
          {error?.digest && (
            <p style={{ fontSize: 12, marginTop: 16, color: '#000000', opacity: 0.6 }}>
              Reference: <span style={{ fontFamily: 'monospace' }}>{error.digest}</span>
            </p>
          )}
          <button
            type="button"
            onClick={reset}
            style={{
              marginTop: 24,
              display: 'inline-flex',
              alignItems: 'center',
              gap: 8,
              height: 40,
              padding: '0 16px',
              border: 0,
              borderRadius: 8,
              color: '#FFFFFF',
              fontSize: 13,
              fontWeight: 600,
              cursor: 'pointer',
              background:
                'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)',
            }}
          >
            Try again
          </button>
        </div>
      </body>
    </html>
  )
}
