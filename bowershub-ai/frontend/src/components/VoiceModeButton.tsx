/**
 * VoiceModeButton — microphone toggle + stop-speaking button.
 *
 * Implements task 27.3:
 *   - Microphone button that toggles `useVoiceMode` STT on/off (R10.1).
 *     Visual states: idle (outline mic), listening (filled mic, red,
 *     pulsing).
 *   - Stop-speaking button shown only while TTS is active (`isSpeaking`)
 *     so the user can cut off the assistant mid-sentence (R10.7).
 *   - Capability gating (R10.8):
 *       - If `SpeechRecognition` / `webkitSpeechRecognition` is not
 *         available, the mic button is hidden entirely. The first time
 *         the component mounts in such a browser, a one-time
 *         dismissable toast explains why. The dismissal is persisted in
 *         localStorage so the message does not re-appear on subsequent
 *         visits.
 *       - If only STT is unsupported but TTS is, the stop-speaking
 *         button still renders during TTS playback so users can still
 *         interrupt read-aloud replies. Voice unavailability of STT
 *         is what triggers the toast.
 *
 * Props let the parent wire the chat-input field to the partial
 * transcript stream and dispatch a send when the recognizer
 * auto-finalizes after a pause:
 *   - `onTranscriptUpdate(text, isFinal)`: each STT result tick.
 *   - `onAutoSubmit(text)`: fired on auto-finalize unless
 *     `voice.manual_send` is on (handled inside `useVoiceMode`).
 *
 * _Requirements: R10.1, R10.7, R10.8
 */
import { useEffect, useState } from 'react'
import { useVoiceMode } from '../hooks/useVoiceMode'
import { useSettingsStore } from '../stores/settings'

// Persisted flag — keeps the unsupported-browser toast a true "one-time"
// notice across page reloads and across PWA cold starts on the same device.
const TOAST_DISMISSED_KEY = 'bh.voiceUnsupportedToastDismissed'

// Auto-dismiss after this many ms so the toast doesn't sit forever if the
// user ignores it.
const TOAST_AUTO_DISMISS_MS = 8000

export interface VoiceModeButtonProps {
  /**
   * Mirror the partial transcript into the chat input as the user speaks
   * (R10.2). Called on every recognition tick — interim and final.
   */
  onTranscriptUpdate?: (text: string, isFinal: boolean) => void

  /**
   * Submit the message when the recognizer auto-finalizes after a pause
   * (R10.3). Not called when `voice.manual_send` is on; in that case the
   * consumer keeps the transcript in the input field and the user presses
   * Send themselves.
   */
  onAutoSubmit?: (text: string) => void
}

function readToastDismissed(): boolean {
  try {
    return localStorage.getItem(TOAST_DISMISSED_KEY) === '1'
  } catch {
    return false
  }
}

function persistToastDismissed() {
  try {
    localStorage.setItem(TOAST_DISMISSED_KEY, '1')
  } catch {
    // localStorage full / disabled — non-fatal; we just won't remember
    // across reloads.
  }
}

