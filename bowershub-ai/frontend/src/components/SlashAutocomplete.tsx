import { useState, useEffect } from 'react'
import { api } from '../services/api'
import { useWorkspaceStore } from '../stores/workspace'

interface CommandFlag {
  flag: string
  description: string
}

interface SlashCommand {
  command: string
  description: string
  flags: CommandFlag[]
}

interface Props {
  input: string
  onSelect: (command: string, send?: boolean) => void
  onClose: () => void
}

export default function SlashAutocomplete({ input, onSelect, onClose }: Props) {
  const [commands, setCommands] = useState<SlashCommand[]>([])
  const [selectedIndex, setSelectedIndex] = useState(0)
  const { activeWorkspace } = useWorkspaceStore()

  useEffect(() => {
    if (activeWorkspace) {
      api.get(`/api/slash-commands?workspace_id=${activeWorkspace.id}`)
        .then(res => setCommands(res.data || []))
        .catch(() => setCommands([]))
    }
  }, [activeWorkspace?.id])

  const inputLower = input.toLowerCase()
  const spaceIndex = inputLower.indexOf(' ')
  const baseCommand = spaceIndex > 0 ? inputLower.slice(0, spaceIndex) : inputLower
  const hasSpace = spaceIndex > 0
  const typedAfter = hasSpace ? inputLower.slice(spaceIndex + 1) : ''

  // Find the command's flags from the DB-driven list
  const matchedCommand = commands.find(c => c.command === baseCommand)
  const commandFlags = matchedCommand?.flags?.length ? matchedCommand.flags : null

  // Show flags when: typed a space after a command that has flags
  const showFlags = hasSpace && commandFlags

  // Build the items to display
  let items: { display: string; description: string; value: string; shouldSend: boolean }[] = []

  if (showFlags) {
    // Show matching flags (filter by what's typed after the space)
    items = commandFlags
      .filter((f: CommandFlag) => !typedAfter || f.flag.startsWith(typedAfter) || typedAfter === '-' || typedAfter === '--')
      .map((f: CommandFlag) => ({
        display: f.flag,
        description: f.description,
        value: `${baseCommand} ${f.flag}`,
        shouldSend: false,  // Don't send — let user append a team name
      }))
  } else if (!hasSpace) {
    // Show matching top-level commands
    items = commands
      .filter(cmd => cmd.command.startsWith(inputLower))
      .map(cmd => ({
        display: cmd.command,
        description: cmd.description,
        value: cmd.command,
        shouldSend: false,
      }))
  }

  useEffect(() => {
    setSelectedIndex(0)
  }, [input])

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (items.length === 0) return
      if (e.key === 'ArrowDown') {
        e.preventDefault()
        e.stopPropagation()
        setSelectedIndex(i => Math.min(i + 1, items.length - 1))
      } else if (e.key === 'ArrowUp') {
        e.preventDefault()
        e.stopPropagation()
        setSelectedIndex(i => Math.max(i - 1, 0))
      } else if (e.key === 'Tab' && items[selectedIndex]) {
        e.preventDefault()
        e.stopPropagation()
        const item = items[selectedIndex]
        onSelect(item.value, item.shouldSend)
      } else if (e.key === 'Enter' && items[selectedIndex]) {
        // When autocomplete is visible and user presses Enter, select the item
        // BUT only if they're actively narrowing (typing --). If they just see
        // suggestions after a space, let Enter send the message.
        if (typedAfter && typedAfter.startsWith('-')) {
          e.preventDefault()
          e.stopPropagation()
          const item = items[selectedIndex]
          onSelect(item.value, item.shouldSend)
        }
      } else if (e.key === 'Escape') {
        e.stopPropagation()
        onClose()
      }
    }
    window.addEventListener('keydown', handler, true)
    return () => window.removeEventListener('keydown', handler, true)
  }, [items, selectedIndex, typedAfter])

  if (items.length === 0) return null

  return (
    <div className="absolute bottom-full left-0 right-0 mb-2 mx-3">
      <div className="bg-surface border border-border rounded-lg shadow-xl overflow-hidden max-h-64 overflow-y-auto">
        {items.map((item, i) => (
          <button
            key={item.value + i}
            onClick={() => onSelect(item.value, item.shouldSend)}
            className={`
              w-full text-left px-4 py-2.5 flex items-center gap-3 text-sm
              ${i === selectedIndex ? 'bg-primary/20 text-text' : 'text-text hover:bg-surface'}
            `}
          >
            <span className="font-mono text-primary shrink-0">{item.display}</span>
            <span className="text-text-muted truncate">{item.description}</span>
          </button>
        ))}
      </div>
    </div>
  )
}
