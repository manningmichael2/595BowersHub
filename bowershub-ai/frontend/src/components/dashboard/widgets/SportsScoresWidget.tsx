import type { WidgetProps } from '../WidgetRegistry'

export default function SportsScoresWidget({ data, widgetDef }: WidgetProps) {
  if (!data) {
    return <div className="p-4 text-sm text-text-muted">Loading scores...</div>
  }

  const display = data.display || data._display || ''
  if (data.error) {
    return <div className="p-4 text-sm text-danger">⚠️ {data.error}</div>
  }

  // Parse the display markdown into structured sections
  const sections = parseScoresDisplay(display)

  return (
    <div className="p-4 space-y-3">
      {sections.map((section, i) => (
        <div key={i}>
          {section.title && (
            <h3 className="text-xs font-semibold text-text-muted uppercase tracking-wide mb-1.5">
              {section.emoji} {section.title}
            </h3>
          )}
          <div className="space-y-1">
            {section.games.map((game, j) => (
              <GameLine key={j} game={game} />
            ))}
          </div>
        </div>
      ))}
      {!sections.length && <p className="text-sm text-text-muted">No games today.</p>}
    </div>
  )
}

interface GameInfo {
  away: string
  home: string
  awayScore?: number
  homeScore?: number
  status: string
  isLive: boolean
  isFinal: boolean
  winner?: 'away' | 'home' | null
}

function GameLine({ game }: { game: GameInfo }) {
  const statusColor = game.isLive ? 'text-danger' : game.isFinal ? 'text-text-muted' : 'text-primary'
  
  return (
    <div className="flex items-center justify-between text-sm py-1 border-b border-border last:border-0">
      <div className="flex-1 min-w-0">
        <span className={game.winner === 'away' ? 'font-semibold text-text' : 'text-text-muted'}>
          {game.away}
        </span>
        {(game.awayScore !== undefined || game.homeScore !== undefined) && (
          <span className="text-text-muted mx-1.5">
            {game.awayScore ?? 0} – {game.homeScore ?? 0}
          </span>
        )}
        <span className={game.winner === 'home' ? 'font-semibold text-text' : 'text-text-muted'}>
          {game.home}
        </span>
      </div>
      <span className={`text-xs shrink-0 ml-2 ${statusColor}`}>
        {game.isLive && '🔴 '}{game.status}
      </span>
    </div>
  )
}

interface Section {
  title: string
  emoji: string
  games: GameInfo[]
}

function parseScoresDisplay(display: string): Section[] {
  const sections: Section[] = []
  let currentSection: Section | null = null

  const lines = display.split('\n')
  for (const line of lines) {
    const trimmed = line.trim()
    if (!trimmed || trimmed === '---') continue

    // Section headers: **MLB**, ## 🏟️ My Teams
    const headerMatch = trimmed.match(/^\*\*(.+?)\*\*$/) || trimmed.match(/^#{1,3}\s*(.+)$/)
    if (headerMatch) {
      const title = headerMatch[1].replace(/[🏟️📅]/g, '').trim()
      const emoji = title.toLowerCase().includes('my team') ? '⭐' : 
                    title.includes('MLB') ? '⚾' :
                    title.includes('NBA') ? '🏀' :
                    title.includes('NHL') ? '🏒' :
                    title.includes('NFL') ? '🏈' :
                    title.includes('MLS') || title.includes('Premier') ? '⚽' : '🏟️'
      currentSection = { title, emoji, games: [] }
      sections.push(currentSection)
      continue
    }

    // Game lines: "- Away 4 – 5 Home (status)" or "- Away @ Home — time"
    const gameMatch = trimmed.match(/^-\s*(?:🔴\s*)?(.+?)(?:\s+(\d+)\s*[–-]\s*(\d+)\s+(.+?))?(?:\s*[\(—]\s*(.+?)\)?)?$/)
    if (gameMatch && currentSection) {
      const fullText = gameMatch[0].replace(/^-\s*(?:🔴\s*)?/, '')
      
      // Try to parse "Away Score – Score Home (status)"
      const scoreMatch = fullText.match(/^(.+?)\s+(\d+)\s*[–-]\s*(\d+)\s+(.+?)(?:\s*\((.+?)\))?$/)
      const atMatch = fullText.match(/^(.+?)\s*@\s*(.+?)\s*[—-]\s*(.+)$/)
      
      if (scoreMatch) {
        const awayScore = parseInt(scoreMatch[2])
        const homeScore = parseInt(scoreMatch[3])
        const status = scoreMatch[5] || 'Final'
        const isLive = fullText.includes('🔴') || status.toLowerCase().includes('inning') || status.toLowerCase().includes('quarter')
        currentSection.games.push({
          away: scoreMatch[1].replace(/\*\*/g, ''),
          home: scoreMatch[4].replace(/\*\*/g, ''),
          awayScore, homeScore, status,
          isLive,
          isFinal: status.toLowerCase().includes('final'),
          winner: awayScore > homeScore ? 'away' : homeScore > awayScore ? 'home' : null,
        })
      } else if (atMatch) {
        currentSection.games.push({
          away: atMatch[1].trim(),
          home: atMatch[2].trim(),
          status: atMatch[3].trim(),
          isLive: false,
          isFinal: false,
        })
      }
    }
  }

  return sections.filter(s => s.games.length > 0)
}
