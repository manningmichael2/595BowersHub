/**
 * Property-based tests for `lib/tts_strip.ts` — the markdown-stripping helper
 * that prepares assistant responses for browser SpeechSynthesis output in
 * Voice_Mode (R10.5).
 *
 * The contract under test (per the design doc and tasks.md task 27.4):
 *   1. tts_strip always returns a string and never throws, regardless of input
 *      type (string or non-string).
 *   2. The output never contains a fenced code block (no ``` lines remain).
 *   3. The output never contains a markdown table separator (e.g. `|---|`).
 *   4. The output never contains image syntax `![alt](url)`.
 *   5. Plain prose without code, tables, or images passes through unchanged.
 *
 * Property 8: TTS markdown stripping preserves prose and elides
 * code/tables/images.
 *
 * Validates: Requirements R10.5
 *
 * Iterations: 200 per property (above the 100-iteration floor in the design
 * doc).
 */

import { describe, it, expect } from 'vitest'
import fc from 'fast-check'

import { tts_strip } from '../tts_strip'

// --- Helpers ------------------------------------------------------------------

/** Detect a markdown table separator line (e.g. `| --- | :---: |`). */
function hasTableSeparator(s: string): boolean {
  // Look for a line that, after trimming, consists entirely of `|`, `-`, `:`,
  // and whitespace, AND contains at least one `-` (so we don't false-match an
  // empty `||` line). At least one `|` somewhere on the line.
  const lines = s.split('\n')
  return lines.some((line) => {
    const trimmed = line.trim()
    if (!trimmed.includes('|') || !trimmed.includes('-')) return false
    return /^[|\-:\s]+$/.test(trimmed)
  })
}

/** Detect a fenced code block opening on its own line (``` or ~~~). */
function hasFencedCodeBlock(s: string): boolean {
  // R10.5 says fenced code blocks should not survive. The opening fence is
  // 3-or-more backticks/tildes at the start of a line (allowing up to 3
  // leading spaces per CommonMark).
  const lines = s.split('\n')
  return lines.some((line) => /^\s{0,3}(`{3,}|~{3,})/.test(line))
}

/** Detect inline markdown image syntax `![alt](url)`. */
function hasImageSyntax(s: string): boolean {
  return /!\[[^\]]*\]\([^)]*\)/.test(s)
}

// --- Generators ---------------------------------------------------------------

/**
 * Plain prose: arbitrary text guaranteed to contain none of the three
 * stripped constructs. We start from a unicode string and reject any sample
 * that happens to look like a code fence, table separator, or image.
 *
 * Using `fc.unicodeString` (not `string`) is important — the production
 * function preserves arbitrary characters and we want to catch any
 * accidental drops.
 */
const plainProseArb = fc
  .unicodeString({ minLength: 0, maxLength: 200 })
  .filter(
    (s) =>
      !hasFencedCodeBlock(s) &&
      !hasTableSeparator(s) &&
      !hasImageSyntax(s) &&
      // Avoid prose that *coincidentally* forms a table header + separator
      // pair, which the helper would (correctly) elide.
      !/(^|\n)[^\n]*\|[^\n]*\n\s{0,3}[|\-:\s]*-+[|\-:\s]*(\n|$)/.test(s),
  )

/** Arbitrary input — strings, numbers, null, undefined, objects, arrays. */
const anyInputArb = fc.oneof(
  fc.string(),
  fc.unicodeString(),
  fc.integer(),
  fc.float(),
  fc.boolean(),
  fc.constant(null),
  fc.constant(undefined),
  fc.constant({}),
  fc.constant([]),
  fc.array(fc.anything(), { maxLength: 5 }),
  fc.object({ maxKeys: 3 }),
)

/**
 * A markdown document that may include any mix of fenced code blocks,
 * tables, images, and prose paragraphs in any order. Built from chunks so
 * the structure is realistic without being trivially small.
 */
const fenceChunkArb = fc
  .tuple(fc.constantFrom('```', '````', '~~~'), fc.string({ maxLength: 50 }))
  .map(([fence, body]) => `${fence}\n${body.replace(/\n/g, ' ')}\n${fence}`)

const tableChunkArb = fc
  .tuple(
    fc.string({ maxLength: 20 }).filter((s) => !s.includes('|') && !s.includes('\n')),
    fc.string({ maxLength: 20 }).filter((s) => !s.includes('|') && !s.includes('\n')),
    fc.string({ maxLength: 20 }).filter((s) => !s.includes('|') && !s.includes('\n')),
    fc.string({ maxLength: 20 }).filter((s) => !s.includes('|') && !s.includes('\n')),
  )
  .map(
    ([h1, h2, c1, c2]) =>
      `| ${h1 || 'a'} | ${h2 || 'b'} |\n| --- | --- |\n| ${c1 || 'x'} | ${c2 || 'y'} |`,
  )

const imageChunkArb = fc
  .tuple(
    fc.string({ maxLength: 30 }).filter((s) => !s.includes(']') && !s.includes('\n')),
    fc.string({ maxLength: 80 }).filter((s) => !s.includes(')') && !s.includes('\n')),
  )
  .map(([alt, url]) => `![${alt}](${url || 'https://example.com/x.png'})`)

const proseChunkArb = plainProseArb

const chunkArb = fc.oneof(
  { weight: 3, arbitrary: proseChunkArb },
  { weight: 2, arbitrary: fenceChunkArb },
  { weight: 2, arbitrary: tableChunkArb },
  { weight: 2, arbitrary: imageChunkArb },
)

const markdownDocArb = fc
  .array(chunkArb, { minLength: 0, maxLength: 6 })
  .map((chunks) => chunks.join('\n\n'))

// --- Tests --------------------------------------------------------------------

describe('tts_strip — property tests (Property 8 / R10.5)', () => {
  it('Property 8a: returns a string and never throws on any input', () => {
    fc.assert(
      fc.property(anyInputArb, (input) => {
        let out: unknown
        expect(() => {
          out = tts_strip(input as unknown as string)
        }).not.toThrow()
        expect(typeof out).toBe('string')
      }),
      { numRuns: 200 },
    )
  })

  it('Property 8b: output never contains a fenced code block', () => {
    fc.assert(
      fc.property(markdownDocArb, (doc) => {
        const out = tts_strip(doc)
        expect(hasFencedCodeBlock(out)).toBe(false)
      }),
      { numRuns: 200 },
    )
  })

  it('Property 8c: output never contains a markdown table separator', () => {
    fc.assert(
      fc.property(markdownDocArb, (doc) => {
        const out = tts_strip(doc)
        expect(hasTableSeparator(out)).toBe(false)
      }),
      { numRuns: 200 },
    )
  })

  it('Property 8d: output never contains image syntax `![...](...)`', () => {
    fc.assert(
      fc.property(markdownDocArb, (doc) => {
        const out = tts_strip(doc)
        expect(hasImageSyntax(out)).toBe(false)
      }),
      { numRuns: 200 },
    )
  })

  it('Property 8e: plain prose without code/tables/images passes through unchanged', () => {
    fc.assert(
      fc.property(plainProseArb, (prose) => {
        // Sanity: our generator must actually produce prose free of all three
        // constructs, otherwise the assertion below is testing the wrong path.
        expect(hasFencedCodeBlock(prose)).toBe(false)
        expect(hasTableSeparator(prose)).toBe(false)
        expect(hasImageSyntax(prose)).toBe(false)

        expect(tts_strip(prose)).toBe(prose)
      }),
      { numRuns: 200 },
    )
  })
})
