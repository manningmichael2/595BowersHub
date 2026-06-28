import { useState, type ReactNode } from 'react'
import { Message, useConversationStore } from '../stores/conversation'
import { useSettingsStore, TextSize, type VoiceSettings } from '../stores/settings'
import { useUIStore } from '../stores/ui'
import ReactMarkdown, { defaultUrlTransform } from 'react-markdown'
import { tts_strip } from '../lib/tts_strip'

interface Props {
  messages: Message[]
}

/**
 * Preserve our in-app link schemes that react-markdown's default transform would
 * otherwise strip for safety:
 *   - `cmd:<text>`  → send <text> as a chat message immediately
 *   - `fill:<text>` → load <text> into the composer (URL-encoded; user completes it)
 * Everything else falls back to the default (safe) transform.
 */
function urlTransform(url: string): string {
  if (url.startsWith('cmd:') || url.startsWith('fill:')) return url
  return defaultUrlTransform(url)
}

/**
 * Render markdown links, intercepting the `cmd:`/`fill:` schemes as buttons.
 * Shared by assistant and system messages so the behavior stays in one place.
 */
function ChatMarkdown({ content }: { content: string }) {
  const sendMessage = useConversationStore(s => s.sendMessage)
  const setComposerPrefill = useUIStore(s => s.setComposerPrefill)

  return (
    <ReactMarkdown
      urlTransform={urlTransform}
      components={{
        a: ({ href, children }: { href?: string; children?: ReactNode }) => {
          if (href?.startsWith('cmd:')) {
            return (
              <button
                type="button"
                onClick={() => sendMessage(decodeURIComponent(href.slice(4)))}
                className="text-accent hover:underline decoration-dotted underline-offset-4 text-left"
              >
                {children}
              </button>
            )
          }
          if (href?.startsWith('fill:')) {
            return (
              <button
                type="button"
                onClick={() => setComposerPrefill(decodeURIComponent(href.slice(5)))}
                className="text-accent hover:underline decoration-dotted underline-offset-4 text-left"
              >
                {children}
              </button>
            )
          }
          return (
            <a href={href} target="_blank" rel="noreferrer" className="text-accent hover:underline">
              {children}
            </a>
          )
        },
      }}
    >
      {content}
    </ReactMarkdown>
  )
}

/**
 * Map the user's effective text size to the corresponding `bh-text-*` class.
 * Note `extra_large` becomes `bh-text-xlarge` (shorter form to match the CSS
 * defined in `index.css`).
 */
const TEXT_SIZE_CLASS: Record<TextSize, string> = {
  small: 'bh-text-small',
  medium: 'bh-text-medium',
  large: 'bh-text-large',
  extra_large: 'bh-text-xlarge',
}

export default function MessageList({ messages }: Props) {
  // Per R4.4: the text-size class is applied to the chat-content wrapper only,
  // not the app root, so navigation/sidebar/header remain at their fixed size.
  const effectiveTextSize = useSettingsStore(s => s.effectiveTextSize)
  const sizeClass = TEXT_SIZE_CLASS[effectiveTextSize] ?? TEXT_SIZE_CLASS.medium

  return (
    <div className={`bh-chat-content space-y-4 ${sizeClass}`}>
      {messages.map(msg => (
        <MessageBubble key={msg.id} message={msg} />
      ))}
    </div>
  )
}

function MessageBubble({ message }: { message: Message }) {
  if (message.role === 'user') {
    return <UserMessage message={message} />
  }
  if (message.role === 'assistant') {
    return <AssistantMessage message={message} />
  }
  if (message.role === 'system') {
    return <SystemMessage message={message} />
  }
  return null
}

function UserMessage({ message }: { message: Message }) {
  return (
    <div className="flex gap-3 justify-end">
      <div className="max-w-[80%] md:max-w-[70%]">
        <div className="bg-primary rounded-2xl rounded-br-md px-4 py-2.5 text-sm text-on-primary">
          {message.content}
        </div>
        <div className="text-xs text-text-muted mt-1 text-right">
          {formatRelativeTime(message.created_at)}
        </div>
      </div>
    </div>
  )
}