export default function VoiceModeButton({
  onTranscriptUpdate,
  onAutoSubmit,
}: VoiceModeButtonProps) {
  const {
    isListening,
    isSpeaking,
    capabilities,
    start,
    stop,
    stopSpeaking,
  } = useVoiceMode({ onTranscriptUpdate, onAutoSubmit })

  const sttSupported = capabilities.stt
  const ttsSupported = capabilities.tts

  // Read TTS enabled state from the global settings store — this is the
  // single source of truth for whether the assistant reads replies aloud.
  const ttsEnabled = useSettingsStore(
    s => s.settings.voice?.output_enabled !== false,
  )
  const patchSettings = useSettingsStore(s => s.patch)

  const handleTtsToggle = () => {
    // Toggle output_enabled in the global store (persisted to backend).
    const newVal = !ttsEnabled
    void patchSettings({ voice: { output_enabled: newVal } })
    // If disabling, also cancel any in-flight speech immediately.
    if (!newVal) {
      stopSpeaking()
    }
  }

  const handleStopSpeaking = () => {
    // Stop current speech only — do NOT disable output_enabled.
    // The user can still re-enable auto-read or tap the per-message
    // "read aloud" button on any reply.
    stopSpeaking()
  }

  // One-time toast for browsers that don't support STT (R10.8). The toast
  // surface shows when (a) STT is unsupported and (b) the user hasn't
  // dismissed it yet on this device.
  const [toastVisible, setToastVisible] = useState<boolean>(
    () => !sttSupported && !readToastDismissed(),
  )

  // Auto-dismiss timer.
  useEffect(() => {
    if (!toastVisible) return
    const handle = window.setTimeout(() => {
      persistToastDismissed()
      setToastVisible(false)
    }, TOAST_AUTO_DISMISS_MS)
    return () => window.clearTimeout(handle)
  }, [toastVisible])

  const dismissToast = () => {
    persistToastDismissed()
    setToastVisible(false)
  }

  const handleMicClick = () => {
    if (!sttSupported) return
    if (isListening) {
      stop()
    } else {
      void start()
    }
  }

  return (
    <>
      {/* TTS on/off toggle — always visible when TTS is supported and not
          currently speaking. Lets users enable/disable read-aloud from the
          chat input without navigating to Settings. */}
      {ttsSupported && !isSpeaking && (
        <button
          type="button"
          onClick={handleTtsToggle}
          className={
            'p-2 rounded-lg shrink-0 mb-0.5 transition-colors ' +
            (ttsEnabled
              ? 'text-primary hover:bg-primary/20'
              : 'text-text-muted hover:bg-surface')
          }
          title={ttsEnabled ? 'Disable read-aloud' : 'Enable read-aloud'}
          aria-label={ttsEnabled ? 'Disable read-aloud' : 'Enable read-aloud'}
          aria-pressed={ttsEnabled}
        >
          {ttsEnabled ? (
            /* Speaker with waves — TTS on */
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M5.586 15H4a1 1 0 01-1-1v-4a1 1 0 011-1h1.586l4.707-4.707C10.923 3.663 12 4.109 12 5v14c0 .891-1.077 1.337-1.707.707L5.586 15z" />
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M15.536 8.464a5 5 0 010 7.072M18.364 5.636a9 9 0 010 12.728" />
            </svg>
          ) : (
            /* Speaker with X — TTS off */
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M5.586 15H4a1 1 0 01-1-1v-4a1 1 0 011-1h1.586l4.707-4.707C10.923 3.663 12 4.109 12 5v14c0 .891-1.077 1.337-1.707.707L5.586 15z" />
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M17 9l4 4m0-4l-4 4" />
            </svg>
          )}
        </button>
      )}

      {/* Stop-speaking button — only while TTS is currently speaking (R10.7).
          Also disables TTS so the next message won't auto-speak. */}
      {ttsSupported && isSpeaking && (
        <button
          type="button"
          onClick={handleStopSpeaking}
          className="p-2 rounded-lg bg-warning/20 hover:bg-warning/40 text-warning shrink-0 mb-0.5 transition-colors"
          title="Stop speaking (disables read-aloud)"
          aria-label="Stop speaking"
        >
          {/* Speaker with slash — universal "mute / cut audio" glyph. */}
          <svg
            className="w-5 h-5"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
            aria-hidden="true"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M5.586 15H4a1 1 0 01-1-1v-4a1 1 0 011-1h1.586l4.707-4.707C10.923 3.663 12 4.109 12 5v14c0 .891-1.077 1.337-1.707.707L5.586 15z"
            />
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M17 9l4 4m0-4l-4 4"
            />
          </svg>
        </button>
      )}

      {/* Microphone button — toggles STT (R10.1). Hidden entirely when STT
          is unsupported (R10.8). */}
      {sttSupported && (
        <button
          type="button"
          onClick={handleMicClick}
          className={
            'p-2 rounded-lg shrink-0 mb-0.5 transition-colors ' +
            (isListening
              ? 'bg-danger/80 hover:bg-danger/90 text-on-primary animate-pulse'
              : 'hover:bg-surface text-text-muted')
          }
          title={isListening ? 'Stop listening' : 'Start voice input'}
          aria-label={isListening ? 'Stop listening' : 'Start voice input'}
          aria-pressed={isListening}
        >
          {isListening ? (
            // Filled mic — listening state.
            <svg
              className="w-5 h-5"
              fill="currentColor"
              viewBox="0 0 24 24"
              aria-hidden="true"
            >
              <path d="M12 14a3 3 0 003-3V5a3 3 0 00-6 0v6a3 3 0 003 3z" />
              <path d="M19 11a1 1 0 10-2 0 5 5 0 01-10 0 1 1 0 10-2 0 7 7 0 006 6.93V20H8a1 1 0 100 2h8a1 1 0 100-2h-3v-2.07A7 7 0 0019 11z" />
            </svg>
          ) : (
            // Outline mic — idle state.
            <svg
              className="w-5 h-5"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
              aria-hidden="true"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M19 11v1a7 7 0 01-14 0v-1m7 7v3m-4 0h8M12 15a3 3 0 003-3V6a3 3 0 00-6 0v6a3 3 0 003 3z"
              />
            </svg>
          )}
        </button>
      )}

      {/* One-time unsupported-browser toast (R10.8). Rendered as a fixed
          floating banner so it doesn't disturb input-area layout. */}
      {toastVisible && (
        <div
          role="status"
          aria-live="polite"
          className="fixed bottom-24 left-1/2 -translate-x-1/2 z-50 max-w-sm rounded-lg border border-warning/40 bg-warning/90 px-4 py-2 text-sm text-on-warning shadow-lg backdrop-blur-sm"
        >
          <div className="flex items-start gap-3">
            <span className="flex-1">
              Voice input isn't available in this browser. Try Chrome, Edge,
              or Safari to talk to BowersHub AI.
            </span>
            <button
              type="button"
              onClick={dismissToast}
              className="text-on-warning/80 hover:text-on-warning font-bold"
              aria-label="Dismiss"
            >
              ×
            </button>
          </div>
        </div>
      )}
    </>
  )
}
