'use client'

import { useMemo } from 'react'
import { renderMarkdown, WG } from '@/lib/worldGuide'

/**
 * WorldGuideProse — the single renderer for World Guide Markdown.
 *
 * The editor preview pane and the public document page both mount
 * this component with the same Markdown string. That way there is
 * exactly one place styling can drift, and there is no way for
 * "preview" to disagree with "published".
 *
 * Styling is emitted via a scoped `.wg-prose` class using an inline
 * `<style>` tag. Small enough to duplicate cheaply; keeps this
 * component drop-in without a global CSS import.
 */

interface Props {
  content: string | null | undefined
  /** Compact tuning for the editor preview (slightly tighter margins). */
  size?: 'default' | 'compact'
}

export default function WorldGuideProse({ content, size = 'default' }: Props) {
  const html = useMemo(
    () => renderMarkdown(content ?? ''),
    [content],
  )
  return (
    <>
      <div
        className={`wg-prose wg-prose-${size}`}
        dangerouslySetInnerHTML={{ __html: html }}
      />
      <style>{`
        .wg-prose {
          color: ${WG.ink};
          font-size: 15.5px;
          line-height: 1.72;
        }
        .wg-prose-compact { font-size: 14.5px; line-height: 1.62; }

        .wg-prose h1, .wg-prose h2, .wg-prose h3 {
          color: ${WG.inkStrong};
          font-family: Georgia, 'Times New Roman', serif;
          font-weight: 600;
          line-height: 1.25;
        }
        .wg-prose h1 { font-size: 28px; margin: 30px 0 12px; }
        .wg-prose h2 { font-size: 22px; margin: 26px 0 10px; }
        .wg-prose h3 { font-size: 18px; margin: 22px 0 8px; }
        .wg-prose-compact h1 { font-size: 22px; margin: 20px 0 10px; }
        .wg-prose-compact h2 { font-size: 18px; margin: 18px 0 8px; }
        .wg-prose-compact h3 { font-size: 15.5px; margin: 14px 0 6px; }

        .wg-prose p { margin: 12px 0; }
        .wg-prose-compact p { margin: 8px 0; }

        .wg-prose ul, .wg-prose ol {
          margin: 12px 0 12px 22px;
          padding: 0;
        }
        .wg-prose li { margin: 4px 0; }
        .wg-prose ol { list-style: decimal outside; }
        .wg-prose ul { list-style: disc outside; }
        .wg-prose ol ol { list-style: lower-alpha outside; margin-top: 4px; }
        .wg-prose ul ul { list-style: circle outside; margin-top: 4px; }

        .wg-prose a {
          color: ${WG.teal};
          text-decoration: underline;
          text-underline-offset: 2px;
        }
        .wg-prose a:hover { opacity: 0.85; }

        .wg-prose blockquote {
          border-left: 3px solid ${WG.teal};
          padding: 4px 16px;
          margin: 16px 0;
          color: ${WG.inkMuted};
          font-style: italic;
        }

        .wg-prose table {
          border-collapse: collapse;
          width: 100%;
          margin: 16px 0;
          font-size: 0.95em;
        }
        .wg-prose th, .wg-prose td {
          border: 1px solid rgba(15,23,42,0.10);
          padding: 8px 12px;
          text-align: left;
          vertical-align: top;
        }
        .wg-prose th {
          background: ${WG.tealSoft};
          color: ${WG.inkStrong};
          font-weight: 600;
        }
        .wg-prose tr:nth-child(even) td { background: rgba(15,23,42,0.02); }

        .wg-prose code {
          background: rgba(15,23,42,0.06);
          padding: 1.5px 6px;
          border-radius: 4px;
          font-size: 0.9em;
          font-family: 'SFMono-Regular', ui-monospace, Menlo, Monaco, Consolas, monospace;
        }
        .wg-prose pre {
          background: ${WG.surfaceBg};
          border: 1px solid rgba(15,23,42,0.08);
          border-radius: 8px;
          padding: 12px 14px;
          margin: 14px 0;
          overflow-x: auto;
          font-size: 0.9em;
        }
        .wg-prose pre code {
          background: transparent;
          padding: 0;
          border-radius: 0;
        }

        .wg-prose hr {
          border: none;
          border-top: 1px solid rgba(15,23,42,0.10);
          margin: 26px 0;
        }

        /* Callouts — flat, part of the document, never a floating card. */
        .wg-callout {
          border: none;
          border-left: 3px solid ${WG.teal};
          background: ${WG.tealSoft};
          padding: 12px 18px;
          margin: 16px 0;
          border-radius: 0;
          box-shadow: none;
        }
        .wg-callout-title {
          font-weight: 600;
          color: ${WG.inkStrong};
          margin-bottom: 4px;
        }
        .wg-callout-body { color: ${WG.ink}; }

        .wg-callout-warning {
          border-left-color: ${WG.gold};
          background: ${WG.goldSoft};
        }
        .wg-callout-warning .wg-callout-title { color: ${WG.inkStrong}; }

        .wg-prose > :first-child { margin-top: 0; }
        .wg-prose > :last-child { margin-bottom: 0; }
      `}</style>
    </>
  )
}
