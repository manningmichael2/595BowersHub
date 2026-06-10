import type { WidgetProps } from '../WidgetRegistry'

export default function NewsWidget({ data }: WidgetProps) {
  if (!data) return <div className="text-sm" style={{ color: 'var(--color-text-muted)' }}>Loading...</div>

  const d = data as { stories?: { title: string; url: string; published: string }[]; error?: string | null }
  if (d.error) return <div className="text-sm" style={{ color: 'var(--color-text-muted)' }}>⚠ {d.error}</div>

  const stories = d.stories || []
  if (stories.length === 0) return <div className="text-sm" style={{ color: 'var(--color-text-muted)' }}>No stories</div>

  return (
    <div className="flex flex-col gap-1.5">
      {stories.map((story, i) => (
        <a
          key={i}
          href={story.url}
          target="_blank"
          rel="noopener noreferrer"
          className="block rounded px-2 py-1.5 text-sm hover:opacity-80 transition-opacity"
          style={{ color: 'var(--color-text)' }}
        >
          <span className="line-clamp-2">{story.title}</span>
        </a>
      ))}
    </div>
  )
}
