/**
 * VoiceInputButton — speech-to-text via the browser's Web Speech API.
 *
 * Uses SpeechRecognition (Chrome, Safari, Edge) for free, client-side
 * voice transcription. Hidden on browsers that don't support it.
 */
import { useCallback, useEffect, useRef, useState } from 'react'

interface Props {
  /** Called with interim transcript as the user speaks */
  onTranscript: (text: string) => void
  /** Called with the final transcript when recognition ends */
  onFinalTranscript: (text: string) => void
  /** Whether to auto-submit after final transcript */
  autoSend?: boolean
  /** If true, button is hidden */
  disabled?: boolean
}

// Check for SpeechRecognition support
const SpeechRecognitionClass =
  (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition

export default function VoiceInputButton({
  onTranscript,
  onFinalTranscript,
  autoSend = false,
  disabled = false,
}: Props) {
  const [isRecording, setIsRecording] = useState(false)
  const recognitionRef = useRef<any>(null)
  const finalTranscriptRef = useRef('')

  // Don't render if not supported
  if (!SpeechRecognitionClass || disabled) return null

  const startRecording = useCallback(() => {
    if (recognitionRef.current) return

    const recognition = new SpeechRecognitionClass()
    recognition.continuous = true
    recognition.interimResults = true
    recognition.lang = 'en-US'

    finalTranscriptRef.current = ''

    recognition.onresult = (event: any) => {
      let interim = ''
      let final = ''

      for (let i = 0; i < event.results.length; i++) {
        const result = event.results[i]
        if (result.isFinal) {
          final += result[0].transcript
        } else {
          interim += result[0].transcript
        }
      }

      finalTranscriptRef.current = final
      // Show both final + interim as the user speaks
      onTranscript(final + interim)
    }

    recognition.onerror = (event: any) => {
      console.warn('Speech recognition error:', event.error)
      setIsRecording(false)
      recognitionRef.current = null
    }

    recognition.onend = () => {
      setIsRecording(false)
      recognitionRef.current = null
      // Deliver the final transcript
      const text = finalTranscriptRef.current.trim()
      if (text) {
        onFinalTranscript(text)
      }
    }

    recognition.start()
    recognitionRef.current = recognition
    setIsRecording(true)
  }, [onTranscript, onFinalTranscript])

  const stopRecording = useCallback(() => {
    if (recognitionRef.current) {
      recognitionRef.current.stop()
    }
  }, [])

  const toggleRecording = useCallback(() => {
    if (isRecording) {
      stopRecording()
    } else {
      startRecording()
    }
  }, [isRecording, startRecording, stopRecording])

  // Clean up on unmount
  useEffect(() => {
    return () => {
      if (recognitionRef.current) {
        recognitionRef.current.abort()
        recognitionRef.current = null
      }
    }
  }, [])

  return (
    <button
      type="button"
      onClick={toggleRecording}
      className={`
        p-2 rounded-lg transition-all shrink-0
        ${isRecording
          ? 'bg-red-500/20 text-red-400 animate-pulse'
          : 'text-gray-400 hover:text-gray-200 hover:bg-gray-800/50'
        }
      `}
      title={isRecording ? 'Stop recording' : 'Voice input'}
      aria-label={isRecording ? 'Stop recording' : 'Start voice input'}
    >
      {isRecording ? (
        // Red recording dot
        <svg className="w-5 h-5" viewBox="0 0 24 24" fill="currentColor">
          <circle cx="12" cy="12" r="6" />
        </svg>
      ) : (
        // Microphone icon
        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 1a3 3 0 00-3 3v8a3 3 0 006 0V4a3 3 0 00-3-3z" />
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 10v2a7 7 0 01-14 0v-2" />
          <line x1="12" y1="19" x2="12" y2="23" strokeLinecap="round" />
          <line x1="8" y1="23" x2="16" y2="23" strokeLinecap="round" />
        </svg>
      )}
    </button>
  )
}
