export interface CoverStyle {
  background: string
  backgroundSize?: string
  titleColor: string
  labelColor: string
  isDark: boolean
}

const PATHWAY_VARIANTS: CoverStyle[] = [
  // 0: Deep Ocean
  {
    background:
      'radial-gradient(ellipse at 85% 30%, rgba(66,199,198,0.32) 0%, transparent 55%), ' +
      'radial-gradient(circle at 15% 80%, rgba(15,94,92,0.45) 0%, transparent 45%), ' +
      'linear-gradient(135deg, #071824 0%, #073B3A 60%, #0C4A48 100%)',
    titleColor: '#FFFFFF',
    labelColor: 'rgba(255,255,255,0.65)',
    isDark: true,
  },
  // 1: Teal Luminance
  {
    background:
      'radial-gradient(ellipse at 72% 18%, rgba(255,255,255,0.22) 0%, transparent 45%), ' +
      'radial-gradient(circle at 18% 78%, rgba(66,199,198,0.28) 0%, transparent 40%), ' +
      'linear-gradient(135deg, #0F5E5C 0%, #38A09E 52%, #55B8B6 100%)',
    titleColor: '#FFFFFF',
    labelColor: 'rgba(255,255,255,0.75)',
    isDark: true,
  },
  // 2: Soft Aqua Editorial (with dot texture)
  {
    background:
      'radial-gradient(circle at 78% 22%, rgba(56,160,158,0.18) 0%, transparent 50%), ' +
      'radial-gradient(rgba(56,160,158,0.09) 1px, transparent 1px), ' +
      'linear-gradient(135deg, #EAF8F7 0%, #F5FCFB 55%, #FAFAF8 100%)',
    backgroundSize: 'auto, 18px 18px, auto',
    titleColor: '#152236',
    labelColor: '#2E8584',
    isDark: false,
  },
  // 3: Mist (very light, with dot texture)
  {
    background:
      'radial-gradient(ellipse at 50% 110%, rgba(56,160,158,0.22) 0%, transparent 52%), ' +
      'radial-gradient(rgba(56,160,158,0.07) 1px, transparent 1px), ' +
      'linear-gradient(160deg, #FFFFFF 0%, #EAF8F7 52%, #DFF5F3 100%)',
    backgroundSize: 'auto, 20px 20px, auto',
    titleColor: '#152236',
    labelColor: '#2E8584',
    isDark: false,
  },
  // 4: Forest Deep
  {
    background:
      'radial-gradient(circle at 88% 12%, rgba(66,199,198,0.30) 0%, transparent 42%), ' +
      'radial-gradient(ellipse at 12% 88%, rgba(6,47,53,0.55) 0%, transparent 42%), ' +
      'linear-gradient(160deg, #062F35 0%, #073B3A 45%, #0A5A56 100%)',
    titleColor: '#FFFFFF',
    labelColor: 'rgba(255,255,255,0.65)',
    isDark: true,
  },
  // 5: Teal Gradient Mid
  {
    background:
      'radial-gradient(circle at 82% 18%, rgba(255,255,255,0.22) 0%, transparent 40%), ' +
      'radial-gradient(circle at 18% 82%, rgba(7,56,58,0.38) 0%, transparent 38%), ' +
      'linear-gradient(145deg, #1A5150 0%, #38A09E 50%, #7FCFCD 100%)',
    titleColor: '#FFFFFF',
    labelColor: 'rgba(255,255,255,0.72)',
    isDark: true,
  },
]

const COLLECTIVE_VARIANTS: CoverStyle[] = [
  // 0: Deep Navy
  {
    background:
      'radial-gradient(ellipse at 80% 20%, rgba(66,199,198,0.28) 0%, transparent 50%), ' +
      'radial-gradient(rgba(56,160,158,0.06) 1px, transparent 1px), ' +
      'linear-gradient(145deg, #071824 0%, #073B3A 55%, #0F5E5C 100%)',
    backgroundSize: 'auto, 24px 24px, auto',
    titleColor: '#FFFFFF',
    labelColor: 'rgba(255,255,255,0.65)',
    isDark: true,
  },
  // 1: Ocean Teal
  {
    background:
      'radial-gradient(ellipse at 75% 25%, rgba(255,255,255,0.18) 0%, transparent 45%), ' +
      'radial-gradient(rgba(56,160,158,0.07) 1px, transparent 1px), ' +
      'linear-gradient(135deg, #0F5E5C 0%, #38A09E 48%, #55B8B6 100%)',
    backgroundSize: 'auto, 22px 22px, auto',
    titleColor: '#FFFFFF',
    labelColor: 'rgba(255,255,255,0.72)',
    isDark: true,
  },
  // 2: Soft Aqua Place
  {
    background:
      'radial-gradient(ellipse at 85% 15%, rgba(56,160,158,0.20) 0%, transparent 55%), ' +
      'radial-gradient(rgba(56,160,158,0.09) 1px, transparent 1px), ' +
      'linear-gradient(135deg, #EAF8F7 0%, #F0FBFA 55%, #FAFAF8 100%)',
    backgroundSize: 'auto, 20px 20px, auto',
    titleColor: '#152236',
    labelColor: '#2E8584',
    isDark: false,
  },
  // 3: Forest
  {
    background:
      'radial-gradient(circle at 85% 15%, rgba(66,199,198,0.28) 0%, transparent 42%), ' +
      'radial-gradient(rgba(56,160,158,0.06) 1px, transparent 1px), ' +
      'linear-gradient(155deg, #062F35 0%, #073B3A 50%, #0A5A56 100%)',
    backgroundSize: 'auto, 22px 22px, auto',
    titleColor: '#FFFFFF',
    labelColor: 'rgba(255,255,255,0.65)',
    isDark: true,
  },
]

function hashSlug(slug: string): number {
  let h = 0
  for (let i = 0; i < slug.length; i++) h = ((h << 5) - h + slug.charCodeAt(i)) | 0
  return Math.abs(h)
}

export function getPathwayCoverStyle(slug: string): CoverStyle {
  return PATHWAY_VARIANTS[hashSlug(slug) % PATHWAY_VARIANTS.length]
}

export function getCollectiveCoverStyle(slug: string): CoverStyle {
  return COLLECTIVE_VARIANTS[hashSlug(slug) % COLLECTIVE_VARIANTS.length]
}
