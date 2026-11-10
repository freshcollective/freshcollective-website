/**
 * "On this page" — anchor links to the body's H2s.
 *
 * Built from ``extractHeadings``, the same function the renderer's
 * ids come from, so a link here always lands on a heading that
 * exists. A stored outline would be a second thing to keep in step
 * with the article, and it would eventually be wrong.
 *
 * Renders nothing for a Guide with fewer than two headings: a
 * contents list with one entry is furniture, not navigation.
 */
export default function OnThisPage({
  headings,
}: {
  headings: Array<{ id: string; text: string }>
}) {
  if (headings.length < 2) return null

  return (
    <nav
      aria-labelledby="on-this-page-heading"
      className="rounded-2xl bg-white px-6 py-6"
      style={{
        boxShadow:
          '0 1px 2px rgba(15,30,55,0.04), 0 0 0 1px rgba(15,30,55,0.08)',
      }}
    >
      <h2
        id="on-this-page-heading"
        className="mb-3 text-[14px] font-semibold text-navy-950"
      >
        On this page
      </h2>
      <ul className="space-y-2.5">
        {headings.map((h) => (
          <li key={h.id}>
            <a
              href={`#${h.id}`}
              className="block rounded-sm text-[14px] leading-[1.45] text-teal-700 transition-colors hover:text-teal-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 focus-visible:ring-offset-2"
            >
              {h.text}
            </a>
          </li>
        ))}
      </ul>
    </nav>
  )
}
