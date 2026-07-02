interface LogoProps {
  /** Rendered width/height in px. Default 24. */
  size?: number
  className?: string
}

/**
 * App logo mark — a rounded indigo→violet tile with a house glyph and a hub
 * node. Purely decorative (the adjacent wordmark carries the name), so it's
 * aria-hidden. Self-contained SVG so it stays crisp at any size and needs no
 * asset pipeline.
 */
export function Logo({ size = 24, className }: LogoProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      aria-hidden
    >
      <defs>
        <linearGradient id="logo-tile" x1="0" y1="0" x2="32" y2="32" gradientUnits="userSpaceOnUse">
          <stop stopColor="#6366f1" />
          <stop offset="1" stopColor="#8b5cf6" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="8" fill="url(#logo-tile)" />
      {/* house silhouette */}
      <path
        d="M16 6.5l8 6.2V24a1.5 1.5 0 0 1-1.5 1.5H19V19.5a1 1 0 0 0-1-1h-4a1 1 0 0 0-1 1v6H9.5A1.5 1.5 0 0 1 8 24V12.7l8-6.2z"
        fill="#fff"
      />
      {/* hub node in the roof */}
      <circle cx="16" cy="13.5" r="2.1" fill="url(#logo-tile)" />
    </svg>
  )
}
