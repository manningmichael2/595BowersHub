import { forwardRef } from 'react'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from './cn'

/**
 * Button — the canonical action primitive (R2.3). Variants/sizes are a single
 * `cva` map reading the theme color tokens + foreground aliases (so it restyles
 * with the active theme) and the R1.5 motion tokens (`duration-base`,
 * `ease-standard`). Focus ring uses the tokenized `ring-primary` offset against
 * the page background for a visible, theme-aware focus indicator.
 */
export const buttonVariants = cva(
  'inline-flex items-center justify-center gap-2 rounded-md font-medium select-none ' +
    'transition-colors duration-base ease-standard ' +
    'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary ' +
    'focus-visible:ring-offset-2 focus-visible:ring-offset-background ' +
    'disabled:pointer-events-none disabled:opacity-50',
  {
    variants: {
      variant: {
        primary: 'bg-primary text-on-primary hover:bg-primary/90 active:bg-primary/80',
        secondary:
          'border border-border bg-surface text-text hover:bg-surface-light active:bg-surface',
        outline: 'border border-border bg-transparent text-text hover:bg-surface-light',
        ghost: 'bg-transparent text-text hover:bg-surface-light',
        danger: 'bg-danger text-on-danger hover:bg-danger/90 active:bg-danger/80',
      },
      size: {
        sm: 'h-8 px-3 text-sm',
        md: 'h-10 px-4 text-sm',
        lg: 'h-11 px-6 text-base',
        icon: 'h-10 w-10',
      },
    },
    defaultVariants: { variant: 'primary', size: 'md' },
  },
)

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, type = 'button', ...props }, ref) => (
    <button
      ref={ref}
      type={type}
      className={cn(buttonVariants({ variant, size }), className)}
      {...props}
    />
  ),
)
Button.displayName = 'Button'
