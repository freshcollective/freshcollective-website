export const COLLECTIVE_THEMES = [
  'Inner Work',
  'Wellbeing',
  'Creativity',
  'Leadership',
  'Reflection',
  'Movement',
  'Business',
  'Spirituality',
  'Relationships',
  'Parenting',
] as const

export type CollectiveTheme = (typeof COLLECTIVE_THEMES)[number]
