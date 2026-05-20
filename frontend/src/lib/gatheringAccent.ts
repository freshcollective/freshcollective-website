export type GatheringAccent = {
  border: string      // card left border colour
  pillBg: string      // format pill background
  pillColor: string   // format pill text
  monthColor: string  // date block month label text
  chipBg: string      // calendar chip background
  chipColor: string   // calendar chip text
}

/**
 * Returns accent tokens for a gathering based on its location_type.
 * Falls back to neutral slate for any unrecognised value.
 */
export function getGatheringAccent(locationType: string): GatheringAccent {
  switch (locationType) {
    case 'zoom':
      return {
        border:     '#38A09E',
        pillBg:     'rgba(56,160,158,0.10)',
        pillColor:  '#0f766e',
        monthColor: '#0f766e',
        chipBg:     'rgba(56,160,158,0.12)',
        chipColor:  '#0f766e',
      }
    case 'in_person':
      return {
        border:     '#BF9830',
        pillBg:     'rgba(191,152,48,0.10)',
        pillColor:  '#92700a',
        monthColor: '#92700a',
        chipBg:     'rgba(191,152,48,0.12)',
        chipColor:  '#92700a',
      }
    case 'async_recorded':
      return {
        border:     '#334155',
        pillBg:     'rgba(51,65,85,0.08)',
        pillColor:  '#334155',
        monthColor: '#475569',
        chipBg:     'rgba(51,65,85,0.10)',
        chipColor:  '#334155',
      }
    default:
      return {
        border:     '#94a3b8',
        pillBg:     'rgba(148,163,184,0.10)',
        pillColor:  '#64748b',
        monthColor: '#64748b',
        chipBg:     'rgba(148,163,184,0.10)',
        chipColor:  '#64748b',
      }
  }
}
