/**
 * Runtime validation at the API boundary.
 *
 * project-review.md C6: the ApiClient returns `Promise<any>` and responses are
 * blind-cast (`as Conversation[]`), so a backend shape change fails silently at
 * runtime, defeating the strict TS config exactly where data crosses the wire.
 *
 * `parseLoose` validates a payload against a zod schema and is *soft by design*:
 * on a mismatch it logs the issues (and surfaces a dev toast) but still returns
 * the data, so a benign additive backend change never white-screens the app.
 * What it buys is visibility — silent drift becomes a loud console error instead
 * of an `undefined` three components deep. Object schemas should use
 * `.passthrough()` so unknown fields are preserved, not stripped.
 */

import type { z } from 'zod'
import { toast } from '../stores/toast'

export function parseLoose<S extends z.ZodTypeAny>(
  schema: S,
  data: unknown,
  label: string,
): z.infer<S> {
  const result = schema.safeParse(data)
  if (result.success) {
    return result.data
  }
  // Drift detected — make it visible rather than failing somewhere downstream.
  console.error(`[api] response shape mismatch at ${label}:`, result.error.issues, { data })
  if (import.meta.env.DEV) {
    toast.error(`Unexpected data from ${label} — see console.`)
  }
  return data as z.infer<S>
}
