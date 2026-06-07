import { useState, useEffect } from 'react'
import { api } from '../services/api'
import { useWorkspaceStore } from '../stores/workspace'

interface SlashCommand {
  command: string
  description: string
}

interface Props {
  input: string
  onSelect: (command: string) => void
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
        .catch(() => {
          // Fallback defaults
          setCommands([
            { command: '/help', description: 'List available commands' },
            { command: '/balance', description: 'Show account balances' },
            { command: '/weather', description: 'Get weather (any location)' },
            { command: '/score', description: 'Live sports scores' },
            { command: '/recall', description: 'Search knowledge base' },
            { command: '/remember', description: 'Save a fact (topic then fact)' },
            { command: '/transactions', description: 'Recent transactions' },
            { command: '/inventory', description: 'Inventory counts' },
            { command: '/spend', description: 'Monthly spending summary' },
            { command: '/cost', description: "Today's AI spend" },
            { command: '/new', description: 'Start new conversation' },
          ])
        })
    }
  }, [activeWorkspace?.id])

  // Filter by typed text
  const filtered = commands.filter(cmd =>
    cmd.command.startsWith(input.toLowerCase())
  )

  useEffect(() => {
    setSelectedIndex(0)
  }, [input])

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'ArrowDown') {
        e.preventDefault()
        setSelectedIndex(i => Math.min(i + 1, filtered.length - 1))
      } else if (e.key === 'ArrowUp') {
        e.preventDefault()
        setSelectedIndex(i => Math.max(i - 1, 0))
      } else if ((e.key === 'Enter' || e.key === 'Tab') && filtered[selectedIndex]) {
        e.preventDefault()
        onSelect(filtered[selectedIndex].command)
      } else if (e.key === 'Escape') {
        onClose()
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [filtered, selectedIndex])

  if (filtered.length === 0) return null

  return (
    <div className="absolute bottom-full left-0 right-0 mb-2 mx-3">
      <div className="bg-[#1e1e3a] border border-gray-700 rounded-lg shadow-xl overflow-hidden max-h-64 overflow-y-auto">
        {filtered.map((cmd, i) => (
          <button
            key={cmd.command}
            onClick={() => onSelect(cmd.command)}
            className={`
              w-full text-left px-4 py-2.5 flex items-center gap-3 text-sm
              ${i === selectedIndex ? 'bg-indigo-600/20 text-indigo-200' : 'text-gray-300 hover:bg-gray-800/50'}
            `}
          >
            <span className="font-mono text-indigo-400 shrink-0">{cmd.command}</span>
            <span className="text-gray-500 truncate">{cmd.description}</span>
          </button>
        ))}
      </div>
    </div>
  )
}
