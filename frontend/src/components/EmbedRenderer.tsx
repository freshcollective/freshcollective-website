/**
 * Renders an allowlisted embed inside a sandboxed <iframe>.
 *
 * The URL is assumed to have already been validated against the allowlist
 * (backend enforces this on save; this component is a thin renderer).
 * Even so, the iframe carries `sandbox` to limit damage if a bad URL ever
 * reaches here, and `referrerPolicy` to avoid leaking the member's session.
 */

import type { EmbedProvider } from '@/lib/embedAllowlist'
import { getEmbedProvider } from '@/lib/embedAllowlist'

interface Props {
  url: string
  /** Pre-resolved provider; if omitted, we look it up. */
  provider?: EmbedProvider | null
  title?: string
}

export default function EmbedRenderer({ url, provider, title }: Props) {
  const p = provider ?? getEmbedProvider(url)
  if (!p) {
    // Should not happen — backend rejects non-allowlisted hosts — but render
    // a safe fallback link instead of silently inserting an unknown iframe.
    return (
      <a
        href={url}
        target="_blank"
        rel="noopener noreferrer"
        className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-[13px] text-black hover:border-teal-300 hover:text-teal-700"
      >
        ↗ {url}
      </a>
    )
  }

  // sandbox: allow scripts (third-party embed needs them) + same-origin (Vimeo
  // analytics) + popups (Calendly opens confirmation in a new window) + forms
  // (Google Forms / Typeform submission). Critically: NO allow-top-navigation,
  // so a hostile embed cannot redirect the parent page.
  const sandbox =
    'allow-scripts allow-same-origin allow-popups allow-popups-to-escape-sandbox allow-forms allow-presentation'

  // 16:9 for video providers; explicit pixel height for forms/calendars/audio.
  if (p.shape === 'video') {
    return (
      <div className="aspect-video w-full overflow-hidden rounded-xl bg-black">
        <iframe
          src={url}
          title={title ?? p.name}
          className="h-full w-full border-0"
          loading="lazy"
          referrerPolicy="strict-origin-when-cross-origin"
          allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; fullscreen"
          allowFullScreen
          sandbox={sandbox}
        />
      </div>
    )
  }

  const minH = p.minHeight ?? (p.shape === 'short' ? 200 : 600)
  return (
    <div className="w-full overflow-hidden rounded-xl bg-white">
      <iframe
        src={url}
        title={title ?? p.name}
        className="block w-full border-0"
        style={{ minHeight: minH, height: minH }}
        loading="lazy"
        referrerPolicy="strict-origin-when-cross-origin"
        sandbox={sandbox}
      />
    </div>
  )
}
