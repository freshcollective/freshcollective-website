#!/usr/bin/env node
/**
 * Measure columns-block layout in a real browser, against the real
 * built stylesheet, and fail if it drifts.
 *
 * Round 2 item 1 moved the stacking breakpoints apart by column count:
 * two columns go side by side from 640px, three from 768px, four from
 * 900px. `columnsResponsive.test.ts` asserts those rules are in
 * globals.css; this asserts the browser actually lays them out that
 * way, which is the part a unit test cannot see.
 *
 * It is deliberately run against `.next/static/chunks/*.css` rather
 * than a hand-written stylesheet. An earlier attempt at this kind of
 * harness in this repo used its own CSS and silently proved nothing,
 * because the arbitrary variants it was testing had never been emitted
 * into the real build at all.
 *
 * Usage:
 *     npm run build                       # the CSS has to exist first
 *     node scripts/measure-columns-responsive.mjs [--verbose]
 *
 * Exits non-zero on the first failed expectation, so it can be wired
 * into a check script. Requires a Chromium binary; set CHROME to
 * override the Playwright-cached default.
 */

import { execFileSync } from 'node:child_process'
import { mkdtempSync, readdirSync, readFileSync, writeFileSync, copyFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const VERBOSE = process.argv.includes('--verbose')

const CHROME = process.env.CHROME
  ?? '/home/lindsey/.cache/ms-playwright/chromium-1228/chrome-linux/chrome'

const CHUNKS = 'frontend/.next/static/chunks'.replace(/^frontend\//, '')
let cssFile
try {
  const dir = join(process.cwd(), '.next/static/chunks')
  cssFile = join(dir, readdirSync(dir).find((f) => f.endsWith('.css')))
} catch {
  console.error(`No built CSS under ${CHUNKS}. Run "npm run build" first.`)
  process.exit(2)
}

// The breakpoints are only real if they are in the stylesheet we are
// about to measure.
const css = readFileSync(cssFile, 'utf8')
for (const needle of ['fc-columns-grid[data-cols="3"]', 'fc-columns-grid[data-cols="4"]']) {
  if (!css.includes(needle)) {
    console.error(`Built CSS is missing ${needle} — measuring it would prove nothing.`)
    process.exit(2)
  }
}

const WIDTHS = [375, 640, 767, 768, 899, 900, 1024, 1280, 1440]

/** Expected track count per column count, by viewport width. */
function expectedTracks(cols, width) {
  if (cols === 2) return width >= 640 ? 2 : 1
  if (cols === 3) return width >= 768 ? 3 : 1
  if (cols === 4) return width >= 900 ? 4 : 1
  return 1
}

// An 800x400 source, so a faithful render has an aspect ratio of
// exactly 2.
const IMG =
  'data:image/svg+xml;charset=utf-8,' +
  '%3Csvg%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%20width%3D%22800%22' +
  '%20height%3D%22400%22%3E%3Crect%20width%3D%22800%22%20height%3D%22400%22%20' +
  'fill%3D%22%2338A09E%22%2F%3E%3C%2Fsvg%3E'

const textCell = (i) =>
  `<div class="min-w-0"><div><p class="my-3 first:mt-0 last:mb-0">Column ${i} text that ` +
  `should stay readable at every width.</p></div></div>`

const imageCell = (i) =>
  `<div class="min-w-0"><figure><img class="h-auto w-full rounded-xl ` +
  `shadow-[0_1px_3px_rgba(15,30,55,0.08),0_2px_8px_rgba(15,30,55,0.04)]" src="${IMG}" alt="">` +
  `<figcaption class="mt-2 text-center text-[12px] text-black">Caption ${i}</figcaption></figure></div>`

// Exactly the markup ColumnsGrid emits for the step renderer.
const grid = (name, tracks, cells) =>
  `<section data-case="${name}"><div class="fc-columns-grid grid items-start gap-6 my-1.5" ` +
  `data-cols="${cells.length}" style="--fc-cols: ${tracks}">${cells.join('')}</div></section>`

const CASES = [
  grid('2col text+image', '1fr 1fr', [textCell(1), imageCell(2)]),
  grid('2col image+text', '1fr 1fr', [imageCell(1), textCell(2)]),
  grid('2col image+image', '1fr 1fr', [imageCell(1), imageCell(2)]),
  grid('2col text+text', '1fr 1fr', [textCell(1), textCell(2)]),
  grid('2col 66-33 img', '2fr 1fr', [imageCell(1), textCell(2)]),
  grid('3col mixed', '1fr 1fr 1fr', [textCell(1), imageCell(2), textCell(3)]),
  grid('4col mixed', '1fr 1fr 1fr 1fr',
    [imageCell(1), textCell(2), imageCell(3), textCell(4)]),
]

const work = mkdtempSync(join(tmpdir(), 'fc-columns-'))
copyFileSync(cssFile, join(work, 'app.css'))
writeFileSync(join(work, 'child.html'),
  `<meta charset="utf-8"><link rel="stylesheet" href="app.css">` +
  `<style>html,body{margin:0}.page{max-width:72rem;margin:0 auto;padding:0 1rem}</style>` +
  `<body><div class="page">${CASES.join('')}</div></body>`)

// Iframes, not window resizing: media queries have to evaluate against
// a real viewport width.
writeFileSync(join(work, 'parent.html'), `<meta charset="utf-8"><body><pre id="out">pending</pre>
<div id="frames"></div><script>
const WIDTHS = ${JSON.stringify(WIDTHS)};
const results = [];
const mk = (w) => new Promise((res) => {
  const f = document.createElement('iframe');
  f.style.cssText = 'width:' + w + 'px;height:4000px;border:0;display:block';
  f.src = 'child.html';
  f.onload = () => res(f);
  document.getElementById('frames').appendChild(f);
});
(async () => {
  for (const w of WIDTHS) {
    const f = await mk(w), d = f.contentDocument, win = f.contentWindow;
    const de = d.documentElement;
    for (const sec of d.querySelectorAll('section[data-case]')) {
      const g = sec.firstElementChild;
      const cells = [...g.children];
      const boxes = cells.map((c) => c.getBoundingClientRect());
      results.push({
        width: w,
        docOverflow: de.scrollWidth - de.clientWidth,
        name: sec.dataset.case,
        cols: cells.length,
        tracks: win.getComputedStyle(g).gridTemplateColumns.split(' ').filter(Boolean).length,
        cellWidths: boxes.map((b) => Math.round(b.width)),
        order: boxes.map((b, i) => [i, Math.round(b.top), Math.round(b.left)]),
        images: [...g.querySelectorAll('img')].map((im) => {
          const r = im.getBoundingClientRect();
          const cell = im.closest('.min-w-0').getBoundingClientRect();
          return {
            w: Math.round(r.width), h: Math.round(r.height),
            aspect: +(r.width / r.height).toFixed(3),
            natural: im.naturalWidth + 'x' + im.naturalHeight,
            withinCell: r.width <= cell.width + 0.5,
          };
        }),
      });
    }
  }
  document.getElementById('out').textContent = JSON.stringify(results);
})();
</script>`)

const dom = execFileSync(CHROME, [
  '--headless', '--disable-gpu', '--no-sandbox', '--allow-file-access-from-files',
  '--virtual-time-budget=20000', '--window-size=1600,2000',
  '--dump-dom', `file://${join(work, 'parent.html')}`,
], { encoding: 'utf8', maxBuffer: 64 * 1024 * 1024, stdio: ['ignore', 'pipe', 'ignore'] })

const payload = dom.slice(dom.indexOf('<pre id="out">') + 14, dom.indexOf('</pre>'))
if (payload.trim() === 'pending' || !payload.trim()) {
  console.error('The harness did not report — Chromium may not have settled.')
  process.exit(2)
}
const rows = JSON.parse(payload.replace(/&quot;/g, '"').replace(/&amp;/g, '&'))

const failures = []
const check = (cond, msg) => { if (!cond) failures.push(msg) }

for (const r of rows) {
  const where = `${r.width}px ${r.name}`
  check(r.tracks === expectedTracks(r.cols, r.width),
    `${where}: ${r.cols} columns laid out in ${r.tracks} tracks, expected ` +
    `${expectedTracks(r.cols, r.width)}`)
  check(r.docOverflow <= 0, `${where}: horizontal document overflow ${r.docOverflow}px`)
  // Source order must survive stacking.
  const visual = [...r.order].sort((a, b) => a[1] - b[1] || a[2] - b[2]).map((o) => o[0]).join(',')
  check(visual === r.order.map((o) => o[0]).join(','), `${where}: visual order ${visual} != source order`)
  for (const [i, im] of r.images.entries()) {
    check(im.natural === '800x400', `${where} image ${i}: source not loaded (${im.natural})`)
    check(Math.abs(im.aspect - 2) < 0.02,
      `${where} image ${i}: aspect ratio ${im.aspect}, expected 2 — image is distorted`)
    check(im.withinCell, `${where} image ${i}: ${im.w}px overflows its column`)
    check(im.w > 0 && im.h > 0, `${where} image ${i}: collapsed to ${im.w}x${im.h}`)
  }
  if (VERBOSE) {
    console.log(`${String(r.width).padStart(4)}px ${r.name.padEnd(16)} ` +
      `tracks=${r.tracks} cells=[${r.cellWidths.join(',')}]` +
      (r.images.length ? ` img=${r.images.map((i) => `${i.w}x${i.h} ar=${i.aspect}`).join(' | ')}` : ''))
  }
}

const widths = [...new Set(rows.map((r) => r.width))]
console.log(
  `columns responsive: ${rows.length} measurements across ${widths.length} widths ` +
  `(${widths.join(', ')}px), ${rows.reduce((n, r) => n + r.images.length, 0)} images`,
)
if (failures.length) {
  console.error(`\n${failures.length} failure(s):`)
  for (const f of failures) console.error(`  - ${f}`)
  process.exit(1)
}
console.log('all expectations met: breakpoints, no overflow, aspect ratios, source order')
