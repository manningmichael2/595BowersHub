/**
 * components/ui — the owned design-system primitives layer (R2.1).
 *
 * Call-sites import from here, never from the vendor libraries directly. This
 * barrel currently re-exports the hand-rolled presentational primitives (R2.3);
 * Radix chrome, state primitives, the themed toast, and React Aria finance
 * widgets are added in later Phase-2 tasks.
 */
export { cn } from './cn'
export { Button, buttonVariants, type ButtonProps } from './Button'
export {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
  CardFooter,
} from './Card'
export { Input } from './Input'
export { Textarea } from './Textarea'
export { Badge, badgeVariants, type BadgeProps } from './Badge'
export { Label } from './Label'
export { Separator, type SeparatorProps } from './Separator'

// State primitives (R2.6)
export { Spinner, type SpinnerProps } from './Spinner'
export { Skeleton } from './Skeleton'
export { EmptyState, type EmptyStateProps } from './EmptyState'
export { ErrorState, type ErrorStateProps } from './ErrorState'
export { FieldError } from './FieldError'

// Radix-backed chrome primitives (R2.2)
export * from './Dialog'
export * from './Sheet'
export * from './AlertDialog'
export * from './DropdownMenu'
export * from './Popover'
export * from './Tooltip'
export * from './Select'
export * from './Tabs'
export * from './Switch'
export * from './ScrollArea'
