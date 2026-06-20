/**
 * MerchantLogo — a small merchant avatar that DEGRADES GRACEFULLY (R1.6).
 *
 * Tries a favicon (Google's favicon service, derived from the merchant key) and,
 * on any load error, falls back to a deterministic letter-avatar. There is never
 * a broken-image icon, and a missing/blocked network never blocks the row from
 * rendering — the fallback is shown immediately if no key is available.
 */
import { useState } from 'react'

interface Props {
  merchantKey: string | null
  size?: number
}

function initials(key: string): string {
  const words = key.replace(/[^A-Za-z0-9 ]/g, ' ').trim().split(/\s+/).filter(Boolean)
  if (words.length === 0) return '?'
  // Two letters: first letter of the first two words, or the first two chars of
  // a single-word merchant (e.g. COSTCO → "CO").
  const two = words.length > 1 ? words[0][0] + words[1][0] : words[0].slice(0, 2)
  return two.toUpperCase()
}

// Deterministic hue from the key so the same merchant always gets the same colour.
function hue(key: string): number {
  let h = 0
  for (const c of key) h = (h * 31 + c.charCodeAt(0)) % 360
  return h
}

export default function MerchantLogo({ merchantKey, size = 28 }: Props) {
  const [failed, setFailed] = useState(false)
  const key = (merchantKey ?? '').trim()

  const avatar = (
    <div
      data-testid="merchant-logo-fallback"
      aria-hidden="true"
      style={{
        width: size, height: size, borderRadius: 6,
        background: key ? `hsl(${hue(key)} 60% 35%)` : 'var(--color-surface-2, #444)',
        color: '#fff', fontSize: size * 0.42, fontWeight: 600,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        flexShrink: 0,
      }}
    >
      {key ? initials(key) : '?'}
    </div>
  )

  // No key, or the image already failed → straight to the fallback (no broken img).
  if (!key || failed) return avatar

  // Guess a domain from the first token; the favicon service returns its own
  // default on a miss, but we still guard with onError → letter avatar.
  const domain = `${key.split(/\s+/)[0].toLowerCase()}.com`
  return (
    <img
      data-testid="merchant-logo-img"
      src={`https://www.google.com/s2/favicons?domain=${encodeURIComponent(domain)}&sz=64`}
      alt=""
      width={size}
      height={size}
      style={{ borderRadius: 6, flexShrink: 0 }}
      onError={() => setFailed(true)}
      loading="lazy"
    />
  )
}
