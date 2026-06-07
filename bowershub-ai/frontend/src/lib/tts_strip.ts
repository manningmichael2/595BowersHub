/**
 * tts_strip — strip markdown elements that don't read aloud well, for use by
 * Voice_Mode TTS output (R10.5).
 *
 * Replaces:
 *   - Fenced code blocks (``` or ~~~)        → "code block omitted"
 *   - Markdown tables (GFM-style with sep)   → "table omitted"
 *   - Inline images `![alt](url)`            → "image: <alt>" if alt is non-empty
 *                                              else "image omitted"
 *
 * Prose outside these regions is preserved verbatim and in order. The function
 * is pure and never throws.
 *
 * Validates: Requirement R10.5
 */

const FENCE_OPEN_RE = /^(\s{0,3})(`{3,}|~{3,})(.*)$/;
const IMAGE_RE = /!\[([^\]]*)\]\(([^)]*)\)/g;

/** Returns true iff the line is a markdown table separator like `| --- | :--- |`. */
function isTableSeparator(line: string): boolean {
  if (!line.includes('|') || !line.includes('-')) return false;
  // Strip leading/trailing pipes to handle both `| a | b |` and `a | b` forms,
  // then every cell must be a (possibly aligned) run of dashes.
  const trimmed = line.trim().replace(/^\|/, '').replace(/\|$/, '');
  const cells = trimmed.split('|');
  if (cells.length < 1) return false;
  return cells.every((c) => /^\s*:?-+:?\s*$/.test(c));
}

/** Returns true iff the closing fence on `line` matches the opening fence. */
function isFenceClose(line: string, fenceChar: string, minLen: number): boolean {
  const m = line.match(/^(\s{0,3})(`{3,}|~{3,})\s*$/);
  if (!m) return false;
  return m[2][0] === fenceChar && m[2].length >= minLen;
}

export function tts_strip(markdown: string): string {
  // Guard contract: always return a string. Non-string inputs (arrays,
  // objects, numbers, null, undefined) collapse to '' so consumers can
  // safely concat the result without a type check (R10.5).
  if (typeof markdown !== 'string') return '';
  if (markdown.length === 0) return '';

  const lines = markdown.split('\n');
  const out: string[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    // 1) Fenced code block
    const fence = line.match(FENCE_OPEN_RE);
    if (fence) {
      const fenceChar = fence[2][0];
      const fenceLen = fence[2].length;
      i++;
      while (i < lines.length && !isFenceClose(lines[i], fenceChar, fenceLen)) {
        i++;
      }
      // Consume the closing fence if present (an unclosed fence runs to EOF).
      if (i < lines.length) i++;
      out.push('code block omitted');
      continue;
    }

    // 2) Markdown table: header row containing `|` followed by a separator row.
    if (line.includes('|') && i + 1 < lines.length && isTableSeparator(lines[i + 1])) {
      // Consume header + separator + any contiguous body rows that contain `|`.
      i += 2;
      while (i < lines.length && lines[i].includes('|') && lines[i].trim() !== '') {
        i++;
      }
      out.push('table omitted');
      continue;
    }

    out.push(line);
    i++;
  }

  let result = out.join('\n');

  // 3) Inline images. The URL is dropped; alt text is announced if present.
  result = result.replace(IMAGE_RE, (_match, alt: string) => {
    const trimmed = alt.trim();
    return trimmed ? `image: ${trimmed}` : 'image omitted';
  });

  return result;
}
