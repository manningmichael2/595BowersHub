/**
 * useIsAdmin — returns whether the current user has the 'admin' role.
 *
 * Used throughout the DB Browser to gate write controls (Save, Add, Delete,
 * Create Table, etc.) so non-admin users get a read-only experience.
 * The backend's `require_admin` dependency returns 403 as a safety net.
 *
 * _Requirements: 21.2, 21.3_
 */
import { useHasRole } from './useHasRole'

export function useIsAdmin(): boolean {
  return useHasRole('admin')
}
