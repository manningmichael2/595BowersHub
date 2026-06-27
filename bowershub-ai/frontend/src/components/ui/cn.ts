import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

/**
 * Merge class names with Tailwind-aware conflict resolution: `clsx` handles
 * conditional/array/object inputs, `twMerge` dedupes conflicting Tailwind
 * utilities so a caller's `className` override always wins (e.g.
 * `cn('px-4', 'px-2')` → `'px-2'`). The single class-composition helper every
 * `components/ui/` primitive uses.
 */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs))
}
