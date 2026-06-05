/**
 * Convert our About-page markdown subset to HTML for loading into TipTap.
 * Handles: ## h2, ### h3, **bold**, [text](url), * bullets, paragraphs.
 *
 * If the input already looks like HTML (starts with '<'), it is returned unchanged.
 */

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

/** Convert inline markdown (bold, links) to HTML, escaping plain text portions. */
function inlineToHtml(text: string): string {
  const re = /\*\*(.+?)\*\*|\[([^\]]+)\]\((https?:\/\/[^)]+)\)/g
  let result = ''
  let last = 0
  let m: RegExpExecArray | null
  while ((m = re.exec(text)) !== null) {
    result += escapeHtml(text.slice(last, m.index))
    if (m[1] !== undefined) {
      result += `<strong>${escapeHtml(m[1])}</strong>`
    } else {
      result += `<a target="_blank" rel="noopener noreferrer nofollow" href="${escapeHtml(m[3])}">${escapeHtml(m[2])}</a>`
    }
    last = m.index + m[0].length
  }
  result += escapeHtml(text.slice(last))
  return result
}

export function markdownToHtml(md: string): string {
  const trimmed = md.trim()
  // Already HTML — return as-is
  if (/^<[a-z]/.test(trimmed)) return md

  const blocks = trimmed.split(/\n\n+/)
  let html = ''

  for (const block of blocks) {
    const t = block.trim()
    if (!t) continue
    const lines = t.split('\n')
    const first = lines[0]

    if (first.startsWith('## ')) {
      html += `<h2>${inlineToHtml(first.slice(3))}</h2>`
    } else if (first.startsWith('### ')) {
      html += `<h3>${inlineToHtml(first.slice(4))}</h3>`
    } else if (lines.every((l) => l.startsWith('* ') || l.startsWith('- '))) {
      const items = lines
        .map((l) => `<li><p>${inlineToHtml(l.slice(2))}</p></li>`)
        .join('')
      html += `<ul>${items}</ul>`
    } else {
      // Each non-empty line within the block → its own <p>
      for (const line of lines) {
        const lt = line.trim()
        if (lt) html += `<p>${inlineToHtml(lt)}</p>`
      }
    }
  }

  return html || '<p></p>'
}
