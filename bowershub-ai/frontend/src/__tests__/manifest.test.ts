/**
 * Manifest assertion test for the PWA Web Share Target.
 *
 * Covers the manifest half of task 26.4. We read the source
 * `frontend/public/manifest.json` (the file vite copies verbatim into
 * the built bundle) and assert its `share_target` block has the shape
 * required by the share-target wiring (R9.6) so that an Android share
 * intent landing on BowersHub AI routes to the `/quick-capture` SPA
 * route as a `multipart/form-data` POST with the expected named params.
 *
 * Why source instead of the built artifact:
 *   - `vite build` copies `public/manifest.json` byte-for-byte; the
 *     manifest itself isn't transformed.
 *   - Reading the source keeps the test runnable without `vite build`
 *     having executed first, which keeps `npm test` self-contained.
 *
 * _Requirements: R9.6 (manifest declares share target)
 */

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const MANIFEST_PATH = resolve(__dirname, '..', '..', 'public', 'manifest.json')

interface ShareTargetFileSpec {
  name?: string
  accept?: string | string[]
}

interface ShareTargetParams {
  title?: string
  text?: string
  url?: string
  files?: ShareTargetFileSpec[]
}

interface ShareTarget {
  action?: string
  method?: string
  enctype?: string
  params?: ShareTargetParams
}

interface Manifest {
  share_target?: ShareTarget
  [k: string]: unknown
}

function readManifest(): Manifest {
  const raw = readFileSync(MANIFEST_PATH, 'utf8')
  return JSON.parse(raw) as Manifest
}

describe('manifest.json — share_target block (R9.6)', () => {
  it('declares the share_target block with the documented shape', () => {
    const manifest = readManifest()
    const target = manifest.share_target

    // Block must exist — without it the BowersHub AI entry never appears
    // in the Android share sheet.
    expect(target).toBeTruthy()
  })

  it('routes share intents to /quick-capture via POST + multipart/form-data', () => {
    const target = readManifest().share_target!

    // Action targets the SPA route the service worker + React Router
    // both know how to handle.
    expect(target.action).toBe('/quick-capture')

    // The browser sends the share payload as a POST so the SW can
    // intercept it; multipart is required for the file slot.
    expect((target.method || '').toUpperCase()).toBe('POST')
    expect(target.enctype).toBe('multipart/form-data')
  })

  it('declares title/text/url params plus an image-accepting files slot', () => {
    const params = readManifest().share_target!.params

    expect(params).toBeTruthy()
    // Standard share-text params — Android populates these from the
    // sharing app's intent extras.
    expect(params!.title).toBe('title')
    expect(params!.text).toBe('text')
    expect(params!.url).toBe('url')

    // The files slot is the most important assertion — it lets users
    // share images straight into Quick Capture from the gallery.
    const files = params!.files
    expect(Array.isArray(files)).toBe(true)
    expect(files!.length).toBeGreaterThanOrEqual(1)

    const firstFile = files![0]
    expect(firstFile.name).toBe('files')

    // `accept` may be a string or an array per the Web Share Target
    // spec. Normalize and assert image/* is included.
    const accept = firstFile.accept
    const acceptList = Array.isArray(accept)
      ? accept
      : typeof accept === 'string'
        ? [accept]
        : []
    expect(acceptList).toContain('image/*')
  })
})
