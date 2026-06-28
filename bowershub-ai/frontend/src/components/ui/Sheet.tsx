import { forwardRef } from 'react'
import * as DialogPrimitive from '@radix-ui/react-dialog'
import { cn } from './cn'

/**
 * Sheet — an edge-anchored modal panel over Radix Dialog (R2.2): focus trap +
 * return, ESC, scroll lock, portalled content. Same engine as `Dialog`, but the
 * content slides in from a screen edge and fills the viewport height, so it
 * works as a mobile nav drawer / side panel. Scrolls internally when its content
 * exceeds the viewport. Styled with tokens + the z-index/elevation scales.
 */
export const Sheet = DialogPrimitive.Root
export const SheetTrigger = DialogPrimitive.Trigger
export const SheetClose = DialogPrimitive.Close
export const SheetPortal = DialogPrimitive.Portal

export const SheetOverlay = forwardRef<
  React.ElementRef<typeof DialogPrimitive.Overlay>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Overlay>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Overlay
    ref={ref}
    className={cn('fixed inset-0 z-modal bg-black/60 animate-fade-in', className)}
    {...props}
  />
))
SheetOverlay.displayName = DialogPrimitive.Overlay.displayName

export const SheetContent = forwardRef<
  React.ElementRef<typeof DialogPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Content> & { side?: 'left' | 'right' }
>(({ side = 'left', className, children, ...props }, ref) => (
  <SheetPortal>
    <SheetOverlay />
    <DialogPrimitive.Content
      ref={ref}
      className={cn(
        'fixed bottom-0 top-0 z-modal flex w-[min(20rem,82vw)] flex-col overflow-y-auto bg-surface text-text shadow-elevation-3 focus:outline-none',
        side === 'left'
          ? 'left-0 border-r border-border animate-slide-in-left'
          : 'right-0 border-l border-border animate-slide-in-right',
        className,
      )}
      style={{
        paddingTop: 'env(safe-area-inset-top, 0px)',
        paddingBottom: 'env(safe-area-inset-bottom, 0px)',
        ...(side === 'left'
          ? { paddingLeft: 'env(safe-area-inset-left, 0px)' }
          : { paddingRight: 'env(safe-area-inset-right, 0px)' }),
      }}
      {...props}
    >
      {children}
    </DialogPrimitive.Content>
  </SheetPortal>
))
SheetContent.displayName = DialogPrimitive.Content.displayName

/** Visually-hidden title — Radix requires a Title in the content for a11y. */
export const SheetTitle = forwardRef<
  React.ElementRef<typeof DialogPrimitive.Title>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Title>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Title ref={ref} className={cn('sr-only', className)} {...props} />
))
SheetTitle.displayName = DialogPrimitive.Title.displayName