function AssistantMessage({ message }: { message: Message }) {
  const [isReading, setIsReading] = useState(false)
  const voice = useSettingsStore(s => s.settings.voice)

  const handleReadAloud = () => {
    const synth = window.speechSynthesis
    if (!synth) return

    if (isReading) {
      // Stop reading this message
      synth.cancel()
      setIsReading(false)
      return
    }

    // Strip markdown/code for clean speech
    const text = tts_strip(message.content).trim()
    if (!text) return

    const utter = new SpeechSynthesisUtterance(text)
    const rate = (voice as VoiceSettings)?.speech_rate ?? 1.0
    utter.rate = Math.max(0.5, Math.min(2.0, rate))

    const wantedName = ((voice as VoiceSettings)?.voice_name || '').trim()
    if (wantedName) {
      const match = synth.getVoices().find(v => v.name === wantedName)
      if (match) utter.voice = match
    }

    utter.onend = () => setIsReading(false)
    utter.onerror = () => setIsReading(false)

    synth.cancel() // cancel any prior speech
    synth.speak(utter)
    setIsReading(true)
  }

  const ttsAvailable = typeof window !== 'undefined' && !!window.speechSynthesis

  return (
    <div className="group flex gap-3">
      <div className="w-7 h-7 rounded-full bg-success flex items-center justify-center text-xs shrink-0 mt-1">
        AI
      </div>
      <div className="flex-1 min-w-0 max-w-[85%]">
        <div className="markdown-content text-text text-sm">
          <ChatMarkdown content={message.content} />
        </div>
        <div className="flex items-center gap-2 mt-1.5">
          {message.routing_layer && (
            <LayerBadge layer={message.routing_layer} />
          )}
          {message.cost_usd != null && message.cost_usd > 0 && (
            <span className="text-xs text-text-muted">
              ${message.cost_usd < 0.01 ? message.cost_usd.toFixed(4) : message.cost_usd.toFixed(2)}
            </span>
          )}
          {message.model_used && (
            <span className="text-xs text-text-muted">
              {message.model_used.includes('haiku') ? 'Haiku' :
               message.model_used.includes('sonnet') ? 'Sonnet' :
               message.model_used.includes('opus') ? 'Opus' : ''}
            </span>
          )}
          <span className="text-xs text-text-muted">
            {formatRelativeTime(message.created_at)}
          </span>
          {/* Read aloud button — visible on hover (desktop) or always (mobile) */}
          {ttsAvailable && (
            <button
              type="button"
              onClick={handleReadAloud}
              className={
                'text-xs px-1.5 py-0.5 rounded transition-colors ' +
                (isReading
                  ? 'text-warning bg-warning/20'
                  : 'text-text-muted hover:text-text opacity-0 group-hover:opacity-100 sm:opacity-0 sm:group-hover:opacity-100 max-sm:opacity-60')
              }
              title={isReading ? 'Stop reading' : 'Read aloud'}
              aria-label={isReading ? 'Stop reading' : 'Read aloud'}
            >
              {isReading ? '⏹ Stop' : '🔊 Read'}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

function SystemMessage({ message }: { message: Message }) {
  return (
    <div className="flex justify-center">
      <div className="bg-surface rounded-lg px-4 py-2 text-xs text-text-muted max-w-[80%]">
        <ChatMarkdown content={message.content} />
      </div>
    </div>
  )
}

function LayerBadge({ layer }: { layer: string }) {
  const colors: Record<string, string> = {
    L1: 'bg-success/20 text-success',
    L2: 'bg-primary/20 text-primary',
    L3: 'bg-primary/20 text-accent',
  }
  return (
    <span className={`text-xs px-1.5 py-0.5 rounded ${colors[layer] || 'bg-surface text-text-muted'}`}>
      {layer}
    </span>
  )
}

function formatRelativeTime(dateStr: string): string {
  const date = new Date(dateStr)
  const now = new Date()
  const diff = now.getTime() - date.getTime()

  if (diff < 60000) return 'just now'
  if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`
  if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`
  if (diff < 604800000) return `${Math.floor(diff / 86400000)}d ago`
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}
