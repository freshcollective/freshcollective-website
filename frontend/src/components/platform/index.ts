/**
 * Fresh Collective Design Language — Public exports.
 *
 * Consumers should import from `@/components/platform` (or the relative
 * equivalent) rather than reaching into individual files, so future
 * refactors of the internal structure remain non-breaking.
 */

// Token layer
export * as tokens from './tokens'
export {
  colors,
  pathwayColor,
  typeColor,
  motion,
  zIndex,
  breakpoint,
  mediaQuery,
  spacing,
  radius,
  type PathwayKey,
  type TypeKey,
} from './tokens'

// Utilities
export { cn } from './utils'

// Typography
export { Heading, type HeadingVariant } from './Heading'
export { Text, type TextVariant } from './Text'

// Layout
export { Page } from './Page'
export { PageHeader } from './PageHeader'
export { Section } from './Section'

// General UI
export {
  Card, CardHeader, CardBody, CardFooter,
  type CardVariant, type CardPadding,
} from './Card'
export { Button, IconButton, type ButtonVariant, type ButtonSize } from './Button'
export { Badge, type BadgeTone } from './Badge'
export { StatusBadge, StatusDot, type StatusKind } from './StatusBadge'

// Forms
export { FormField } from './FormField'
export { Input } from './Input'
export { TextArea } from './TextArea'
export { Select } from './Select'
export { Checkbox } from './Checkbox'
export { Switch } from './Switch'

// Navigation
export { Tabs } from './Tabs'

// Feedback
export { EmptyState } from './EmptyState'
export { LoadingState } from './LoadingState'
export { ToastProvider, useToast, type ToastTone } from './Toast'

// Overlays
export { Drawer, DrawerSection } from './Drawer'
export { Modal, ConfirmDialog } from './Modal'
export { ConfirmProvider, useConfirm, type ConfirmOptions } from './useConfirm'

// Shell
export {
  AppShell, AppShellBrand,
  type AppShellNavItem,
} from './AppShell'

// Root providers
export { FreshProviders } from './FreshProviders'

// Data
export {
  Table, TableHeader, TableBody, TableRow, TableHead, TableCell, emDash,
  type TableDensity,
} from './Table'

// Search
export { SearchInput } from './SearchInput'
